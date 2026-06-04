# business-ideation-bot

リアルタイムの市場信号から事業仮説を生成し、ナレッジで補強・市場検証を経てテストマーケに進めるパイプライン。

## パイプライン

```
信号収集（7ソース）
  X/Twitter, Google Trends, Product Hunt,
  アプリレビュー, Reddit, 求人, 法改正
        │
        ▼
    仮説生成 + 適合度採点（0-10）
        │
        ├─ 基準以下 → 却下
        │
        ▼
    Issue投稿 [シグナル発]
        │
        ▼
    市場検証（競合調査 + 需要裏取り + 収益モデル）
    + ナレッジ補強（マーケ侍496件と照合）
        │
        ├─ 基準以下 → 却下
        │
        ▼
    Issue投稿 [検証済]
        │
        ▼
    テストマーケ（未設計）
```

## 使い方

### 1. 信号収集

```bash
python bot/collect.py              # 全ソース（50クエリ）
python bot/collect.py twitter      # 特定ソースのみ
python bot/collect.py --list       # ソース一覧
```

GitHub Actions で毎日 JST 8:30 に自動実行。

### 2. 仮説生成・投稿

Claude Code で `bot/signals_raw.json` を読み、Exa web search で各クエリを実行。
結果を分析して仮説を `bot/signals_hypotheses.json` に保存。

```bash
python bot/ideation.py post-signals       # Issue投稿（ラベル: シグナル発）
python bot/ideation.py post-signals --dry # dry run
```

### 3. 市場検証

```bash
python bot/ideation.py validate           # 検証対象Issue + ナレッジ取得
python bot/ideation.py validate-post      # 検証済みIssue投稿（ラベル: 検証済）
python bot/ideation.py validate-post --dry
```

## ラベル体系

| ラベル | 意味 |
|--------|------|
| `シグナル発` | リアルタイム信号から生成された仮説 |
| `検証済` | 競合調査・需要裏取りを通過した仮説 |

## セットアップ

### GitHub Secrets

| Secret | 内容 |
|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key（任意） |

### ローカル実行

```bash
pip install supabase
python bot/collect.py
```

## アーカイブ済み

以下は旧パイプラインのコードで、現在は使用していません：
- `bot/research.mjs` — DeepSeek による失敗スタートアップ事例からの仮説生成（旧入り口①）
- `bot/ideation_analysis.json`, `bot/ideation_hypotheses.json` — 静的ナレッジからの独立生成（旧入り口②）
