"""youtube コレクタ: 監視チャンネルの新着動画コメントからニーズ語を含むものを信号化する (日次実行)。

- 動画の発見: チャンネルRSS (無料・APIクォータ消費なし・stdlibで取得)
    https://www.youtube.com/feeds/videos.xml?channel_id=UC...
  Atom形式。各entryの yt:videoId / published を使い「公開90日以内・チャンネルあたり
  最新5本」を監視対象に自動選定する (静的動画リストの鮮度枯れ対策、2026-07-26改修)
- コメント取得: YouTube Data API v3 commentThreads.list (公式ドキュメントで確認済み)
    GET https://www.googleapis.com/youtube/v3/commentThreads
    part=snippet, videoId=..., maxResults=100 (上限100), order=time,
    textFormat=plainText, key=APIキー
  クォータ: 1リクエスト = 1 unit (無料枠 10,000 unit/日)。15ch×最大5本=75 unit/日以内
  コメント無効の動画は 403 (commentsDisabled)
- APIキー: 環境変数 YOUTUBE_API_KEY (未設定時はスキップ、エラーにしない)
- 対象: bot/data/monitored-channels.json の各チャンネル。ニーズ語正規表現マッチのみ信号化
- ニーズ語は high/low の2層 (2026-07-26改修)。lowも収集する (非LLM層は意味判断を
  しない・トリアージ側が meta.need_tier でフィルタする)
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

if __package__:
    from . import common
else:
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    import common  # type: ignore

API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
API_KEY_ENV = "YOUTUBE_API_KEY"
RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
MONITORED_FILE = "monitored-channels.json"
MAX_RESULTS = 100
REQUEST_TIMEOUT = 60
MAX_VIDEO_AGE_DAYS = 90  # 公開90日以内の動画のみ監視 (鮮度優先)
VIDEOS_PER_CHANNEL = 5  # チャンネルあたり最新5本まで

# ニーズ語 HIGH層: 具体的なツール・ドメイン文脈を伴うパターン (高信頼)
NEED_PATTERNS_HIGH: tuple[str, ...] = (
    r"アプリ(?:が|は|も)?な(?:い|くて|さそう)",
    r"アプリ(?:を)?探し",
    r"ツール(?:が|は|も)?な(?:い|くて|さそう)",
    r"作って(?:ほしい|欲しい|ください|くれ)",
    r"あったらいい",
    r"あればいい",
    r"有料でも",
    r"どうやって管理",
    r"自動化(?:したい|できたら|できれば)",
    r"(?:いい|良い|おすすめの)(?:アプリ|ツール|サービス)(?:を)?(?:教えて|ない)",
    r"探して(?:も|る(?:けど|が))?見つから",
    r"(?:おすすめ|オススメ)の?(?:アプリ|ツール|ソフト|サイト|やり方)",
    r"(?:アプリ|ツール|ソフト)(?:とか|って)?あり(?:ま)?せんか",
    r"(?:何|なに|どの)(?:の|か)?(?:アプリ|ソフト|ツール)(?:を|で|が)",
    r"(?:管理|入力|記録|申告|手続き?)(?:が|は|も)?(?:大変|面倒|めんどう|めんどくさ|難し)",
    r"探して(?:い)?ます",
    # 2026-07-26: 文脈必須型の「教えて」— ツール/実務語が同一文内で先行する場合のみHIGH
    r"(?:アプリ|ツール|ソフト|サイト|サービス|やり方|方法|管理|申告|手続き|設定)[^。！？!?\n]{0,30}教えて(?:ください|下さい|ほしい|欲しい|いただけ)",
)

# ニーズ語 LOW層: 丁寧な依頼一般にマッチする広いパターン (補助証拠)。
# 2026-07-26: 初回36件の78%が文脈なし「教えてください」で誤爆したためLOWに降格
NEED_PATTERNS_LOW: tuple[str, ...] = (
    r"教えて(?:ください|下さい|ほしい|欲しい|いただけ)",
    r"どう(?:やって|すれば)(?:いい|良い)",
)

# 既存テスト互換のため全パターンの結合も保持
NEED_PATTERNS: tuple[str, ...] = NEED_PATTERNS_HIGH + NEED_PATTERNS_LOW

_COMPILED_HIGH = tuple(re.compile(p) for p in NEED_PATTERNS_HIGH)
_COMPILED_LOW = tuple(re.compile(p) for p in NEED_PATTERNS_LOW)
_HIGH_SET = frozenset(NEED_PATTERNS_HIGH)

_ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}


def match_needs(text: str) -> list[str]:
    """テキストにマッチしたニーズ語パターン(文字列)のリストを返す (high+low両層)。"""
    matched = [p.pattern for p in _COMPILED_HIGH if p.search(text)]
    matched.extend(p.pattern for p in _COMPILED_LOW if p.search(text))
    return matched


def classify_tier(matched: list[str]) -> str:
    """マッチ結果の信頼度層。HIGHを1つでも含めば high、LOWのみなら low。"""
    return "high" if any(p in _HIGH_SET for p in matched) else "low"


def comment_age_days(published_at: str | None, now: datetime | None = None) -> int | None:
    """publishedAt (ISO8601, 例 2021-05-01T12:34:56Z) から経過日数。パース不能は None。"""
    if not published_at:
        return None
    try:
        published = datetime.fromisoformat(published_at)
    except ValueError:
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0, (now - published).days)


def parse_channel_rss(xml_bytes: bytes) -> list[dict[str, str]]:
    """チャンネルRSS (Atom) をパースし entry のリスト (video_id/title/published) を返す。"""
    root = ET.fromstring(xml_bytes)
    entries = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        video_id = (entry.findtext("yt:videoId", "", _ATOM_NS) or "").strip()
        if not video_id:
            continue
        entries.append({
            "video_id": video_id,
            "title": (entry.findtext("atom:title", "", _ATOM_NS) or "").strip(),
            "published": (entry.findtext("atom:published", "", _ATOM_NS) or "").strip(),
        })
    return entries


def select_recent_videos(
    entries: list[dict[str, str]],
    max_age_days: int = MAX_VIDEO_AGE_DAYS,
    per_channel: int = VIDEOS_PER_CHANNEL,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """公開 max_age_days 日以内の動画を公開日降順で per_channel 本まで選定する。"""
    now = now or datetime.now(timezone.utc)
    recent = []
    for entry in entries:
        age = comment_age_days(entry.get("published"), now=now)
        if age is None or age > max_age_days:
            continue
        recent.append(entry)
    recent.sort(key=lambda e: e.get("published", ""), reverse=True)
    return recent[:per_channel]


def _fetch_channel_videos(channel_id: str) -> list[dict[str, str]]:
    """1チャンネルのRSSから監視対象動画を選定する (クォータ消費なし)。"""
    url = RSS_URL.format(channel_id=channel_id)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (business-ideation-bot)"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as res:
        entries = parse_channel_rss(res.read())
    selected = select_recent_videos(entries)
    print(f"[youtube] {channel_id}: RSS {len(entries)}本 → 90日以内の新しい順 {len(selected)}本")
    return selected


def _fetch_comment_threads(video_id: str, api_key: str) -> list[dict[str, Any]]:
    """1動画の新着コメントスレッドを取得する (1ページ=最大100件, 1 unit)。"""
    params = {
        "part": "snippet",
        "videoId": video_id,
        "maxResults": MAX_RESULTS,
        "order": "time",
        "textFormat": "plainText",
        "key": api_key,
    }
    url = f"{API_URL}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as res:
        return json.load(res).get("items", [])


def thread_to_signal(
    video_id: str,
    item: dict[str, Any],
    matched: list[str],
    channel_id: str = "",
) -> dict[str, Any]:
    """commentThreads の1アイテムを共通スキーマの信号に変換する。"""
    snippet = item["snippet"]["topLevelComment"]["snippet"]
    comment_id = item.get("id", "")
    published_at = snippet.get("publishedAt")
    return common.build_signal(
        source="youtube",
        native_id=comment_id,
        title=f"[{video_id}] コメント by {snippet.get('authorDisplayName', '')}",
        body=snippet.get("textOriginal") or snippet.get("textDisplay") or "",
        url=f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}",
        raw_category="need_comment",
        meta={
            "video_id": video_id,
            "channel_id": channel_id,
            "author": snippet.get("authorDisplayName"),
            "published_at": published_at,
            "age_days": comment_age_days(published_at),
            "like_count": snippet.get("likeCount"),
            "matched_patterns": matched,
            "need_tier": classify_tier(matched),
        },
    )


def _collect_video(video_id: str, api_key: str, channel_id: str = "") -> list[dict[str, Any]]:
    """1動画のコメントを取得しニーズ語でフィルタする。"""
    items = _fetch_comment_threads(video_id, api_key)
    signals = []
    for item in items:
        try:
            text = item["snippet"]["topLevelComment"]["snippet"].get("textOriginal", "")
        except (KeyError, TypeError):
            continue
        matched = match_needs(text)
        if matched:
            signals.append(thread_to_signal(video_id, item, matched, channel_id=channel_id))
    print(f"[youtube] {video_id}: コメント{len(items)}件 → ニーズ語 {len(signals)}件")
    return signals


def collect() -> list[dict[str, Any]]:
    """監視チャンネルの新着動画を巡回する。個別失敗は警告に留め、全滅時のみ例外。"""
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        # シークレット未設定時はスキップ (エラーにしない)
        print(f"[youtube] SKIP: 環境変数 {API_KEY_ENV} が未設定です")
        sys.exit(0)

    channels = common.load_monitored(MONITORED_FILE, "channels")
    if not channels:
        print("[youtube] 監視対象チャンネルなし (monitored-channels.json が空)")
        return []

    signals: list[dict[str, Any]] = []
    failures: list[str] = []
    for channel in channels:
        channel_id = channel.get("channel_id")
        if not channel_id:
            print(f"[youtube] WARN: channel_id がありません: {channel!r}", file=sys.stderr)
            continue
        try:
            videos = _fetch_channel_videos(channel_id)
        except Exception as exc:
            failures.append(channel_id)
            print(f"[youtube] WARN: {channel_id} RSS取得失敗: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        for video in videos:
            video_id = video["video_id"]
            try:
                signals.extend(_collect_video(video_id, api_key, channel_id=channel_id))
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:300]
                except OSError:
                    pass
                # コメント無効(403)等は動画単位の警告に留める (チャンネル失敗とは数えない)
                print(f"[youtube] WARN: {video_id} 取得失敗 HTTP {exc.code}: {detail}", file=sys.stderr)
            except Exception as exc:
                print(f"[youtube] WARN: {video_id} 取得失敗: {type(exc).__name__}: {exc}", file=sys.stderr)

    if failures and len(failures) == len(channels):
        raise RuntimeError(f"全{len(channels)}チャンネルのRSS取得に失敗: {', '.join(failures)}")
    return signals


if __name__ == "__main__":
    common.run_collector("youtube", collect)
