// 高適合度 Issue に対して Step 1-9 のフルリサーチを実行し、Issue コメントとして投稿
//
// 使い方: node bot/deep-research.mjs [--manual 5,6,7]
//   引数なし: founder-fit >= 8 の issue を自動収集
//   --manual: 指定した issue 番号のみ対象
// 環境変数: DEEPSEEK_API_KEY, GH_TOKEN
import OpenAI from 'openai';
import { execSync } from 'node:child_process';
import { writeFileSync, readFileSync, readdirSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { retryWithBackoff } from './retry.mjs';

const { DEEPSEEK_API_KEY } = process.env;
if (!DEEPSEEK_API_KEY) {
  console.error('DEEPSEEK_API_KEY が未設定');
  process.exit(1);
}

const ai = new OpenAI({
  baseURL: 'https://api.deepseek.com',
  apiKey: DEEPSEEK_API_KEY,
});

const REPO = 'beru3/business-ideation-bot';
const gh = (args) => execSync('gh ' + args, { encoding: 'utf8' }).trim();
const DEEP_RESEARCH_MARKER = '<!-- deep-research:v1 -->';

const dir = fileURLToPath(new URL('./', import.meta.url));

// --- ターゲット収集 ---
function collectTargetsFromHistory() {
  const historyDir = dir + 'history/';
  mkdirSync(historyDir, { recursive: true });
  const files = readdirSync(historyDir).filter(f => f.endsWith('.json'));
  const targets = [];
  for (const f of files) {
    try {
      const item = JSON.parse(readFileSync(historyDir + f, 'utf8'));
      if (item.founder_fit_score >= 8 && item.id) {
        targets.push({
          issueNumber: parseInt(item.id, 10),
          topic: item.title,
          description: `founder-fit ${item.founder_fit_score}/10 — domain: ${item.domain_id}`,
        });
      }
    } catch { /* skip */ }
  }
  return targets;
}

function parseManualTargets(arg) {
  return arg.split(',').map(n => parseInt(n.trim(), 10)).filter(n => !isNaN(n)).map(n => ({
    issueNumber: n,
    topic: `Issue #${n}`,
    description: '手動指定',
  }));
}

const manualIdx = process.argv.indexOf('--manual');
const targets = manualIdx >= 0 && process.argv[manualIdx + 1]
  ? parseManualTargets(process.argv[manualIdx + 1])
  : collectTargetsFromHistory();

if (targets.length === 0) {
  console.log('対象 Issue なし（founder-fit >= 8 の Issue が見つかりませんでした）');
  process.exit(0);
}

console.log(`対象: ${targets.length}件`);

const systemPrompt = `あなたは新規事業の機会発掘の専門家です。指定されたプロダクトアイデアについて、以下のパイプラインで詳細分析を行ってください。

## Step 1: 失敗事例の収集
このプロダクトと同じ領域・類似領域で、過去に失敗・撤退・閉鎖したアプリ・サービス・スタートアップを5〜8件列挙してください。
各事例に以下を併記:
- 事業名・形態
- ピーク時の規模（調達額・ユーザー数等）
- 死亡時期
- 死因（1-2行）
- 出典（ニュース記事URL、プレスリリース、報道等の根拠を1つ以上）

**重要**: 実在する事例のみ記載すること。架空の事例や、存在が確認できない事業を捏造しないこと。事実確認が曖昧な場合は「※未確認」と明記すること。

## Step 2: 失敗パターンの分類
収集した事例を以下のパターンで分類:
- P1: スマホ代替誤認
- P2: コスト青天井
- P3: FOMOバイラル誤認
- P4: 一過性トレンド固定化
- P5: マネタイズ不在
- P6: 時期過早
- P7: デモと製品の乖離
- その他

## Step 3: 機会仮説の深掘り
このプロダクトが「なぜ今なら成功できるか」を以下の観点で分析:
- 起点となる失敗事例との違い
- 現代環境で何が変わったか（技術コスト低下、規制変化、人口動態、インフラ普及、競合変化）
- 誰の・痛みの本質・解法
- 失敗からの学び（同じ罠をどう回避するか）

## Step 4: Pre-mortem（事前検死）
「18ヶ月後にこのプロダクトが死んでいるとしたら死因は何か」を3つ挙げ、それぞれの回避策を記載。

## Step 5: 市場規模と最小反証実験
- **TAM/SAM/SOM概算**: 日本市場での規模を根拠となる統計・数字とともに記載
- **最小反証実験**: 1週間以内・コストゼロ〜数万円で仮説を検証できる実験を2つ設計
  - 何を検証するか / どうやって / 失敗の判定基準

## Step 6: 総合評価と推奨戦略
以下の5軸で10点満点で採点:
- タイミング適合度
- 参入障壁構築可能性
- 収益性
- 実現難易度（10=容易）
- 市場の痛みの深さ

**なぜ今やるべきか**を以下3つの観点で具体的に説明:
1. AIによるコスト構造の変化
2. 既存プレイヤーの構造的弱点
3. 規制・社会変化の追い風

## Step 7: 90日アクションプラン
### Phase 1: 検証期（Day 1〜30）
- 具体的アクション、初期投資額、Go/No-Go判定基準
### Phase 2: MVP開発期（Day 31〜60）
- MVPスコープ（やること3つ/やらないこと3つ）、技術スタック、開発コスト
### Phase 3: 初期トラクション期（Day 61〜90）
- 最初の有料顧客5社の獲得戦略、KPI目標、90日後の到達点

## Step 8: 逆算思考フレームワーク

### 8-1. ゴール数字逆算
月収目標（50万円）から逆算:
- 月収目標 ÷ 月額単価 = 必要契約数
- 必要契約数 ÷ トライアル→有料転換率 = 必要トライアル数
- 必要トライアル数 ÷ LP→登録CVR = 必要LP訪問数
- 日次KPI

### 8-2. SNS戦略
- メインチャネル選定（理由付き）
- バズりやすい投稿フォーマット3パターン（具体的な投稿文案つき）
- 投稿頻度

### 8-3. 開発前の需要テスト（モックアップ検証）
- モックアップの内容
- SNS投稿文案（コピペで使えるレベル）
- 判定基準（いいね○件以上等の数値基準）
- 事前登録フロー

### 8-4. Build in Public 計画
4フェーズのタイムライン:
- Phase 1: 問題提起 & 認知（Week 1-2）
- Phase 2: モックアップ & 需要テスト（Week 3-4）
- Phase 3: MVP開発の裏側を公開（Week 5-8）
- Phase 4: ベータテスト & 事例公開（Week 9-12）

### 8-5. 競合レビュー分析
- 既存競合4〜5個（サービス名・概要・弱点）
- レビューで頻出する不満 → 自社での解決策
- 空白地帯

## Step 9: マネタイズロードマップ

### 9-1. 課金モデル設計
- 最適な課金モデルと理由
- 価格帯の根拠（競合比較、支払い意思額、コスト構造）
- プラン設計（Free / Basic / Pro）

### 9-2. 収益シミュレーション
- 6ヶ月・12ヶ月・24ヶ月のMRR / ARR
- 前提条件（月間新規獲得数、チャーン率、ARPU）
- 損益分岐点（何ヶ月目に黒字化、必要契約数）

### 9-3. マネタイズまでのマイルストーン
- Month 1-3: 無料ベータ → 有料転換テスト
- Month 4-6: 初期課金開始 → プラン最適化
- Month 7-12: スケール → 追加収益源
- 各マイルストーンのGo/No-Go判定基準（定量）

## 出力ルール
- Markdown形式で見やすく構造化すること
- 曖昧な根拠は禁止。数字・事例・具体的アクションで答えること
- 日本市場を前提とすること
- 実在しない事例を捏造しないこと
- 市場規模の根拠には公的統計・業界レポート等の出典を明記すること`;

const today = new Date().toISOString().slice(0, 10);

for (const target of targets) {
  console.log(`\n${'='.repeat(60)}`);
  console.log(`Issue #${target.issueNumber}: ${target.topic}`);
  console.log('='.repeat(60));

  // 冪等化: 既存の深掘りコメントがあればスキップ
  try {
    const comments = gh(`api repos/${REPO}/issues/${target.issueNumber}/comments --jq '[.[].body]'`);
    const bodies = JSON.parse(comments);
    if (bodies.some(b => b.includes(DEEP_RESEARCH_MARKER))) {
      console.log(`Issue #${target.issueNumber} は既に深掘り済み — スキップ`);
      continue;
    }
  } catch (e) {
    console.warn(`コメント確認失敗（続行）: ${e.message}`);
  }

  const userPrompt = `今日は${today}です。

【対象プロダクト】${target.topic}

【プロダクト概要】${target.description}

このプロダクトについて、Step 1〜9のフルリサーチを実行してください。`;

  console.log('DeepSeek APIで調査実行中…');

  const response = await retryWithBackoff(() =>
    ai.chat.completions.create({
      model: 'deepseek-chat',
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt },
      ],
      temperature: 0.7,
      max_tokens: 8000,
    })
  );

  const content = response.choices[0].message.content.trim();
  const usage = response.usage;
  console.log(`トークン: input=${usage?.prompt_tokens}, output=${usage?.completion_tokens}`);

  const comment = [
    DEEP_RESEARCH_MARKER,
    `# Step 1-9 フルリサーチ: ${target.topic}`,
    '',
    `> 自動生成 (${today}) | DeepSeek Chat | tokens: in=${usage?.prompt_tokens} out=${usage?.completion_tokens}`,
    '',
    content,
  ].join('\n');

  writeFileSync('/tmp/deep_research.md', comment);
  const commentUrl = gh(`issue comment ${target.issueNumber} --repo ${REPO} --body-file /tmp/deep_research.md`);
  console.log(`コメント投稿: ${commentUrl}`);
}

console.log('\n全プロダクトのリサーチ完了。');
