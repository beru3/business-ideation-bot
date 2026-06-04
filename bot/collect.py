"""
リアルタイム信号収集スクリプト

全7ソースからExa web searchで信号を収集し、
bot/signals_raw.json に統合出力する。

Usage (Claude Code内で実行):
  python bot/collect.py              # 全ソース収集
  python bot/collect.py twitter      # 特定ソースのみ
  python bot/collect.py --list       # ソース一覧
"""
import importlib
import json
import os
import sys
from datetime import datetime, timezone

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


def collect_all(targets=None):
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

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_queries": len(all_queries),
        "collectors": targets,
        "queries": all_queries,
        "signals": [],
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {OUTPUT_FILE}")
    print(f"  Total queries: {len(all_queries)}")
    print(f"\nNext: Claude Code で各クエリをExa web searchで実行し、")
    print(f"  結果を {OUTPUT_FILE} の signals に追加してください。")
    print(f"  完了後、`python bot/ideation.py post-signals` で起票。")


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("Available collectors:")
        for name in COLLECTORS:
            c = load_collector(name)
            print(f"  {name} ({c['source']}): {len(c['queries'])} queries")
        sys.exit(0)

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
    collect_all(targets)
