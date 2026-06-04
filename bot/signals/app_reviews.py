"""
アプリストア低評価レビュー検索

業務系アプリの低評価レビューから不満・改善余地を収集する。
既存ツールへの具体的な不満 = 新しい事業機会。
"""

SEARCH_QUERIES = [
    # App Store / Google Play の低評価
    "site:apps.apple.com OR site:play.google.com レビュー 使いにくい 業務",
    # レビューまとめサイト
    "ITreview 評判 不満 OR デメリット 業務効率化",
    "G2 review negative OR complaint small business software",
    "Capterra review cons OR disadvantages 日本",
    # 特定カテゴリ
    "会計ソフト レビュー 不満 OR 使いにくい OR 高い",
    "予約システム レビュー 不満 OR 機能不足",
    "CRM レビュー 中小企業 高い OR 複雑",
]

SOURCE = "appreviews"
