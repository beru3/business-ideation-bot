#!/usr/bin/env python3
"""explored-map.json の読み書きヘルパー。

週次パイプライン Step 0 が使う:
  python bot/explored_map.py due     # recheck_date が今日以前のエントリを表示
  python bot/explored_map.py avoid   # avoid エントリの category_path 一覧を表示
"""
import json
import sys
from datetime import date
from pathlib import Path

MAP_PATH = Path(__file__).parent / "data" / "explored-map.json"


def load() -> dict:
    if not MAP_PATH.exists():
        raise FileNotFoundError(f"explored-map not found: {MAP_PATH}")
    with open(MAP_PATH, encoding="utf-8") as f:
        data = json.load(f)
    if "entries" not in data:
        raise ValueError("explored-map.json: 'entries' キーがありません")
    return data


def due_rechecks(today: date | None = None) -> list[dict]:
    """recheck_date が today 以前の recheck エントリを返す。"""
    today = today or date.today()
    due = []
    for e in load()["entries"]:
        if e.get("verdict") != "recheck":
            continue
        rd = e.get("recheck_date")
        if rd and date.fromisoformat(rd) <= today:
            due.append(e)
    return due


def avoid_paths() -> list[list[str]]:
    return [e["category_path"] for e in load()["entries"] if e.get("verdict") == "avoid"]


def add_entry(entry: dict) -> None:
    """エントリを追記保存する。必須キーを検証してから書き込む。"""
    required = {"category_path", "keywords", "verdict", "verdict_date", "evidence"}
    missing = required - entry.keys()
    if missing:
        raise ValueError(f"必須キー不足: {missing}")
    if entry["verdict"] not in ("avoid", "recheck", "open"):
        raise ValueError(f"不正なverdict: {entry['verdict']}")
    data = load()
    data["entries"].append(entry)
    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "due"
    if cmd == "due":
        due = due_rechecks()
        if not due:
            print("期限到来のrecheckなし")
        for e in due:
            print(f"[{e.get('recheck_date')}] {' > '.join(e['category_path'])} (Issue #{e.get('related_issue', '-')}): {e['evidence']}")
    elif cmd == "avoid":
        for p in avoid_paths():
            print(" > ".join(p))
    else:
        print(f"不明なコマンド: {cmd}（due | avoid）", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
