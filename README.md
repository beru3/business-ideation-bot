# business-ideation-bot

リアルタイムの市場信号から事業仮説を生成し、ナレッジで補強・市場検証を経てテストマーケに進めるパイプライン。

外部API（Exa, DeepSeek等）は使わず、Claude Code のスキルで完結する（ランニングコスト ¥0）。

## パイプライン v2

```
/weekly-pipeline （Claude Code スキル、週次実行）
        │
信号収集（WebSearch x 8ソース）
  X/Twitter, Google Trends, Product Hunt,
  アプリレビュー, Reddit, 求人, 法改正, 学習由来
        │
        ▼
    トリアージ → 深掘りリサーチ
        │
        ▼
    仮説生成 + ナレッジ照合（マーケ侍496件 / Supabase）
        │
        ▼
    市場検証（競合調査 + 需要裏取り）
    スコアリング: 4軸10点（7+ pass / 4-6 hold / 3以下 reject）
        │
        ▼
    Issue投稿 [シグナル発] → [検証済] / [保留] / クローズ
        │
        ▼
    /test-marketing （pass仮説のLP・X投稿・note記事生成）
```

## 使い方

```
/weekly-pipeline    # 信号収集→仮説生成→市場検証→Issue投稿まで一気通貫
/test-marketing     # 検証済仮説のテストマーケ素材生成
```

### 補助スクリプト

```bash
python bot/validate.py fetch   # ナレッジ496件を bot/validate_input.json に取得
python bot/validate.py post    # bot/validate_output.json の検証結果をIssueに反映
```

## ディレクトリ構成

| パス | 内容 |
|---|---|
| `bot/validate.py` | ナレッジ取得 + Issue反映スクリプト |
| `bot/VALIDATE_PROMPT.md` | 市場検証の評価基準 |
| `bot/briefs/` | pass仮説のマーケブリーフ |
| `bot/articles/` `bot/x-posts/` `bot/knowledge_context/` | テストマーケ素材 |
| `x-bot/` | X / note の自動運用Bot（GitHub Actions） |
| `site/lp/` | LP（GitHub Pages 配信） |
| `supabase/` | ナレッジDBマイグレーション |

## ラベル体系

| ラベル | 意味 |
|--------|------|
| `シグナル発` | リアルタイム信号から生成された仮説 |
| `検証済` | 競合調査・需要裏取りを通過した仮説 |
| `保留` | スコア4-6で再検証待ちの仮説 |

## セットアップ

```bash
pip install supabase
export SUPABASE_SERVICE_ROLE_KEY=...   # validate.py fetch に必要
```

## 廃止済み

v1パイプライン（GitHub Actions + Exa API + DeepSeek API）は 2026-06 に削除済み。
履歴は git log を参照（`bot/collect.py`, `bot/research.mjs` 等）。
