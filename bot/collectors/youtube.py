"""youtube コレクタ: 監視チャンネル新着 + 固定evergreen動画のコメントからニーズ語を信号化する (日次実行)。

2階建て構成 (v3.2 / 2026-07-26。v3.1初回の学習「テーマ精度の小規模動画と母数の
人気動画の2階建てで持つ」の正式実装):
1. チャンネルRSS (無料・APIクォータ消費なし・stdlibで取得)
     https://www.youtube.com/feeds/videos.xml?channel_id=UC...
   Atom形式。各entryの yt:videoId / published からRSS掲載分 (最大15本) を監視対象に
   自動選定する。当初の「公開90日窓」は撤廃 — ニーズはevergreen動画 (確定申告の
   やり方等) に長期でコメントされ続けるため、90日窓は成果源を除外していた (実測:
   freee農業簿記告発を生んだ農Tube委員会を含む4chが空振り)
2. 固定動画リスト bot/data/monitored-videos.json (任意・無ければスキップ)。
   信号実績のあるevergreen動画を明示的に監視し続ける。meta.via="pinned" で区別

- コメント取得: YouTube Data API v3 commentThreads.list (公式ドキュメントで確認済み)
    GET https://www.googleapis.com/youtube/v3/commentThreads
    part=snippet, videoId=..., maxResults=100 (上限100), order=time,
    textFormat=plainText, key=APIキー
  クォータ: 1リクエスト = 1 unit (無料枠 10,000 unit/日)。15ch×最大15本+固定10本
  ≒ 235 unit/日 (無料枠の2.4%)
  コメント無効の動画は 403 (commentsDisabled)
- APIキー: 環境変数 YOUTUBE_API_KEY (未設定時はスキップ、エラーにしない)
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
PINNED_FILE = "monitored-videos.json"  # 固定evergreen動画 (任意)
MAX_RESULTS = 100
REQUEST_TIMEOUT = 60
VIDEOS_PER_CHANNEL = 15  # RSS掲載分 (YouTube仕様の上限15本) を全て監視。90日窓は撤廃 (v3.2)

# ニーズ語 HIGH層: 具体的なツール・ドメイン文脈を伴うパターン (高信頼)
NEED_PATTERNS_HIGH: tuple[str, ...] = (
    r"アプリ(?:が|は|も)?な(?:い|くて|さそう)",
    r"アプリ(?:を)?探し",
    r"ツール(?:が|は|も)?な(?:い|くて|さそう)",
    # 「作ってくれている人」等の叙述表現を除くため、依頼形のみに限定 (2026-07-26)
    r"作って(?:ほしい|欲しい|ください|くれない|くれませんか|くれ[!！]|くれ$)",
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

# ペイン語 PAIN層 (v3.2 / 2026-07-26): 明示的なツール要求ではなく「経験談として
# 語られる不満・自前計算」を拾う。軽貨物102コメントの実地検証で判明した欠落 —
# ドメイン不満は「アプリが欲しい」ではなく「時給計算すると割に合わん」の形で現れる。
# 実測: 特異度99.9% (雑談1,451件で誤爆2) / 感度12.7% (軽貨物102件で13検出)
NEED_PATTERNS_PAIN: tuple[str, ...] = (
    r"割に合わ",
    r"時給(?:換算|計算)(?:する|した)?と",
    r"実質(?:時給|手取り)",
    r"経費(?:が|も)?(?:自腹|自己負担|持ち|かかりすぎ)",
    r"(?:ガソリン|燃料)代?(?:を)?(?:差し引|自腹|自己負担)",
    r"手(?:取り|元に残る|元に残った)(?:は|が)?\d+万?",
    r"(?:儲かり|儲から|稼げ)(?:ない|ません|まへん|ん(?:わ|よ|。|$))",
    r"(?:補償|保証|保障)(?:も|が)?(?:ない|無い|無し|なし)",
    r"自腹",
)

# ニーズ語 LOW層: 丁寧な依頼一般にマッチする広いパターン (補助証拠)。
# 2026-07-26: 初回36件の78%が文脈なし「教えてください」で誤爆したためLOWに降格
NEED_PATTERNS_LOW: tuple[str, ...] = (
    r"教えて(?:ください|下さい|ほしい|欲しい|いただけ)",
    r"どう(?:やって|すれば)(?:いい|良い)",
)

# 既存テスト互換のため全パターンの結合も保持
NEED_PATTERNS: tuple[str, ...] = NEED_PATTERNS_HIGH + NEED_PATTERNS_PAIN + NEED_PATTERNS_LOW

_COMPILED_HIGH = tuple(re.compile(p) for p in NEED_PATTERNS_HIGH)
_COMPILED_PAIN = tuple(re.compile(p) for p in NEED_PATTERNS_PAIN)
_COMPILED_LOW = tuple(re.compile(p) for p in NEED_PATTERNS_LOW)
_HIGH_SET = frozenset(NEED_PATTERNS_HIGH)
_PAIN_SET = frozenset(NEED_PATTERNS_PAIN)

_ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}


def match_needs(text: str) -> list[str]:
    """テキストにマッチしたニーズ語パターン(文字列)のリストを返す (high+pain+low全層)。"""
    matched = [p.pattern for p in _COMPILED_HIGH if p.search(text)]
    matched.extend(p.pattern for p in _COMPILED_PAIN if p.search(text))
    matched.extend(p.pattern for p in _COMPILED_LOW if p.search(text))
    return matched


def classify_tier(matched: list[str]) -> str:
    """マッチ結果の信頼度層。high (明示的ツール要求) > pain (不満・収支語り) > low (丁寧な依頼一般)。"""
    if any(p in _HIGH_SET for p in matched):
        return "high"
    if any(p in _PAIN_SET for p in matched):
        return "pain"
    return "low"


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
    max_age_days: int | None = None,
    per_channel: int = VIDEOS_PER_CHANNEL,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """動画を公開日降順で per_channel 本まで選定する。

    max_age_days=None (既定) は日数フィルタなし — ニーズはevergreen動画に長期で
    コメントされ続けるため、鮮度で絞らない (v3.2で90日窓を撤廃)。日数を指定した
    場合のみ公開日ベースで絞り込む (published が不正な行は除外)。
    """
    now = now or datetime.now(timezone.utc)
    selected = []
    for entry in entries:
        if max_age_days is not None:
            age = comment_age_days(entry.get("published"), now=now)
            if age is None or age > max_age_days:
                continue
        selected.append(entry)
    selected.sort(key=lambda e: e.get("published", ""), reverse=True)
    return selected[:per_channel]


def _fetch_channel_videos(channel_id: str) -> list[dict[str, str]]:
    """1チャンネルのRSSから監視対象動画を選定する (クォータ消費なし)。"""
    url = RSS_URL.format(channel_id=channel_id)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (business-ideation-bot)"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as res:
        entries = parse_channel_rss(res.read())
    selected = select_recent_videos(entries)
    print(f"[youtube] {channel_id}: RSS {len(entries)}本 → 監視対象 {len(selected)}本")
    return selected


def merge_video_targets(
    channel_videos: list[tuple[str, str]],
    pinned_videos: list[str],
) -> list[tuple[str, str, str]]:
    """(video_id, channel_id) のRSS由来リストと固定動画リストを統合する。

    戻り値: (video_id, channel_id, via) のリスト。via は "channel_rss" | "pinned"。
    同一動画が両方に載る場合はRSS由来を優先 (重複巡回しない)。
    """
    targets: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for video_id, channel_id in channel_videos:
        if video_id in seen:
            continue
        seen.add(video_id)
        targets.append((video_id, channel_id, "channel_rss"))
    for video_id in pinned_videos:
        if video_id in seen:
            continue
        seen.add(video_id)
        targets.append((video_id, "", "pinned"))
    return targets


def _load_pinned_videos() -> list[str]:
    """固定evergreen動画リストを読む。ファイルが無ければ空 (任意ファイル)。"""
    try:
        entries = common.load_monitored(PINNED_FILE, "videos")
    except FileNotFoundError:
        return []
    return [e["video_id"] for e in entries if e.get("video_id")]


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
    via: str = "channel_rss",
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
            "via": via,
            "author": snippet.get("authorDisplayName"),
            "published_at": published_at,
            "age_days": comment_age_days(published_at),
            "like_count": snippet.get("likeCount"),
            "matched_patterns": matched,
            "need_tier": classify_tier(matched),
        },
    )


def _collect_video(
    video_id: str, api_key: str, channel_id: str = "", via: str = "channel_rss"
) -> list[dict[str, Any]]:
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
            signals.append(thread_to_signal(video_id, item, matched, channel_id=channel_id, via=via))
    print(f"[youtube] {video_id} ({via}): コメント{len(items)}件 → ニーズ語 {len(signals)}件")
    return signals


def collect() -> list[dict[str, Any]]:
    """監視チャンネルRSS + 固定動画の2階建てで巡回する。個別失敗は警告に留め、全滅時のみ例外。"""
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        # シークレット未設定時はスキップ (エラーにしない)
        print(f"[youtube] SKIP: 環境変数 {API_KEY_ENV} が未設定です")
        sys.exit(0)

    channels = common.load_monitored(MONITORED_FILE, "channels")
    pinned = _load_pinned_videos()
    if not channels and not pinned:
        print("[youtube] 監視対象なし (monitored-channels.json / monitored-videos.json とも空)")
        return []

    channel_videos: list[tuple[str, str]] = []
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
        channel_videos.extend((v["video_id"], channel_id) for v in videos)

    if channels and failures and len(failures) == len(channels):
        raise RuntimeError(f"全{len(channels)}チャンネルのRSS取得に失敗: {', '.join(failures)}")

    targets = merge_video_targets(channel_videos, pinned)
    print(f"[youtube] 監視対象動画: {len(targets)}本 (RSS由来 {len(channel_videos)} / 固定 {len(pinned)})")

    signals: list[dict[str, Any]] = []
    for video_id, channel_id, via in targets:
        try:
            signals.extend(_collect_video(video_id, api_key, channel_id=channel_id, via=via))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except OSError:
                pass
            # コメント無効(403)等は動画単位の警告に留める (全滅判定には含めない)
            print(f"[youtube] WARN: {video_id} 取得失敗 HTTP {exc.code}: {detail}", file=sys.stderr)
        except Exception as exc:
            print(f"[youtube] WARN: {video_id} 取得失敗: {type(exc).__name__}: {exc}", file=sys.stderr)
    return signals


if __name__ == "__main__":
    common.run_collector("youtube", collect)
