# X自動運用システム設計書

## 概要

3商材（AIOチェッカー / AIコンプラチェック / ホウレイナビ）ごとに専用Xアカウントを運用。
投稿・エンゲージメント・計測・学習をすべて全自動で回す。

barbara-saas-marketing の x-bot をベースに、承認フローを撤廃し、
フィードバックループ（計測→学習→再生成）を追加。

## アーキテクチャ

```
┌─────────────────────────────────────────────────┐
│                 日次ループ（全自動）                │
│                                                   │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    │
│  │ generate │───▶│  post    │───▶│ metrics  │    │
│  │ 投稿文生成 │    │ X投稿    │    │ 計測     │    │
│  └──────────┘    └──────────┘    └──────────┘    │
│       ▲                               │          │
│       │          ┌──────────┐         │          │
│       │          │ engage   │         │          │
│       │          │ フォロー   │         │          │
│       │          │ いいね    │         │          │
│       │          │ リプライ   │         │          │
│       │          │ フォロバ   │         │          │
│       │          └──────────┘         │          │
│       │                               │          │
│       └───────── learn ◀──────────────┘          │
│                 学習・最適化                       │
└─────────────────────────────────────────────────┘
```

## アカウント構成（動的）

アカウントはハードコードしない。`bot/briefs/brief_*.json` のうち
検証済（pass）仮説から動的にアカウント設定を生成する。

**初期設定スクリプト `x-bot/setup-account.mjs`:**
```
node setup-account.mjs --brief bot/briefs/brief_26.json --handle aio_checker_jp
```
→ ブリーフの target_persona, channels, x_hooks, knowledge_backed_tactics を読み取り
→ `x-bot/accounts/{slug}/config.json` を自動生成（ペルソナ、キーワード、禁止事項等）

新しいpass仮説が `/weekly-pipeline` で生まれたら:
1. ブリーフが `bot/briefs/brief_{N}.json` に保存される
2. `setup-account.mjs` でアカウント設定を追加
3. Xアカウント作成 + APIキー取得（手動）
4. GitHub Secrets にキー追加（手動）
5. 以降は全自動で運用開始

**現時点のアカウント（3件）:**

| # | ブリーフ | アカウント名（案） | 自動生成元 |
|---|---------|------------------|-----------|
| 1 | brief_26.json | @aio_checker_jp | target_persona, x_hooks から |
| 2 | brief_new_ai_compliance.json | @ai_compla_jp | 同上 |
| 3 | brief_37.json | @hourei_navi | 同上 |

## コンポーネント一覧

### 1. generate.mjs — 投稿文自動生成

```
実行: GitHub Actions (毎朝 7:00 JST) × 3アカウント
入力: config.json + posted.json + metrics_history.json
出力: queue.json に追加
生成: DeepSeek API (deepseek-chat)
```

barbaraとの差分:
- **承認Issueなし** → queue.json に直接追加（承認不要）
- **メトリクス参照** → 過去の高imp投稿のパターンを生成プロンプトに反映
- **learn.mjs の出力を参照** → 効いた訴求パターン・避けるべき表現をプロンプトに注入
- 1アカウントあたり3本/日 × 3アカウント = 9本/日

生成プロンプト構造:
```
[システムプロンプト]
- ペルソナ定義（アカウントごと）
- 投稿ルール（140字以内、ハッシュタグ1-2個）
- 禁止事項
- LP URL（リンク付き投稿用）
- 過去の投稿（重複防止）
- 【自己プロンプト部分】learn.mjs が生成した「次回の生成指示」
  例: 「数字・統計型の投稿がimp高い。問いかけ型を増やせ」
  例: 「"知ってますか？"の書き出しはCTR低い。避けろ」

[ユーザープロンプト]
- 今日の日付
- 生成件数
- JSON形式で出力指示
```

### 2. post.mjs — X投稿

