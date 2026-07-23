"""gplay コレクタ: Google Play の監視アプリの低評価レビューを信号化する (日次実行)。

- ライブラリ: google-play-scraper (PyPI, JoMingyu/google-play-scraper)。実APIで確認済み:
    from google_play_scraper import Sort, reviews
    result, token = reviews(app_id, lang=, country=, sort=Sort.NEWEST, count=)
  レビューdictのキー: reviewId, userName, content, score, at (datetime),
  thumbsUpCount, appVersion 等
- 対象: bot/data/monitored-apps.json の各アプリ。score<=2 のみ信号化
- 規約グレー・内部利用のみ。1アプリの失敗は他アプリを巻き込まない
"""
from __future__ import annotations

import sys
from typing import Any

if __package__:
    from . import common
else:
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    import common  # type: ignore

MONITORED_FILE = "monitored-apps.json"
MAX_SCORE = 2  # ★1-2 のみ
FETCH_COUNT = 100  # 新着から取得する件数 (重複はcommon側で排除)
DEFAULT_LANG = "ja"
DEFAULT_COUNTRY = "jp"


def review_to_signal(app_id: str, review: dict[str, Any]) -> dict[str, Any]:
    """google-play-scraper のレビューdictを共通スキーマの信号に変換する。"""
    at = review.get("at")
    return common.build_signal(
        source="gplay",
        native_id=str(review["reviewId"]),
        title=f"[{app_id}] ★{review.get('score')} レビュー",
        body=review.get("content") or "",
        url=f"https://play.google.com/store/apps/details?id={app_id}",
        raw_category=f"score_{review.get('score')}",
        meta={
            "app_id": app_id,
            "score": review.get("score"),
            "reviewed_at": at.isoformat() if hasattr(at, "isoformat") else str(at or ""),
            "thumbs_up_count": review.get("thumbsUpCount"),
            "app_version": review.get("appVersion"),
        },
    )


def _fetch_app_reviews(app: dict[str, Any]) -> list[dict[str, Any]]:
    """1アプリの新着レビューを取得し、score<=MAX_SCORE のみ信号化する。"""
    from google_play_scraper import Sort, reviews  # 遅延import (ワークフローでpip install)

    app_id = app.get("app_id")
    if not app_id:
        raise ValueError(f"app_id がありません: {app!r}")

    result, _token = reviews(
        app_id,
        lang=app.get("lang", DEFAULT_LANG),
        country=app.get("country", DEFAULT_COUNTRY),
        sort=Sort.NEWEST,
        count=FETCH_COUNT,
    )
    low = [r for r in result if isinstance(r.get("score"), int) and r["score"] <= MAX_SCORE]
    print(f"[gplay] {app_id}: 取得{len(result)}件 → ★{MAX_SCORE}以下 {len(low)}件")
    return [review_to_signal(app_id, r) for r in low]


def collect() -> list[dict[str, Any]]:
    """監視対象アプリを巡回する。一部アプリの失敗は警告に留め、全滅時のみ例外。"""
    apps = common.load_monitored(MONITORED_FILE, "apps")
    if not apps:
        print("[gplay] 監視対象アプリなし (monitored-apps.json が空)")
        return []

    signals: list[dict[str, Any]] = []
    failures: list[str] = []
    for app in apps:
        try:
            signals.extend(_fetch_app_reviews(app))
        except Exception as exc:
            app_id = app.get("app_id", "?")
            failures.append(app_id)
            print(f"[gplay] WARN: {app_id} の取得失敗: {type(exc).__name__}: {exc}", file=sys.stderr)

    if failures and len(failures) == len(apps):
        raise RuntimeError(f"全{len(apps)}アプリの取得に失敗: {', '.join(failures)}")
    return signals


if __name__ == "__main__":
    common.run_collector("gplay", collect)
