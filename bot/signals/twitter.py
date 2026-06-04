"""
X/Twitter 不満・困りごと検索

Exa web searchで X/Twitter上の不満・痛みを収集する。
検索クエリ例: 「〇〇 困る」「〇〇 めんどくさい」「〇〇 手作業」「〇〇 非効率」
"""

SEARCH_QUERIES = [
    # 業務系の不満
    "site:x.com OR site:twitter.com 業務 めんどくさい 手作業",
    "site:x.com OR site:twitter.com 経営 困る 中小企業",
    "site:x.com OR site:twitter.com 事務作業 非効率 自動化したい",
    "site:x.com OR site:twitter.com 請求書 面倒 手入力",
    "site:x.com OR site:twitter.com 集客 うまくいかない 個人事業",
    # SaaS/ツール系の不満
    "site:x.com OR site:twitter.com SaaS 高い 代替",
    "site:x.com OR site:twitter.com ツール 使いにくい 乗り換え",
    # 業種特化の不満
    "site:x.com OR site:twitter.com 飲食店 人手不足 オペレーション",
    "site:x.com OR site:twitter.com 美容室 予約管理 大変",
    "site:x.com OR site:twitter.com 士業 書類作成 時間かかる",
]

SOURCE = "twitter"