```
実行: GitHub Actions (12:00 / 16:00 / 19:00 JST) × 3アカウント
入力: queue.json
出力: posted.json に記録、X API で投稿
```

barbaraとの差分:
- **承認チェック不要** → queue.json の先頭から順に投稿
- **動的本数制御は維持** → キュー残数に応じて0-3本/日
- **URL分離リプライは維持** → リーチ低下防止

### 3. engage.mjs — エンゲージメント自動化

```
実行: GitHub Actions (10:00 / 14:00 / 20:00 JST) × 3アカウント
入力: config.json (キーワード、フィルター条件)
出力: engage_history.json
```

barbaraからの拡張:
- **フォローバック** — 自分をフォローしたユーザーを自動フォロー返し
- **フォロー解除** — 14日以上フォローバックがないユーザーを自動解除
- **いいね** — キーワード検索でエンゲージメント高のツイートに自動いいね
- **リプライ** — 関連ツイートにDeepSeekで返信生成→自動投稿
- **自動リプライ** — 自分の投稿への返信に自動で返す
- **引用リツイート** — 高エンゲージメントの関連ツイートを引用RT+コメント

日次上限:
| 操作 | 上限/日/アカウント |
|------|-------------------|
| フォロー | 10 |
| フォロー解除 | 5 |
| いいね | 15 |
| リプライ（他者へ） | 5 |
| 自動リプライ（自分宛て） | 10 |
| 引用RT | 2 |

### 4. metrics.mjs — 計測

```
実行: GitHub Actions (毎朝 6:00 JST) × 3アカウント
入力: posted.json (ツイートID一覧)
出力: metrics_history.json, GitHub Issue にレポート
```

barbaraと同等 + フォロワー数の推移記録を追加。

### 5. learn.mjs — フィードバックループ（新規）

```
実行: GitHub Actions (毎週月曜 6:30 JST)
入力: metrics_history.json (3アカウント分)
出力: learnings.json (次回のgenerate.mjsが参照)
```

**これが「自分でプロンプトを与えるシステム」の核。**

処理:
1. 過去7日間の全投稿のメトリクスを集計
2. imp/♥/RT/返信 の上位・下位を分析
3. DeepSeek に「なぜこの投稿は反応が良かった/悪かったか」を分析させる
4. 次回の生成プロンプトに注入する「指示」を生成:
   - 効いた訴求パターン（例: 「数字で始まる投稿はimp 2倍」）
   - 避けるべきパターン（例: 「質問形式の投稿はエンゲージメント低い」）
   - 最適な投稿時間帯
   - 効果の高いハッシュタグ
5. learnings.json に書き出す
6. pipeline-learnings.md のマーケ学習セクションにも反映

```json
// learnings.json の例
{
  "updated_at": "2026-06-16",
  "accounts": {
    "aio_checker_jp": {
      "top_patterns": ["数字で始まる投稿", "「知ってた？」系"],
      "avoid_patterns": ["長文スレッド", "ハッシュタグ3個以上"],
      "best_hashtags": ["#AIO対策", "#AI検索"],
      "best_hours": [12, 19],
      "generate_instructions": "数字・統計型を50%以上にせよ。スレッドより単発。URL付き投稿は19時に集中させよ。"
    }
  }
}
```

## ディレクトリ構成

```
x-bot/
├── accounts/
│   ├── aio-checker/
│   │   ├── config.json        # アカウント固有設定
│   │   ├── queue.json         # 投稿キュー
│   │   ├── posted.json        # 投稿済み台帳
│   │   ├── engage_history.json
│   │   └── metrics_history.json
│   ├── ai-compla/
│   │   └── (同上)
│   └── hourei-navi/
│       └── (同上)
├── shared/
│   ├── learnings.json         # フィードバックループ出力
│   └── base-prompts.json      # 共通プロンプトテンプレート
├── generate.mjs               # 投稿文生成（3アカウント共通）
├── post.mjs                   # X投稿（3アカウント共通）
├── engage.mjs                 # エンゲージメント（3アカウント共通）
├── metrics.mjs                # 計測（3アカウント共通）
├── learn.mjs                  # フィードバックループ（週次）
├── ad-recommend.mjs           # 広告ブースト推奨（週次）
├── package.json
└── README.md
```

