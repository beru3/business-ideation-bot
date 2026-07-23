"""信号収集bot 共通基盤 (Phase 2)。

- signals書き込み: bot/data/signals/{source}-{YYYY-MM}.jsonl (追記専用)
- 重複排除: 当月+前月のjsonl既存idと照合してから書き込む
- 死活記録: 成功時に _health.json へ {source: {last_success_at, rows_collected}} をマージ

スキーマ (docs/renovation-plan-2026-07.md 準拠):
  {"id": sha1(source+native_id), "source": ..., "collected_at": ISO8601,
   "native_id": ..., "raw_category": ..., "title": ..., "body": ..., "url": ..., "meta": {}}
"""
from __future__ import annotations

import hashlib
import json
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

BOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BOT_DIR / "data"
SIGNALS_DIR = DATA_DIR / "signals"

VALID_SOURCES = ("gplay", "youtube", "prtimes", "laws")


def make_id(source: str, native_id: str) -> str:
    """信号ID = sha1(source + native_id)。"""
    return hashlib.sha1((source + native_id).encode("utf-8")).hexdigest()


def build_signal(
    source: str,
    native_id: str,
    title: str,
    body: str,
    url: str,
    raw_category: str = "",
    meta: dict[str, Any] | None = None,
    collected_at: str | None = None,
) -> dict[str, Any]:
    """共通スキーマに準拠した信号dictを新規生成する。"""
    if source not in VALID_SOURCES:
        raise ValueError(f"unknown source: {source}")
    if not native_id:
        raise ValueError("native_id must be non-empty")
    return {
        "id": make_id(source, native_id),
        "source": source,
        "collected_at": collected_at or datetime.now(timezone.utc).isoformat(),
        "native_id": native_id,
        "raw_category": raw_category,
        "title": title,
        "body": body,
        "url": url,
        "meta": dict(meta) if meta else {},
    }


def month_keys(today: date | None = None) -> tuple[str, str]:
    """(当月, 前月) の "YYYY-MM" キーを返す。"""
    today = today or date.today()
    current = f"{today.year:04d}-{today.month:02d}"
    prev_year, prev_month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return current, f"{prev_year:04d}-{prev_month:02d}"


def load_existing_ids(source: str, signals_dir: Path | None = None) -> frozenset[str]:
    """当月+前月のjsonlから既存の信号idを読み込む。"""
    signals_dir = signals_dir or SIGNALS_DIR
    ids: set[str] = set()
    for month in month_keys():
        path = signals_dir / f"{source}-{month}.jsonl"
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(f"[{source}] WARN: {path.name}:{line_no} 不正なJSON行を無視: {exc}", file=sys.stderr)
                    continue
                if isinstance(row, dict) and row.get("id"):
                    ids.add(row["id"])
    return frozenset(ids)


def append_signals(source: str, signals: list[dict[str, Any]], signals_dir: Path | None = None) -> int:
    """重複を除いた新規信号を当月jsonlに追記し、書き込み件数を返す。"""
    signals_dir = signals_dir or SIGNALS_DIR
    signals_dir.mkdir(parents=True, exist_ok=True)

    existing = set(load_existing_ids(source, signals_dir))
    current_month, _ = month_keys()
    path = signals_dir / f"{source}-{current_month}.jsonl"

    written = 0
    with open(path, "a", encoding="utf-8") as f:
        for sig in signals:
            sig_id = sig.get("id")
            if not sig_id or sig_id in existing:
                continue
            f.write(json.dumps(sig, ensure_ascii=False) + "\n")
            existing.add(sig_id)
            written += 1
    return written


def record_health(source: str, rows_collected: int, signals_dir: Path | None = None) -> None:
    """_health.json に成功記録をマージ書き込みする。"""
    signals_dir = signals_dir or SIGNALS_DIR
    signals_dir.mkdir(parents=True, exist_ok=True)
    path = signals_dir / "_health.json"

    health: dict[str, Any] = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                health = loaded
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[{source}] WARN: _health.json 読み込み失敗、再生成します: {exc}", file=sys.stderr)

    updated = {
        **health,
        source: {
            "last_success_at": datetime.now(timezone.utc).isoformat(),
            "rows_collected": rows_collected,
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_monitored(filename: str, list_key: str) -> list[dict[str, Any]]:
    """monitored-*.json を読み込み、list_key 配下のエントリを返す。

    ファイル構造: {"_comment": "...", "<list_key>": [...]}
    """
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"{path} が見つかりません")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get(list_key), list):
        raise ValueError(f"{filename} の構造が不正です (キー '{list_key}' の配列が必要)")
    entries = data[list_key]
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{filename}: エントリはオブジェクトである必要があります: {entry!r}")
    return entries


def run_collector(source: str, collect: Callable[[], list[dict[str, Any]]]) -> None:
    """コレクタ実行の共通ラッパ。

    成功: 信号追記 + _health.json 更新。
    失敗: stderrへコンテキスト付きログを出し exit code 1 (他ソースは巻き込まない)。
    """
    try:
        signals = collect()
        written = append_signals(source, signals)
        record_health(source, written)
        print(f"[{source}] OK: collected={len(signals)} written={written} (dedup済み)")
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[{source}] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
