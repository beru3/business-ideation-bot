"""
Reddit/掲示板の悩み検索

海外の起業家・中小企業オーナーのリアルな悩みを収集する。
日本の掲示板（5ch、知恵袋等）も対象。
"""

SEARCH_QUERIES = [
    # Reddit
    "site:reddit.com r/smallbusiness struggle OR problem OR frustrating 2026",
    "site:reddit.com r/entrepreneur pain point OR biggest challenge 2026",
    "site:reddit.com r/SaaS looking for OR need a tool OR alternative",
    "site:reddit.com r/startups idea validation OR market gap",
    # 日本の掲示板・Q&A
    "site:detail.chiebukuro.yahoo.co.jp 経営 困っている OR 悩み",
    "中小企業 経営者 悩み 2026 掲示板 OR フォーラム",
]

SOURCE = "reddit"
