"""
厚労省 job tag（職業情報提供サイト）データから検索クエリを生成

520職業の数値データ（反復作業スコア、自動化スコア、事務処理スコア等）を分析し、
「ソフトウェアで解決可能だが、まだ自動化されていない職業×タスク」を特定。
その職業名でリアルタイムの不満・痛みを検索する。

データ元: https://shigoto.mhlw.go.jp/User/download
"""
import csv
import os

SOURCE = "jobtag"
JOBTAG_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "data", "jobtag_numeric.csv")

# 使用するカラムのインデックス (0-based, Row 17がヘッダー)
COL_NAME = 3        # 職業名
COL_REP = 175       # 同一作業の反復
COL_AUTO = 200      # 機械やコンピュータによる仕事の自動化
COL_OFFICE = 100    # 事務処理
COL_DATA = 250      # 情報やデータを処理する
COL_MGMT = 281      # 管理業務を遂行する
COL_TIME = 56       # 時間管理

# タスク関連カラム: Col 329=リード文, Col 330=タスク1名, Col 331=実施率, Col 332=重要度, ...
TASK_LEAD = 329      # リード文
TASK_START = 330     # タスク1（名前）
TASK_STRIDE = 3      # タスク名, 実施率, 重要度 のセット
TASK_COUNT = 37


def _get_float(row, idx):
    if idx < len(row) and row[idx]:
        try:
            return float(row[idx])
        except ValueError:
            return None
    return None


def _load_occupations():
    """CSVから職業データを読み込み、自動化余地の高い順にソートして返す"""
    if not os.path.exists(JOBTAG_CSV):
        return []

    with open(JOBTAG_CSV, "r", encoding="cp932") as f:
        reader = csv.reader(f)
        rows = list(reader)

    occupations = []
    for row in rows[18:]:  # データ行は19行目以降
        if len(row) < 200 or not row[COL_NAME]:
            continue

        name = row[COL_NAME]
        rep = _get_float(row, COL_REP)
        auto = _get_float(row, COL_AUTO)
        office = _get_float(row, COL_OFFICE)
        data_proc = _get_float(row, COL_DATA)
        mgmt = _get_float(row, COL_MGMT)

        # ソフトウェアで解ける職業 = 事務処理 or データ処理が高い
        if not (office and data_proc and (office >= 2.5 or data_proc >= 3.0)):
            continue
        if not (rep and auto):
            continue

        # 公務員・法執行系は販売先が限られるため除外
        skip_keywords = [
            "官", "警察", "自衛", "消防", "刑務", "検察", "裁判",
            "入国審査", "科学捜査", "検疫", "麻薬取締",
        ]
        if any(kw in name for kw in skip_keywords):
            continue

        # 自動化余地スコア = 反復 + 事務 + データ処理 - 自動化 × 2
        opportunity = rep + office + data_proc - auto * 2

        # 上位タスクを抽出（実施率が高いもの）
        # 実施率は0.0-1.0スケール
        tasks = []
        for t in range(TASK_COUNT):
            task_idx = TASK_START + t * TASK_STRIDE
            rate_idx = task_idx + 1
            if task_idx < len(row) and row[task_idx]:
                task_name = row[task_idx]
                rate = _get_float(row, rate_idx)
                if task_name and rate and rate >= 0.7:
                    tasks.append(task_name)

        occupations.append({
            "name": name,
            "opportunity": opportunity,
            "repetition": rep,
            "automation": auto,
            "office": office,
            "data_processing": data_proc,
            "management": mgmt,
            "top_tasks": tasks[:5],
        })

    occupations.sort(key=lambda x: x["opportunity"], reverse=True)
    return occupations


def generate_queries(top_n=30):
    """自動化余地の高い職業トップNから検索クエリを生成"""
    occupations = _load_occupations()
    if not occupations:
        return []

    queries = []
    for occ in occupations[:top_n]:
        name = occ["name"]
        # 職業名 × 不満系キーワードで検索
        queries.append(f'site:x.com OR site:twitter.com "{name}" 大変 OR 面倒 OR 非効率 OR 手作業')

        # タスクがあれば、タスク名でも検索
        if occ["top_tasks"]:
            task = occ["top_tasks"][0]
            queries.append(f'"{name}" "{task}" 効率化 OR 自動化 OR ツール')

    return queries


SEARCH_QUERIES = generate_queries()
