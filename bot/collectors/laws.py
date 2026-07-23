"""laws コレクタ: e-Gov法令API v2 の更新法令一覧から施行日接近の法令を信号化する。

施行日が「今日から3-5ヶ月先」の窓に入る改正法令を検知する (週次実行)。

API仕様 (https://laws.e-gov.go.jp/api/2/swagger-ui で確認済み):
- GET https://laws.e-gov.go.jp/api/2/laws
- 認証不要。limit最大1000・next_offsetでページング (全法令 約9,500件 ≒ 10リクエスト)
- asof=窓の終端 を指定すると、その時点で最新の改正履歴が revision_info に入る
  (施行前の改正は current_revision_status="UnEnforced" として現れる)
- order パラメータの挙動が不安定なため、全件走査 + クライアント側で
  amendment_enforcement_date / amendment_scheduled_enforcement_date を窓判定する
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

if __package__:
    from . import common
else:  # スクリプト直接実行 (python bot/collectors/laws.py)
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    import common  # type: ignore

API_BASE = "https://laws.e-gov.go.jp/api/2"
PAGE_LIMIT = 1000
REQUEST_TIMEOUT = 60
WINDOW_START_MONTHS = 3
WINDOW_END_MONTHS = 5


def add_months(base: date, months: int) -> date:
    """月単位の日付加算。存在しない日(例: 1/31 + 3ヶ月)は月末に丸める。"""
    total = base.year * 12 + (base.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    # 月末丸め
    for day in (base.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError(f"invalid date: {year}-{month}")


def enforcement_date_in_window(
    revision: dict[str, Any], window_start: date, window_end: date
) -> str | None:
    """revision_info の施行日が窓に入る場合その日付文字列を返す。入らなければ None。"""
    for field in ("amendment_enforcement_date", "amendment_scheduled_enforcement_date"):
        value = revision.get(field)
        if not value:
            continue
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            continue
        if window_start <= parsed <= window_end:
            return value
    return None


def _fetch_page(asof: date, offset: int) -> dict[str, Any]:
    """法令一覧APIを1ページ取得する。"""
    params = {
        "asof": asof.isoformat(),
        "limit": PAGE_LIMIT,
        "offset": offset,
        "omit_current_revision_info": "true",
        "response_format": "json",
    }
    url = f"{API_BASE}/laws?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "business-ideation-bot/1.0"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as res:
        return json.load(res)


def _to_signal(law: dict[str, Any], enforcement_date: str) -> dict[str, Any]:
    """APIレスポンスの1法令を共通スキーマの信号に変換する。"""
    info = law.get("law_info", {})
    revision = law.get("revision_info", {})
    law_id = info.get("law_id", "")
    native_id = revision.get("law_revision_id") or f"{law_id}_{enforcement_date}"

    amendment_title = revision.get("amendment_law_title") or ""
    amendment_num = revision.get("amendment_law_num") or ""
    body_parts = [f"施行日: {enforcement_date}"]
    if amendment_title:
        body_parts.append(f"改正法令: {amendment_title} ({amendment_num})")
    comment = revision.get("amendment_enforcement_comment")
    if comment:
        body_parts.append(f"施行注記: {comment}")

    return common.build_signal(
        source="laws",
        native_id=native_id,
        title=f"{revision.get('law_title', law_id)} (施行 {enforcement_date})",
        body=" / ".join(body_parts),
        url=f"https://laws.e-gov.go.jp/law/{law_id}",
        raw_category=revision.get("category") or "",
        meta={
            "law_id": law_id,
            "law_num": info.get("law_num"),
            "enforcement_date": enforcement_date,
            "amendment_law_id": revision.get("amendment_law_id"),
            "current_revision_status": revision.get("current_revision_status"),
            "mission": revision.get("mission"),
        },
    )


def collect() -> list[dict[str, Any]]:
    """全法令を走査し、施行日が窓に入る改正法令を信号化する。"""
    today = date.today()
    window_start = add_months(today, WINDOW_START_MONTHS)
    window_end = add_months(today, WINDOW_END_MONTHS)
    print(f"[laws] 施行日窓: {window_start} 〜 {window_end}")

    signals: list[dict[str, Any]] = []
    offset: int | None = 0
    pages = 0
    while offset is not None:
        page = _fetch_page(asof=window_end, offset=offset)
        pages += 1
        for law in page.get("laws", []):
            revision = law.get("revision_info", {})
            matched = enforcement_date_in_window(revision, window_start, window_end)
            if matched:
                signals.append(_to_signal(law, matched))
        offset = page.get("next_offset")
        if pages > 30:  # 想定外のページ数は打ち切り (全法令 約9,500件 = 10ページ)
            raise RuntimeError(f"ページ数が想定を超過: {pages}ページ目で中断")
    print(f"[laws] {pages}ページ走査, 窓内 {len(signals)}件")
    return signals


if __name__ == "__main__":
    common.run_collector("laws", collect)
