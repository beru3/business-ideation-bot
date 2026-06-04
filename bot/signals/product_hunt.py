"""
Product Hunt 新着プロダクト検索

海外で出たばかりのSaaS/ツールで日本未上陸のものを探す。
タイムマシン経営（海外→日本の時間差）の機会を発見する。
"""

SEARCH_QUERIES = [
    "site:producthunt.com launched today SaaS small business",
    "site:producthunt.com launched this week AI automation",
    "site:producthunt.com launched this week productivity tool",
    "site:producthunt.com launched this week invoice OR accounting OR scheduling",
    "site:producthunt.com launched this week marketing automation",
    # 日本未上陸の確認
    "Product Hunt 話題 日本語対応 まだ OR 未対応",
]

SOURCE = "producthunt"
