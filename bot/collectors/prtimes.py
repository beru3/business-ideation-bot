"""prtimes コレクタ: PR TIMES全体RSSから供給側イベントを信号化する (日次実行)。

- フィード: https://prtimes.jp/index.rdf (RSS 1.0 / RDF形式、直近200件、実データ確認済み)
- タイトルに供給側イベントのキーワードを含むリリースのみ信号化
- stdlib (urllib + xml.etree) のみで実装。内部利用のみ・再配布禁止 (規約グレーの注意)
"""
from __future__ import annotations

import sys
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

if __package__:
    from . import common
else:
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    import common  # type: ignore

FEED_URL = "https://prtimes.jp/index.rdf"
REQUEST_TIMEOUT = 60

# 供給側イベントのキーワード (タイトルに含まれるもののみ信号化)
KEYWORDS: tuple[str, ...] = (
    "サービス終了",
    "提供終了",
    "サポート終了",
    "価格改定",
    "値上げ",
    "料金改定",
    "事業譲渡",
    "吸収合併",
    "事業承継",
    "生産終了",
)

_NS = {
    "rss": "http://purl.org/rss/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def match_keywords(title: str) -> list[str]:
    """タイトルに含まれる供給側イベントキーワードのリストを返す。"""
    return [kw for kw in KEYWORDS if kw in title]


def parse_feed(xml_bytes: bytes) -> list[dict[str, str]]:
    """RDFフィードをパースし item のリスト (title/link/description/date) を返す。"""
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.findall("rss:item", _NS):
        items.append({
            "title": (item.findtext("rss:title", "", _NS) or "").strip(),
            "link": (item.findtext("rss:link", "", _NS) or "").strip(),
            "description": (item.findtext("rss:description", "", _NS) or "").strip(),
            "date": (item.findtext("dc:date", "", _NS) or "").strip(),
        })
    return items


def collect() -> list[dict[str, Any]]:
    """フィードを取得し、キーワードにマッチするリリースを信号化する。"""
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0 (business-ideation-bot)"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as res:
        xml_bytes = res.read()

    items = parse_feed(xml_bytes)
    print(f"[prtimes] フィード取得: {len(items)}件")

    signals: list[dict[str, Any]] = []
    for item in items:
        if not item["title"] or not item["link"]:
            continue
        matched = match_keywords(item["title"])
        if not matched:
            continue
        signals.append(common.build_signal(
            source="prtimes",
            native_id=item["link"],
            title=item["title"],
            body=item["description"],
            url=item["link"],
            raw_category=matched[0],
            meta={"published_at": item["date"], "matched_keywords": matched},
        ))
    print(f"[prtimes] キーワードマッチ: {len(signals)}件")
    return signals


if __name__ == "__main__":
    common.run_collector("prtimes", collect)