各スクリプトは `--account aio-checker` のように引数でアカウントを切り替える。

## GitHub Actions ワークフロー

```yaml
# .github/workflows/x-bot.yml
# 1つのワークフローで全アカウント・全操作を管理

# スケジュール:
#   06:00 JST — metrics (3アカウント)
#   06:30 JST (月曜のみ) — learn
#   07:00 JST — generate (3アカウント)
#   10:00/14:00/20:00 JST — engage (3アカウント)
#   12:00/16:00/19:00 JST — post (3アカウント)
```

## GitHub Secrets

```
# 3アカウント分 × 4キー = 12個
AIO_X_API_KEY / AIO_X_API_KEY_SECRET / AIO_X_ACCESS_TOKEN / AIO_X_ACCESS_TOKEN_SECRET
COMPLA_X_API_KEY / COMPLA_X_API_KEY_SECRET / COMPLA_X_ACCESS_TOKEN / COMPLA_X_ACCESS_TOKEN_SECRET
HOUREI_X_API_KEY / HOUREI_X_API_KEY_SECRET / HOUREI_X_ACCESS_TOKEN / HOUREI_X_ACCESS_TOKEN_SECRET

# 共通
DEEPSEEK_API_KEY
```

## 自己プロンプトループの全体像

```
週次:
  metrics_history.json (過去7日)
       │
       ▼
  learn.mjs (DeepSeek分析)
       │
       ▼
  learnings.json (「次はこう生成しろ」指示)
       │
       ▼
日次:
  generate.mjs (learnings.json を読み込んでプロンプトに注入)
       │
       ▼
  queue.json → post.mjs → X投稿
       │
       ▼
  metrics.mjs → metrics_history.json
       │
       └──────────▶ 翌週の learn.mjs へ
```

人間が介入するのは:
- 初期設定（アカウント作成、APIキー取得）
- 異常時の対応（凍結、炎上等）
- 月次の方向性確認（pipeline-learnings.md を見て戦略調整）

## セットアップ手順

セットアップは `/test-marketing` スキルの Step 7 で対話式に実行される。
setup-account.mjs は不要（スキル内でconfig.json生成まで完結）。

### /test-marketing 実行時の流れ
1. LP・X投稿案・note記事を生成（Step 1-3）
2. Issue更新・commit（Step 4-6）
3. **x-botアカウントセットアップ（Step 7、対話式）**
   - 「Xアカウントは作成済みですか？」
   - 「アカウント名を入力してください」
   - 「X Developer PortalでAPIキーを取得してください」（手順付き）
   - APIキー4つを順番に入力
   - → GitHub Secrets に自動設定
   - → config.json をブリーフから自動生成
   - → テスト投稿で認証確認
4. **GitHub Actions 確認（Step 8）**
   - x-bot.yml の存在確認
   - DeepSeek APIキーの設定確認

### 手動作業（ユーザー）
- Xアカウント作成（https://x.com）
- X Developer Portal でアプリ作成・APIキー取得
- APIキーをClaude Codeの対話に入力

### 自動処理（Claude Code + GitHub Actions）
- config.json 生成（ブリーフから）
- GitHub Secrets 設定
- テスト投稿
- 以降の投稿・エンゲージメント・計測・学習はすべて自動

## コスト見込み

| 項目 | 月額 |
|------|------|
| X API (3アカウント × 3本/日) | $6-15 (約¥900-2,250) |
| DeepSeek API (生成+リプライ+学習) | $1-3 (約¥150-450) |
| X広告ブースト (推奨投稿のみ、任意) | ¥2,000-12,000 |
| **合計（広告なし）** | **約¥1,050-2,700/月** |
| **合計（広告あり）** | **約¥3,050-14,700/月** |

