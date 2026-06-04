"""
Google Trends 急上昇キーワード検索

Exa web searchでGoogle Trendsの急上昇トレンドを収集する。
ビジネス・業務効率化関連のトレンドを重点的に探す。
"""

SEARCH_QUERIES = [
    # Google Trends直接
    "site:trends.google.co.jp 急上昇 ビジネス",
    # トレンド分析記事
    "Google Trends 2026 急上昇 SaaS OR ツール OR 業務効率",
    "トレンド 2026 中小企業 課題 新しい",
    # 技術トレンド
    "AI活用 2026 トレンド 中小企業 導入",
    "DX推進 2026 課題 最新",
]

SOURCE = "trends"
