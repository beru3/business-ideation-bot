"""
リアルタイム信号収集スクリプト

全8ソースから検索クエリを生成し、bot/signals_raw.json に統合出力する。

Usage:
  python bot/collect.py              # 全ソース全クエリ
  python bot/collect.py --daily      # 日次モード (15-20クエリに絞る)
  python bot/collect.py twitter      # 特定ソースのみ
  python bot/collect.py --list       # ソース一覧
"""
import importlib
import json
import os
import sys
from datetime import datetime, timezone, timedelta

SIGNALS_DIR = os.path.join(os.path.dirname(__file__), "signals")
OUTPUT_FILE = "bot/signals_raw.json"

# collect.py がどこから実行されても bot.signals を import できるようにする
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

COLLECTORS = [
    "twitter",
    "google_trends",
    "product_hunt",
    "app_reviews",
    "reddit",
    "job_postings",
    "regulation",
    "jobtag",
]


def load_collector(name):
    """コレクターモジュールを読み込み、検索クエリとソース名を返す"""
    mod = importlib.import_module(f"bot.signals.{name}")
    return {
        "name": name,
        "source": mod.SOURCE,
        "queries": mod.SEARCH_QUERIES,
    }


DAILY_QUERY_BUDGET = 18  # 日次モードの最大クエリ数


def _select_daily_queries(all_queries):
    """日次モード: カテゴリローテーションで15-20クエリに絞る。

    曜日ベースでコレクターをローテーションし、
    jobtag はペインカテゴリの重みで上位を優先する。
    """
    today = datetime.now(timezone(timedelta(hours=9)))  # JST
    day_of_week = today.weekday()  # 0=Mon ... 6=Sun

    # コレクターを2グループに分け、曜日で交互
    # Group A (偶数日): twitter, product_hunt, reddit, jobtag
    # Group B (奇数日): google_trends, app_reviews, job_postings, regulation
    group_a = {"twitter", "product_hunt", "reddit", "jobtag"}
    group_b = {"google_trends", "app_reviews", "job_postings", "regulation"}
    active_group = group_a if day_of_week % 2 == 0 else group_b

    # jobtag は常に含める（ペインカテゴリが最重要）
    active_group.add("jobtag")

    # アクティブグループのクエリのみ抽出
    filtered = [q for q in all_queries if q["collector"] in active_group]

    if len(filtered) <= DAILY_QUERY_BUDGET:
        return filtered

    # 予算オーバーの場合、jobtag を優先し残りを均等配分
    jobtag_queries = [q for q in filtered if q["collector"] == "jobtag"]
    other_queries = [q for q in filtered if q["collector"] != "jobtag"]

    # jobtag: 上位カテゴリから最大12クエリ（重みでソート済みなので先頭優先）
    jobtag_budget = min(len(jobtag_queries), 12)
    selected = jobtag_queries[:jobtag_budget]

    # 残り予算を他コレクターに均等配分
    remaining_budget = DAILY_QUERY_BUDGET - len(selected)
    collectors = list({q["collector"] for q in other_queries})
    per_collector = max(1, remaining_budget // len(collectors)) if collectors else 0

    for collector in collectors:
        cq = [q for q in other_queries if q["collector"] == collector]
        selected.extend(cq[:per_collector])

    return selected[:DAILY_QUERY_BUDGET]


def collect_all(targets=None, daily_mode=False):
    """指定されたコレクター（またはすべて）のクエリを統合出力する"""
    if targets is None:
        targets = COLLECTORS

    all_queries = []
    for name in targets:
        try:
            collector = load_collector(name)
            for query in collector["queries"]:
                all_queries.append({
                    "source": collector["source"],
                    "collector": name,
                    "query": query,
                })
            print(f"  {name}: {len(collector['queries'])} queries")
        except Exception as e:
            print(f"  {name}: ERROR - {e}")

    if daily_mode:
        before = len(all_queries)
        all_queries = _select_daily_queries(all_queries)
        print(f"\n  Daily mode: {before} → {len(all_queries)} queries")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "daily" if daily_mode else "full",
        "total_queries": len(all_queries),
        "collectors": targets,
        "queries": all_queries,
        "signals": [],
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {OUTPUT_FILE}")
    print(f"  Total queries: {len(all_queries)}")


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("Available collectors:")
        for name in COLLECTORS:
            c = load_collector(name)
            print(f"  {name} ({c['source']}): {len(c['queries'])} queries")
        sys.exit(0)

    daily = "--daily" in sys.argv
    targets = [a for a in sys.argv[1:] if not a.startswith("-")]
    if targets:
        invalid = [t for t in targets if t not in COLLECTORS]
        if invalid:
            print(f"Unknown collector(s): {invalid}")
            print(f"Available: {COLLECTORS}")
            sys.exit(1)
    else:
        targets = None

    print("Collecting signal queries...")
    collect_all(targets, daily_mode=daily)
