"""youtube コレクタ: 監視動画の新着コメントからニーズ語を含むものを信号化する (日次実行)。

- API: YouTube Data API v3 commentThreads.list (公式ドキュメントで確認済み)
    GET https://www.googleapis.com/youtube/v3/commentThreads
    part=snippet, videoId=..., maxResults=100 (上限100), order=time,
    textFormat=plainText, key=APIキー
  クォータ: 1リクエスト = 1 unit (無料枠 10,000 unit/日)
  コメント無効の動画は 403 (commentsDisabled)
- APIキー: 環境変数 YOUTUBE_API_KEY (未設定時はスキップ、エラーにしない)
- 対象: bot/data/monitored-videos.json の各動画。ニーズ語正規表現マッチのみ信号化
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

if __package__:
    from . import common
else:
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    import common  # type: ignore

API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
API_KEY_ENV = "YOUTUBE_API_KEY"
MONITORED_FILE = "monitored-videos.json"
MAX_RESULTS = 100
REQUEST_TIMEOUT = 60

# ニーズ語 (いずれかにマッチするコメントのみ信号化)
NEED_PATTERNS: tuple[str, ...] = (
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
)

_COMPILED = tuple(re.compile(p) for p in NEED_PATTERNS)


def match_needs(text: str) -> list[str]:
    """テキストにマッチしたニーズ語パターン(文字列)のリストを返す。"""
    return [p.pattern for p in _COMPILED if p.search(text)]


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


def thread_to_signal(video_id: str, item: dict[str, Any], matched: list[str]) -> dict[str, Any]:
    """commentThreads の1アイテムを共通スキーマの信号に変換する。"""
    snippet = item["snippet"]["topLevelComment"]["snippet"]
    comment_id = item.get("id", "")
    return common.build_signal(
        source="youtube",
        native_id=comment_id,
        title=f"[{video_id}] コメント by {snippet.get('authorDisplayName', '')}",
        body=snippet.get("textOriginal") or snippet.get("textDisplay") or "",
        url=f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}",
        raw_category="need_comment",
        meta={
            "video_id": video_id,
            "author": snippet.get("authorDisplayName"),
            "published_at": snippet.get("publishedAt"),
            "like_count": snippet.get("likeCount"),
            "matched_patterns": matched,
        },
    )


def _collect_video(video_id: str, api_key: str) -> list[dict[str, Any]]:
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
            signals.append(thread_to_signal(video_id, item, matched))
    print(f"[youtube] {video_id}: コメント{len(items)}件 → ニーズ語 {len(signals)}件")
    return signals


def collect() -> list[dict[str, Any]]:
    """監視対象動画を巡回する。コメント無効(403)等の個別失敗は警告に留める。"""
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        # シークレット未設定時はスキップ (エラーにしない)
        print(f"[youtube] SKIP: 環境変数 {API_KEY_ENV} が未設定です")
        sys.exit(0)

    videos = common.load_monitored(MONITORED_FILE, "videos")
    if not videos:
        print("[youtube] 監視対象動画なし (monitored-videos.json が空)")
        return []

    signals: list[dict[str, Any]] = []
    failures: list[str] = []
    for video in videos:
        video_id = video.get("video_id")
        if not video_id:
            print(f"[youtube] WARN: video_id がありません: {video!r}", file=sys.stderr)
            continue
        try:
            signals.extend(_collect_video(video_id, api_key))
        except urllib.error.HTTPError as exc:
            failures.append(video_id)
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except OSError:
                pass
            print(f"[youtube] WARN: {video_id} 取得失敗 HTTP {exc.code}: {detail}", file=sys.stderr)
        except Exception as exc:
            failures.append(video_id)
            print(f"[youtube] WARN: {video_id} 取得失敗: {type(exc).__name__}: {exc}", file=sys.stderr)

    if failures and len(failures) == len(videos):
        raise RuntimeError(f"全{len(videos)}動画の取得に失敗: {', '.join(failures)}")
    return signals


if __name__ == "__main__":
    common.run_collector("youtube", collect)
