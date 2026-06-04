# Knowledge Base

## 概要

マーケティング侍の378件の記事コンテンツ（YouTube文字起こし + PDF/資料テキスト）から、構造化されたビジネスインサイトを抽出し、Supabaseに格納した知識ベース。

**現在の役割**: パイプラインの入り口ではなく、市場検証ステップでの**補強材料**として使用。

## アーキテクチャ

```
┌─────────────────────────────────────────────────────┐
│  Data Sources (378 articles)                        │
│  ├─ YouTube transcripts (373件)                     │
│  ├─ Evernote PDFs (306件)                           │
│  ├─ Direct PDFs (51件)                              │
│  ├─ Google Sheets (2件)                             │
│  └─ Notion pages (2件)                              │
└──────────────────┬──────────────────────────────────┘
                   │ Claude Code (構造化抽出)
                   ▼
┌─────────────────────────────────────────────────────┐
│  Supabase (business-ideation)                       │
│  ├─ knowledge_articles (378 rows)                   │
│  ├─ knowledge_insights (496 rows)                   │
│  ├─ hypotheses                                      │
│  └─ test_campaigns                                  │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
        市場検証ステップ (validate) で
        仮説の裏付け・補強材料として参照
```

## Supabase

- **Project**: business-ideation
- **Region**: ap-northeast-1
- **Ref**: fkyapyaiqigqdfdyjyop

## テーブル設計

### knowledge_articles
記事メタデータ。378件。

| Column | Type | Description |
|--------|------|-------------|
| idx | INT PK | 記事番号 |
| title | TEXT | 記事タイトル |
| youtube_url | TEXT | YouTube URL |
| video_id | TEXT | YouTube video ID |
| download_type | TEXT | evernote_pdf / direct_pdf / google_sheets / notion |
| download_href | TEXT | ダウンロードリンク |
| transcript_chars | INT | 文字起こし文字数 |
| download_chars | INT | ダウンロードテキスト文字数 |

### knowledge_insights
構造化インサイト。Claude Codeで抽出。496件。

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| article_idx | INT FK | 記事番号 |
| target_who | TEXT | 具体的ペルソナ |
| target_industry | TEXT | 業種カテゴリ |
| pain_point | TEXT | 具体的課題 |
| existing_solution | TEXT | 既存解法 |
| automation_opportunity | TEXT | AI/自動化の余地 |
| market_hint | TEXT | 市場規模ヒント |
| tags | TEXT[] | タグ (3-5個) |
| confidence | REAL | 確信度 (0.0-1.0) |
| embedding | vector(1536) | 将来のセマンティック検索用 |

### hypotheses / test_campaigns
スキーマは `supabase/migrations/20260603_init.sql` 参照。

## 業種分布

| 業種 | 件数 |
|------|------|
| 全業種 | 278 |
| 小売 | 59 |
| 教育 | 23 |
| 飲食 | 18 |
| IT | 11 |
| 美容 | 11 |
| 製造 | 7 |
| 士業 | 6 |
| その他 | 2 |
| 医療 | 2 |
| 不動産 | 2 |
| 建設 | 1 |

## データ収集プロセス

1. **記事一覧取得**: Playwrightでマーケティング侍サイトをスクレイピング
2. **YouTube文字起こし**: youtube-transcript-api + Playwrightフォールバック
3. **PDF抽出**: Evernote PDF (PyMuPDF) + 直接PDF
4. **Google Sheets**: CSV export via Playwright
5. **Notion**: DOM text extraction via Playwright
6. **統合**: `tmp/articles_complete.json` (377/378件にコンテンツあり)
7. **インサイト抽出**: Claude Codeエージェント並列処理 → Supabase投入