## 6. ad-recommend.mjs — 広告ブースト推奨（新規）

```
実行: learn.mjs の後続（毎週月曜 6:45 JST）
入力: metrics_history.json (3アカウント分)
出力: GitHub Issue にプロモート推奨通知
```

Ads APIは高額プラン（月$99〜のBasic以上）が必要なため、
**「どの投稿を広告すべきか」の判断だけ自動化**し、実行は手動1タップ。

処理:
1. 過去7日間の全投稿からimp/♥/RTの上位投稿を抽出
2. 「広告ブースト推奨スコア」を算出:
   - エンゲージメント率（♥+RT+返信 / imp）が上位20%
   - かつ imp が一定以上（自然リーチで伸びている証拠）
   - かつ LP誘導型の投稿（URL付き or CTA含む）を優先
3. 推奨投稿をGitHub Issueに通知:

```markdown
## 広告ブースト推奨（2026-06-16週）

### @account_1 (brief_26)
- **推奨**: [この投稿](https://x.com/account_1/status/xxx)
  imp: 1,200 / ♥: 45 / RT: 12 / エンゲージメント率: 4.8%
  → Xアプリで「投稿をプロモート」→ 予算¥500-1,000/日で3日間テスト

### @account_2 (brief_35)
- 今週は推奨なし（エンゲージメント率が基準未満）

### @account_3 (brief_37)
- **推奨**: [この投稿](https://x.com/account_3/status/yyy)
  imp: 800 / ♥: 32 / RT: 8 / エンゲージメント率: 5.0%
  → 予算¥500/日で3日間テスト
```

※ アカウント名・ブリーフ番号は `x-bot/accounts/*/config.json` から動的に読み込む。

推奨基準:
| 条件 | しきい値 |
|------|---------|
| エンゲージメント率 | 上位20%かつ2%以上 |
| 最低imp | 300以上 |
| 投稿タイプ | LP誘導型・CTA含む投稿を2倍加重 |
| 推奨上限 | 1アカウントにつき週1件まで |

広告予算の目安:
| フェーズ | 予算/アカウント/週 | 目的 |
|---------|-------------------|------|
| テスト期（最初の1ヶ月） | ¥500-1,000 | どの投稿タイプが広告で伸びるか検証 |
| 拡大期 | ¥2,000-5,000 | 効果実証済みの投稿タイプに集中 |
| 定常運用 | learn.mjsの推奨に従う | ROI基準で自動判断 |

learn.mjs との連携:
- 広告ブーストした投稿のメトリクス変化を記録
- 「広告で伸びやすい投稿パターン」を学習
- 次回のgenerate.mjsで「広告向き投稿」を意図的に生成する指示を追加

---

## GitHub Actions スケジュール（更新版）

```yaml
# .github/workflows/x-bot.yml

# 06:00 JST — metrics (3アカウント)
# 06:30 JST (月曜のみ) — learn
# 06:45 JST (月曜のみ) — ad-recommend
# 07:00 JST — generate (3アカウント)
# 10:00/14:00/20:00 JST — engage (3アカウント)
# 12:00/16:00/19:00 JST — post (3アカウント)
```

---

## リスクと対策

| リスク | 対策 |
|--------|------|
| アカウント凍結 | X API使用（ブラウザ自動化不使用）、日次上限設定、自然な投稿間隔 |
| 炎上 | 禁止トピックリスト、政治/事件/災害に絡めない、攻撃的表現の自動除外 |
| 暴走課金 | X API spending cap設定、DeepSeek APIにも上限設定 |
| 広告費暴走 | 週次推奨のみ（自動出稿しない）、手動1タップで実行、予算上限を明示 |
| 低品質投稿 | learn.mjsのフィードバックで自動改善、月次で人間レビュー |
