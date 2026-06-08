# Phase 2: 市場検証プロンプト

> Claude Code で実行する。PC起動時に週1回。

## 実行手順

```bash
# Step 1: 検証対象を取得
python bot/validate.py fetch

# Step 2: このプロンプトに従い調査・評価（Claude Code が実行）

# Step 3: 結果をIssueに反映
python bot/validate.py post
```

## Step 2 の詳細指示

`bot/validate_input.json` を読み込み、各Issueについて以下を実行せよ。

### 2-1. 競合調査

各仮説について Exa 検索（または Web 検索）で以下を調べる:
- 同じ課題を解決する既存サービス
- 価格帯、機能の網羅度、ターゲット
- 弱点・隙（UI悪い、日本語未対応、高額すぎる等）

出力例:
```
主な競合: ServiceA ($30/月), ServiceB (日本語なし)
隙: 日本の中小企業向けに特化したものがない。ServiceAは大企業向けで高額。
```

### 2-2. 需要の裏付け

以下のソースで需要を確認:
- 検索ボリュームの推定（関連キーワードの人気度）
- SNS/フォーラムでの類似の悩み投稿
- 業界レポートや統計

出力例:
```
「法改正 対応 ツール」月間検索 2,400件。
X上で「法改正ついていけない」系投稿が週50+件。
中小企業庁調査: 73%が法改正対応を負担と回答。
```

### 2-3. ナレッジ照合

`validate_input.json` 内の `knowledge_insights` から関連するインサイトを特定し、
仮説を補強する知見があるか確認する。

確認観点:
- 類似ターゲットの既存ペイン情報
- 類似ソリューションの成功/失敗パターン
- マーケティング手法の有効性データ

出力例:
```
ナレッジID #142: 「法改正対応は"恐怖訴求"が効く。罰則・期限を前面に出すLPのCVRが3.2倍」
ナレッジID #89: 「中小企業向けコンプライアンスツールはfreee/マネフォが手薄な領域」
```

### 2-4. スコアリング

| 軸 | 基準 | 点数 |
|---|---|---|
| 競合の隙 | 直接競合なし=3 / 弱い競合のみ=2 / 差別化可能=1 / 大手独占=0 | 0-3 |
| 需要確認 | 明確な証拠=3 / ある程度=2 / 微妙=1 / なし=0 | 0-3 |
| 収益成立性 | 明確に成立=2 / ギリギリ=1 / 非現実的=0 | 0-2 |
| タイミング | 今がベスト=2 / 悪くない=1 / 遅い/早すぎ=0 | 0-2 |

**判定:**
- 7点以上 → `pass`（検証済、テストマーケへ）
- 4-6点 → `hold`（保留）
- 3点以下 → `reject`（却下、Issueクローズ）

### 2-5. マーケブリーフ生成（passの場合のみ）

検証済み仮説にはPhase 3用のマーケブリーフを生成する:

```json
{
  "target_persona": "誰に売るか（具体的に）",
  "pain_statement": "ターゲットが共感する痛みの表現",
  "solution_hook": "一文で伝わるソリューション説明",
  "differentiator": "競合との違い（なぜこれを選ぶか）",
  "cta_design": "CTAの設計（何をしてもらうか）",
  "pricing_hint": "想定価格帯",
  "channels": ["有効なチャネル"],
  "lp_angle": "LPの訴求角度",
  "x_hooks": ["X投稿で使えるフック3つ"],
  "knowledge_backed_tactics": ["ナレッジから得たマーケ戦術"]
}
```

## 出力フォーマット

調査完了後、以下の形式で `bot/validate_output.json` に書き込む:

```json
{
  "validated_at": "ISO8601",
  "results": [
    {
      "issue_number": 30,
      "issue_title": "...",
      "verdict": "pass",
      "market_fit_score": 8,
      "score_competitive_gap": 2,
      "score_demand_evidence": 3,
      "score_revenue_viability": 2,
      "score_timing": 1,
      "competitive_analysis": "競合調査の結果テキスト",
      "demand_evidence": "需要裏付けのテキスト",
      "knowledge_match": "関連ナレッジIDと内容",
      "marketing_brief": { ... }
    }
  ]
}
```

## 注意事項

- 厳しめに評価すること。量産しているので、通過率30-50%が健全
- 「なんとなく良さそう」では pass にしない。具体的な証拠が必要
- ナレッジに「この手のツールは失敗する」という知見があれば素直に reject
- マーケブリーフは Phase 3 で DeepSeek が読むので、簡潔・具体的に書く
