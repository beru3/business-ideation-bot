"""prtimes コレクタ: PR TIMES全体RSSから供給側イベントを信号化する (1日5回実行)。

- フィード: https://prtimes.jp/index.rdf (RSS 1.0 / RDF形式、直近200件、実データ確認済み)
- PR TIMESは1日1,000本超の配信があり、フィードは直近200件しか持たないため
  日次1回では大半を取りこぼす。collect-prtimes.yml で1日5回ポーリングする
  (重複はcommon側のid照合で排除)
- タイトルまたは説明文に供給側イベントのキーワードを含むリリースのみ信号化
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

# 供給側イベントのキーワード (タイトルまたは説明文に含まれるもののみ信号化)
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
    # 2026-07拡張: 供給側イベントの語彙補強 (タイトル+説明文マッチ化に伴う)。
    # 意図的除外: 単体「統合」(システム統合で誤爆) / 単体「改定」(規約改定で誤爆) /
    # 「受付終了」(イベント申込締切で誤爆)
    "撤退",
    "終売",
    "販売終了",
    "事業終了",
    "営業終了",
    "経営統合",
    "サービス統合",
    "移管",
    "新規受付停止",
)

_NS = {
    "rss": "http://purl.org/rss/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def match_keywords(text: str) -> list[str]:
    """テキストに含まれる供給側イベントキーワードのリストを返す。"""
    return [kw for kw in KEYWORDS if kw in text]


def match_release(title: str, description: str) -> tuple[list[str], str]:
    """タイトル→説明文の順でキーワード照合し、(マッチ一覧, マッチ箇所) を返す。

    タイトルマッチはトリアージで優位に扱うため、マッチ箇所 ("title"/"description")
    を区別して返す。両方マッチしない場合は ([], "")。
    """
    matched = match_keywords(title)
    if matched:
        return matched, "title"
    matched = match_keywords(description)
    if matched:
        return matched, "description"
    return [], ""


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
        matched, matched_in = match_release(item["title"], item["description"])
        if not matched:
            continue
        signals.append(common.build_signal(
            source="prtimes",
            native_id=item["link"],
            title=item["title"],
            body=item["description"],
            url=item["link"],
            raw_category=matched[0],
            meta={
                "published_at": item["date"],
                "matched_keywords": matched,
                "matched_in": matched_in,
            },
        ))
    print(f"[prtimes] キーワードマッチ: {len(signals)}件")
    return signals


if __name__ == "__main__":
    common.run_collector("prtimes", collect)
