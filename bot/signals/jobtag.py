"""
厚労省 job tag（職業情報提供サイト）データからペインカテゴリ別検索クエリを生成

520職業の数値データを分析し、「ソフトウェアで解決可能だが、まだ自動化されていない」
業務活動を特定。職業名ではなく、ペインカテゴリ（活動 × 不満キーワード）で検索する。

jobtag の役割: 検索キーワードの生成ではなく、
「どのペインカテゴリを優先的に検索するか」の重み付けエンジン。

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

# 業務活動カラム (Col 243-283): 各職業のスコア (1.0-5.0)
ACTIVITY_START = 243
ACTIVITY_END = 284

# ペインカテゴリ定義
# key: カテゴリID
# activity_cols: jobtag の活動カラムインデックス（重み計算に使用）
# queries: 実際に人がSNSで書く言葉ベースの検索クエリ
PAIN_CATEGORIES = {
    "document_processing": {
        "label": "書類・申請処理",
        "activity_cols": [249, 266],  # 法律や規定を適用, 情報の文書化と記録
        "queries": [
            'site:x.com "申請書" "手作業" OR "面倒" OR "非効率" OR "時間かかる"',
            'site:x.com "書類作成" "毎回" OR "同じこと" OR "コピペ" OR "テンプレ"',
            '"申請業務" "効率化" OR "自動化" OR "ツール" OR "システム化"',
        ],
    },
    "data_entry_excel": {
        "label": "データ入力・エクセル地獄",
        "activity_cols": [250, 262],  # 情報やデータを処理, コンピュータ作業
        "queries": [
            'site:x.com "エクセル" "手作業" OR "コピペ" OR "地獄" OR "限界"',
            'site:x.com "データ入力" "面倒" OR "終わらない" OR "ミス" OR "手打ち"',
            '"手入力" "自動化したい" OR "なんとかしたい" OR "いい加減"',
        ],
    },
    "schedule_coordination": {
        "label": "スケジュール・予約調整",
        "activity_cols": [256, 257],  # スケジュール作成, 仕事の整理計画
        "queries": [
            'site:x.com "スケジュール調整" "面倒" OR "大変" OR "手間" OR "メール"',
            'site:x.com "予約管理" "ダブルブッキング" OR "電話" OR "手動" OR "紙"',
            '"日程調整" "効率化" OR "自動化" OR "ツール"',
        ],
    },
    "compliance_law_update": {
        "label": "法令対応・コンプライアンス",
        "activity_cols": [249, 254],  # 法律や規定を適用, 知識の更新
        "queries": [
            'site:x.com "法改正" "対応" "大変" OR "追いつかない" OR "把握"',
            'site:x.com "コンプライアンス" "チェック" OR "確認作業" OR "手動"',
            '"法令チェック" OR "規制対応" "効率化" OR "自動化"',
        ],
    },
    "reporting_aggregation": {
        "label": "レポート・集計作業",
        "activity_cols": [251, 266],  # 情報やデータを分析, 文書化と記録
        "queries": [
            'site:x.com "月次報告" OR "週報" "面倒" OR "毎回" OR "同じ" OR "作成"',
            'site:x.com "データ集計" "手動" OR "時間" OR "エクセル" OR "毎月"',
            '"レポート作成" "自動化" OR "効率化" OR "テンプレート"',
        ],
    },
    "progress_status_tracking": {
        "label": "進捗・ステータス管理",
        "activity_cols": [244, 257],  # 継続的に状況を把握, 仕事の整理
        "queries": [
            'site:x.com "進捗管理" "エクセル" OR "限界" OR "属人" OR "共有"',
            'site:x.com "ステータス確認" OR "状況確認" "手間" OR "いちいち" OR "聞く"',
            '"案件管理" "一元化" OR "見える化" OR "ツール"',
        ],
    },
    "information_gathering": {
        "label": "情報収集・調べもの",
        "activity_cols": [243, 245],  # 情報を取得, 情報の整理と検知
        "queries": [
            'site:x.com "調べもの" OR "情報収集" "時間かかる" OR "終わらない" OR "膨大"',
            'site:x.com "リサーチ" "手作業" OR "毎回" OR "同じ調査"',
            '"情報収集" "自動化" OR "効率化" OR "まとめ"',
        ],
    },
    "quality_check": {
        "label": "チェック・検品・ダブルチェック",
        "activity_cols": [248, 246],  # クオリティを判断, 設備等を検査
        "queries": [
            'site:x.com "ダブルチェック" OR "目視確認" "時間" OR "面倒" OR "人手"',
            'site:x.com "チェック作業" "自動化" OR "ミス" OR "見落とし"',
            '"検品" OR "品質チェック" "効率化" OR "省力化" OR "AI"',
        ],
    },
    "filing_organization": {
        "label": "ファイル・書類整理",
        "activity_cols": [245, 266],  # 情報の整理と検知, 文書化と記録
        "queries": [
            'site:x.com "書類整理" OR "ファイル管理" "カオス" OR "探す" OR "どこ"',
            'site:x.com "紙" "電子化" OR "ペーパーレス" OR "まだ" OR "いつまで"',
            '"文書管理" "効率化" OR "システム化" OR "クラウド"',
        ],
    },
    "communication_overhead": {
        "label": "社内外コミュニケーション負荷",
        "activity_cols": [268, 269],  # 内部コミュニケーション, 外部コミュニケーション
        "queries": [
            'site:x.com "メール" "返信" "終わらない" OR "多すぎ" OR "cc地獄"',
            'site:x.com "議事録" "作成" "面倒" OR "毎回" OR "誰が書く"',
            '"社内連絡" OR "報連相" "効率化" OR "自動化" OR "ツール"',
        ],
    },
    "numerical_calculation": {
        "label": "数値計算・見積作成",
        "activity_cols": [247, 250],  # 数値の算出・推計, 情報やデータを処理
        "queries": [
            'site:x.com "見積書" "作成" "面倒" OR "手作業" OR "時間" OR "毎回"',
            'site:x.com "請求書" "手動" OR "エクセル" OR "ミス" OR "発行"',
            '"見積作成" OR "請求処理" "自動化" OR "効率化" OR "システム"',
        ],
    },
}


def _get_float(row, idx):
    if idx < len(row) and row[idx]:
        try:
            return float(row[idx])
        except ValueError:
            return None
    return None


def _calculate_category_weights():
    """jobtag データからペインカテゴリごとの重みを計算する。

    自動化余地の高い職業群において、各活動カラムのスコア合計を集計し、
    ペインカテゴリの優先度を決定する。
    """
    if not os.path.exists(JOBTAG_CSV):
        return {}

    with open(JOBTAG_CSV, "r", encoding="cp932") as f:
        rows = list(csv.reader(f))

    skip_keywords = [
        "官", "警察", "自衛", "消防", "刑務", "検察", "裁判",
        "入国審査", "科学捜査", "検疫", "麻薬取締",
    ]

    # 対象職業を抽出
    target_rows = []
    for row in rows[18:]:
        if len(row) < ACTIVITY_END or not row[COL_NAME]:
            continue
        name = row[COL_NAME]
        office = _get_float(row, COL_OFFICE)
        data_proc = _get_float(row, COL_DATA)
        rep = _get_float(row, COL_REP)
        auto = _get_float(row, COL_AUTO)
        if not (office and data_proc and (office >= 2.5 or data_proc >= 3.0)):
            continue
        if not (rep and auto):
            continue
        if any(kw in name for kw in skip_keywords):
            continue
        target_rows.append(row)

    if not target_rows:
        return {}

    # 各ペインカテゴリの重みを計算
    weights = {}
    for cat_id, cat in PAIN_CATEGORIES.items():
        total_score = 0.0
        for row in target_rows:
            for col in cat["activity_cols"]:
                val = _get_float(row, col)
                if val:
                    total_score += val
        # 平均スコア（カラム数 × 職業数で正規化）
        avg = total_score / (len(cat["activity_cols"]) * len(target_rows))
        weights[cat_id] = avg

    return weights


def _get_representative_occupations():
    """各ペインカテゴリの代表的な職業名を取得する（コンテキスト付加用）。"""
    if not os.path.exists(JOBTAG_CSV):
        return {}

    with open(JOBTAG_CSV, "r", encoding="cp932") as f:
        rows = list(csv.reader(f))

    skip_keywords = [
        "官", "警察", "自衛", "消防", "刑務", "検察", "裁判",
        "入国審査", "科学捜査", "検疫", "麻薬取締",
    ]

    reps = {cat_id: [] for cat_id in PAIN_CATEGORIES}

    for row in rows[18:]:
        if len(row) < ACTIVITY_END or not row[COL_NAME]:
            continue
        name = row[COL_NAME]
        office = _get_float(row, COL_OFFICE)
        data_proc = _get_float(row, COL_DATA)
        rep = _get_float(row, COL_REP)
        auto = _get_float(row, COL_AUTO)
        if not (office and data_proc and (office >= 2.5 or data_proc >= 3.0)):
            continue
        if not (rep and auto):
            continue
        if any(kw in name for kw in skip_keywords):
            continue

        for cat_id, cat in PAIN_CATEGORIES.items():
            cat_score = sum(
                _get_float(row, c) or 0 for c in cat["activity_cols"]
            ) / len(cat["activity_cols"])
            if cat_score >= 3.5:
                reps[cat_id].append((name, cat_score))

    # 各カテゴリ上位3職業を返す
    return {
        cat_id: [name for name, _ in sorted(items, key=lambda x: -x[1])[:3]]
        for cat_id, items in reps.items()
    }


def generate_queries():
    """ペインカテゴリの重みに基づき、優先度の高い順に検索クエリを生成する。"""
    weights = _calculate_category_weights()
    if not weights:
        # CSV がない場合は全カテゴリの全クエリを返す
        queries = []
        for cat in PAIN_CATEGORIES.values():
            queries.extend(cat["queries"])
        return queries

    # 重みでソートし、上位カテゴリから優先的にクエリを生成
    sorted_cats = sorted(weights.items(), key=lambda x: -x[1])

    queries = []
    for cat_id, weight in sorted_cats:
        cat = PAIN_CATEGORIES[cat_id]
        for q in cat["queries"]:
            queries.append(q)

    return queries


SEARCH_QUERIES = generate_queries()
