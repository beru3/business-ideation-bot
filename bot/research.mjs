// 新規事業アイデア自動調査bot v2
//   node research.mjs        … 調査実行 → Issue投稿 → メール通知 → 履歴保存
//   node research.mjs --dry  … 調査のみ（Issue投稿・メール送信・履歴保存なし）
//
// 必要な環境変数:
//   DEEPSEEK_API_KEY
//   GH_TOKEN（Issue作成用）
//   GMAIL_USERNAME, GMAIL_APP_PASSWORD（メール通知用）
import OpenAI from 'openai';
import { createTransport } from 'nodemailer';
import { readFileSync, writeFileSync, mkdirSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { execSync } from 'node:child_process';
import { calculateSimilarity, classifyIdea } from './similarity.mjs';

const dir = fileURLToPath(new URL('./', import.meta.url));
const dryRun = process.argv.includes('--dry');

// --- 0. 環境変数チェック ---
if (!process.env.DEEPSEEK_API_KEY) {
  console.error('環境変数が未設定: DEEPSEEK_API_KEY');
  process.exit(1);
}

const ai = new OpenAI({
  baseURL: 'https://api.deepseek.com',
  apiKey: process.env.DEEPSEEK_API_KEY,
});

const REPO = 'beru3/business-ideation-bot';
const gh = (args) => execSync('gh ' + args, { encoding: 'utf8' }).trim();

// --- 1. テーマ選択（重み付きドメイン → テーマ） ---
const themesConfig = JSON.parse(readFileSync(dir + 'themes.json', 'utf8'));
const brandsConfig = JSON.parse(readFileSync(dir + '../brands.json', 'utf8'));

function selectThemeByWeight(config) {
  const totalWeight = config.domains.reduce((s, d) => s + d.weight, 0);
  let r = Math.random() * totalWeight;
  for (const domain of config.domains) {
    r -= domain.weight;
    if (r <= 0) {
      const theme = domain.themes[Math.floor(Math.random() * domain.themes.length)];
      return { theme, domainId: domain.id };
    }
  }
  const fallback = config.domains[0];
  return { theme: fallback.themes[0], domainId: fallback.id };
}

const { theme: todayTheme, domainId } = selectThemeByWeight(themesConfig);
console.log(`テーマ: ${todayTheme} (domain: ${domainId})`);

// --- 2. スポーク自動判定 ---
function assignSpoke(themeText, config) {
  const matches = config.spokes.map(spoke => ({
    spokeId: spoke.id,
    score: spoke.target_keywords.filter(kw => themeText.includes(kw)).length,
    specificity: spoke.target_keywords.length,
  }));
  // 同スコア時はキーワード数が少ない（＝より特化した）スポークを優先
  matches.sort((a, b) => b.score - a.score || a.specificity - b.specificity);
  return matches[0].score > 0 ? matches[0].spokeId : 'unassigned';
}

const spokeId = assignSpoke(todayTheme, brandsConfig);
console.log(`スポーク: ${spokeId}`);

// --- 3. 過去の結果を取得（重複判定用） ---
const history = JSON.parse(readFileSync(dir + 'results_history.json', 'utf8'));
const pastHashes = new Set(history.map(h => h.hash));
const pastSummaries = history
  .filter(h => h.theme === todayTheme)
  .slice(-3)
  .map(h => h.summary);

const avoidText = pastSummaries.length > 0
  ? `\n\n【過去にこのテーマで出した仮説（重複しないこと）】\n${pastSummaries.map(s => `- ${s}`).join('\n')}`
  : '';

// --- 4. 構造化履歴の読み込み（類似度判定用） ---
function loadStructuredHistory(historyDir, retentionDays) {
  mkdirSync(historyDir, { recursive: true });
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - retentionDays);
  const cutoffStr = cutoff.toISOString().slice(0, 10);

  const files = readdirSync(historyDir).filter(f => f.endsWith('.json'));
  const items = [];
  for (const f of files) {
    try {
      const item = JSON.parse(readFileSync(historyDir + f, 'utf8'));
      if (item.generated_at && item.generated_at.slice(0, 10) >= cutoffStr) {
        items.push(item);
      }
    } catch { /* skip corrupt files */ }
  }
  return items;
}

const historyDir = dir + 'history/';
const structuredHistory = loadStructuredHistory(historyDir, 180);
console.log(`構造化履歴: ${structuredHistory.length}件`);

// --- 5. プロンプト構築 ---
const today = new Date().toISOString().slice(0, 10);

const systemPrompt = `あなたは新規事業の機会発掘の専門家です。過去に失敗したアプリ・サービス・スタートアップを起点に、現代環境で再起動可能な新規事業の機会仮説を生成します。

以下のパイプラインで分析してください:

## Step 1: 失敗事例の収集
指定された業界・領域で、過去に失敗・撤退・閉鎖したアプリ・サービス・スタートアップを5〜8件列挙してください。
各事例に以下を併記:
- 事業名・形態
- ピーク時の規模（調達額・ユーザー数等）
- 死亡時期
- 死因（1-2行）
- 出典（ニュース記事URL、プレスリリース、報道等の根拠を1つ以上）

**重要**: 実在する事例のみ記載すること。架空の事例や、存在が確認できない事業を捏造しないこと。事実確認が曖昧な場合は「※未確認」と明記すること。

## Step 2: 失敗パターンの分類
収集した事例を以下のパターンで分類:
- P1: スマホ代替誤認（スマホで十分なのに別形態で再現）
- P2: コスト青天井（売上 < ランニングコスト）
- P3: FOMOバイラル誤認（初期狂熱を持続需要と勘違い）
- P4: 一過性トレンド固定化（一時需要を構造変化と誤認）
- P5: マネタイズ不在（ユーザー獲得 ≠ 収益）
- P6: 時期過早（アイデア正、タイミング誤）
- P7: デモと製品の乖離
- その他（新パターン発見歓迎）

## Step 3: 機会仮説の生成
失敗事例から、現代環境で再起動可能な機会仮説を2〜3個生成してください。

各仮説に以下を含めること:
- 起点となった失敗事例
- 派生方向（A:タイミング再起動 / B:ターゲット再定義 / C:業界特化）
- 現代環境で何が違うか（5変化要因のいずれか）
  1. 技術コストの非連続的低下
  2. 規制環境の構造変化
  3. 人口動態の不可逆変化
  4. インフラの普及
  5. 競合の構造変化
- 誰の・痛みの本質・解法
- ソリューション形態（SaaS/アプリ/API等）
- 失敗からの学び（同じ罠をどう回避するか）

## Step 4: Pre-mortem（事前検死）
各仮説について「18ヶ月後にこの事業が死んでいるとしたら死因は何か」を2つ挙げてください。

## Step 5: 市場規模と最小反証実験
各仮説について以下を記載:
- **TAM/SAM概算**: 対象市場の規模を日本市場で概算（根拠となる統計・数字を明記）
- **最小反証実験**: 1週間以内・コストゼロ〜数万円で「この仮説が間違っている」ことを検証できる具体的な実験を1つ設計
  - 何を検証するか
  - どうやって検証するか（LP作成、ヒアリング、広告テスト等）
  - 「失敗」の判定基準（例: CVR 1%未満なら仮説棄却）

## Step 6: 総合評価と推奨戦略
全仮説を以下の5軸で10点満点で採点し、表形式で総合スコア順に並べてください:
- **タイミング適合度**: 今この瞬間に始める必然性があるか（AI・規制・人口動態等の追い風）
- **参入障壁構築可能性**: 後発に真似されにくい堀を築けるか（データネットワーク効果、スイッチングコスト等）
- **収益性**: ユニットエコノミクスが成立するか（LTV/CAC > 3x）
- **実現難易度（逆転）**: 技術・チーム・資金の観点で実現しやすいか（10=容易）
- **市場の痛みの深さ**: 「あったらいいな」ではなく「ないと困る」レベルか

最高スコアの仮説について、**なぜ今やるべきか**を以下3つの観点で具体的に説明:
1. AIによるコスト構造の変化（何が何分の1になったか）
2. 既存プレイヤーの構造的弱点（なぜ大手がやらない／できないか）
3. 規制・社会変化の追い風（どの法改正・トレンドが味方か）

## Step 7: 90日アクションプラン
最高スコアの仮説について、個人または少人数チームが実行可能な90日間のアクションプランを作成:

### Phase 1: 検証期（Day 1〜30）
- 仮説検証の具体的アクション（ヒアリング先の属性・人数、LP構成、広告テスト設計等）
- 必要な初期投資額（円単位で）
- Go/No-Go判定基準（定量）

### Phase 2: MVP開発期（Day 31〜60）
- MVPの機能スコープ（やること3つ / やらないこと3つ）
- 推奨技術スタック
- 想定開発コスト・体制

### Phase 3: 初期トラクション期（Day 61〜90）
- 最初の有料顧客5社の獲得戦略（具体的なチャネルとアプローチ）
- KPI目標（MRR、契約数、NPS等を数値で）
- 90日後の到達点と次の意思決定ポイント

## Step 8: 逆算思考フレームワーク（最高スコアの仮説に適用）

### 8-1. ゴール数字逆算
月収目標（例: 50万円）から逆算して以下を算出:
- 月収目標 ÷ 月額単価 = 必要契約数
- 必要契約数 ÷ トライアル→有料転換率 = 必要トライアル数
- 必要トライアル数 ÷ LP→登録CVR = 必要LP訪問数
- 日次KPI（1日あたりのLP訪問・登録・転換目標）

### 8-2. SNS戦略
- **メインチャネル選定**: ターゲット層が最も集まるSNSを1つ選定（X / LinkedIn / Instagram / note等）し、理由を明記
- **コンテンツ設計**: バズりやすい投稿フォーマットを3パターン提案（例: Before/After、業界あるある×解決策、数字で衝撃）
- **投稿頻度**: 推奨頻度とリソース見合い

### 8-3. 開発前の需要テスト（モックアップ検証）
- AI画像生成でプロダクトのモックアップを作成し、SNSに投稿して反応を測る
- 具体的な投稿文案（コピペで使えるレベル）
- 判定基準: いいね○件以上で需要あり / ○件未満でピボット等の数値基準
- 反応が良い場合のGoogle Form事前登録フロー

### 8-4. Build in Public 計画
4フェーズのタイムラインを作成:
- Phase 1: 問題提起 & 認知（Week 1-2）
- Phase 2: モックアップ & 需要テスト（Week 3-4）
- Phase 3: MVP開発の裏側を公開（Week 5-8）
- Phase 4: ベータテスト & 事例公開（Week 9-12）

### 8-5. 競合レビュー分析
- 既存の競合サービスを4〜5個リストアップ（サービス名・概要・弱点）
- アプリストアやSNSのレビューで頻出する不満を抽出
- その不満を自社プロダクトでどう解決するかを対応表で示す
- 空白地帯（誰もカバーしていない領域）を明示

## Step 9: マネタイズロードマップ（最高スコアの仮説に適用）

### 9-1. 課金モデル設計
- フリーミアム / サブスクリプション / 従量課金 / 買い切り等から最適なモデルを選定し理由を明記
- 価格帯の設定根拠（競合比較、顧客の支払い意思額、コスト構造から逆算）
- プラン設計（Free / Basic / Pro等の機能差と想定単価）

### 9-2. 収益シミュレーション
- 6ヶ月・12ヶ月・24ヶ月時点での想定MRR / ARR
- 主要な前提条件（月間新規獲得数、チャーン率、ARPU）
- 損益分岐点（何ヶ月目に黒字化するか、必要契約数）

### 9-3. マネタイズまでのマイルストーン
具体的な時系列で記載:
- Month 1-3: 無料ベータ → 有料転換テスト
- Month 4-6: 初期課金開始 → プラン最適化
- Month 7-12: スケール → 追加収益源（アップセル、API提供等）
- 各マイルストーンのGo/No-Go判定基準（定量）

## ミルカルテ方法論との適合度評価（必須出力）

以下6軸で評価し、それぞれのスコアと理由を出力すること。

1. **データソース層** (3点満点)
   - UKE/レセプト/介護給付費明細書等の公的・規制由来の構造化データが存在するか
   - 存在し標準フォーマットあり: 3点
   - 存在するが未統一: 2点
   - 業界データはあるが規制由来でない: 1点
   - 構造化データなし: 0点

2. **ARPU許容度** (2点満点)
   - 想定顧客は月額¥20,000以上を支払えるか
   - ¥50,000以上余裕: 2点 / ¥20,000〜¥50,000: 1点 / ¥20,000未満: 0点

3. **顧客の安定性** (2点満点)
   - 想定顧客(事業所)の年間廃業率
   - 2%以下: 2点 / 2〜5%: 1点 / 5%以上: 0点

4. **販路の流用可能性** (2点満点)
   - ミルカルテで使う販路(医師会・ORCA管理機構・業界紙)を流用できるか
   - ほぼ完全流用可: 2点 / 部分流用可: 1点 / 別販路必要: 0点

5. **規制対応の流用度** (1点満点)
   - 個人情報・要配慮個人情報の取扱が既存規制対応で流用できるか
   - 完全流用: 1点 / 部分流用または不要: 0点

6. **時流の追い風** (該当時+1点ボーナス)
   - 直近3年の規制変更・制度改正・社会変化で需要が拡大しているか

## 総合スコア
X/10点（+ボーナス1点）

## スポーク帰属判定
- 既存スポーク (mirukarte, dental, kaigo) のどれに最も近いか: ___
- 新規スポーク候補として独立すべきか: [Yes/No]
- 理由: ___

## 構造化属性（必須・JSONコードブロックで出力）

\`\`\`structured_attrs
{
  "data_source_type": "unregulated_paper | regulated_format | api_available | none",
  "target_industry": "medical-clinic | dental | pharmacy | acupuncture | visiting-nursing | care-facility | restaurant-individual | retail-individual | other-XXX",
  "revenue_model": "saas-subscription | usage-based | success-fee | b2b2c-bundled | freemium | one-time",
  "value_layer": "visualization | execution | both | platform",
  "regulation_level": "high-medical | medium-financial | low-general"
}
\`\`\`

語彙は上記列挙のいずれかから厳密に選択すること。該当なしの場合は\`other-XXX\`形式で記述（例: \`other-veterinary\`）。

## 人間判断用サマリ（必須・3行のみ）

1. **なぜ今面白いか**（時流の追い風を1文で）: ___
2. **並列で走らせる場合の追加投資**: 月¥____ / 週___時間
3. **90日後にkillする判定基準**（数値で）: ___件未満なら撤退

## 出力ルール
- Markdown形式で見やすく構造化すること
- 「気合」「成熟した」のような曖昧な根拠は禁止
- 「ブランド」「UX」だけを堀として主張しない
- 実行レイヤーまで含む解法にする（分析・可視化だけで終わらない）
- 日本市場を前提とする
- 実在しない事例を捏造しないこと。確信度が低い情報には「※未確認」を付記すること
- 市場規模の根拠には公的統計・業界レポート等の出典を明記すること`;

const userPrompt = `今日は${today}です。

【調査テーマ】${todayTheme}
【ドメイン】${domainId}

このテーマで、過去に失敗したアプリ・サービス・スタートアップを起点に、現代で再起動可能な新規事業の機会仮説を生成してください。

上記パイプライン（Step 1〜9 + ミルカルテ適合度評価 + 構造化属性 + 人間判断用サマリ）に沿って分析し、最後に以下のJSON形式で仮説サマリーを出力してください（本文の分析の後に追記）。

\`\`\`json
{
  "theme": "${todayTheme}",
  "hypotheses": [
    {
      "name": "仮説の短い名前",
      "origin_failure": "起点となった失敗事業名",
      "summary": "1-2文の仮説サマリー",
      "change_factor": "変化要因（1-5のいずれか）",
      "solution_type": "SaaS/アプリ/API等",
      "tam_billion_yen": "TAM概算（億円）",
      "falsification_test": "最小反証実験の概要（1文）",
      "score": "総合スコア（50点満点）",
      "recommended": "最推奨ならtrue、それ以外はfalse"
    }
  ]
}
\`\`\`${avoidText}`;

// --- 6. DeepSeek APIで調査実行 ---
console.log('DeepSeek APIで調査実行中…');

const response = await ai.chat.completions.create({
  model: 'deepseek-chat',
  messages: [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: userPrompt },
  ],
  temperature: 0.7,
  max_tokens: 16000,
});

const content = response.choices[0].message.content.trim();
const usage = response.usage;
console.log(`トークン: input=${usage?.prompt_tokens}, output=${usage?.completion_tokens}`);

// --- 7. 重複判定（ハッシュベース） ---
const contentHash = createHash('sha256').update(content).digest('hex').slice(0, 16);

if (pastHashes.has(contentHash)) {
  console.log('完全重複のためスキップ。');
  process.exit(0);
}

// --- 8. JSON出力の抽出 ---
// 仮説サマリーJSON
let hypotheses = [];
const jsonMatch = content.match(/```json\s*\n([\s\S]*?)\n```/);
if (jsonMatch) {
  try {
    const parsed = JSON.parse(jsonMatch[1]);
    hypotheses = parsed.hypotheses || [];
  } catch (e) {
    console.warn('JSONサマリーのパース失敗（本文レポートは投稿します）:', e.message);
  }
}

// 構造化属性JSON
let structuredAttrs = null;
const attrsMatch = content.match(/```structured_attrs\s*\n([\s\S]*?)\n```/);
if (attrsMatch) {
  try {
    structuredAttrs = JSON.parse(attrsMatch[1]);
  } catch (e) {
    console.warn('構造化属性のパース失敗:', e.message);
  }
}

// ミルカルテ適合度スコア抽出（複数パターン対応）
let mirukarteScore = null;
const scoreMatch = content.match(/総合スコア[\s\S]*?(\d+(?:\.\d+)?)\s*[\/／]\s*10/)
  || content.match(/適合度[\s\S]*?(\d+(?:\.\d+)?)\s*[\/／]\s*10/);
if (scoreMatch) {
  mirukarteScore = parseFloat(scoreMatch[1]);
}
console.log(`ミルカルテ適合度: ${mirukarteScore ?? '抽出失敗'}/10`);

// 仮説名の重複チェック（トークン重複率50%以上で重複とみなす）
const pastNames = history
  .filter(h => h.theme === todayTheme)
  .flatMap(h => h.hypothesisNames || []);

const tokenize = (s) => s.replace(/[【】（）()・/／]/g, ' ').split(/\s+/).filter(Boolean);

const isSimilar = (a, b) => {
  const tokensA = tokenize(a);
  const tokensB = new Set(tokenize(b));
  const overlap = tokensA.filter(t => tokensB.has(t)).length;
  const maxLen = Math.max(tokensA.length, tokensB.size);
  return maxLen > 0 && overlap / maxLen >= 0.5;
};

const newHypotheses = hypotheses.filter(
  h => !pastNames.some(past => past === h.name || isSimilar(past, h.name))
);
const skippedCount = hypotheses.length - newHypotheses.length;

if (skippedCount > 0) {
  console.log(`仮説${skippedCount}件が過去と重複のためスキップ`);
}

if (newHypotheses.length === 0 && hypotheses.length > 0) {
  console.log('全仮説が重複のためスキップ。');
  process.exit(0);
}

console.log(`新規仮説: ${newHypotheses.length}件`);

// --- 9. 構造化属性ベースの類似度チェック ---
let classification = { action: 'create_issue', tag: 'novel', similar_to: [] };

if (structuredAttrs && structuredHistory.length > 0) {
  let simConfig;
  try {
    simConfig = JSON.parse(readFileSync(dir + 'similarity.config.json', 'utf8'));
  } catch {
    simConfig = { duplicateThreshold: 0.85, expansionThreshold: 0.65 };
  }

  const newIdea = { structured_attrs: structuredAttrs };
  classification = classifyIdea(newIdea, structuredHistory, simConfig);
  console.log(`類似度判定: ${classification.tag} (action: ${classification.action})`);

  if (classification.action === 'skip_duplicate') {
    console.log(`重複スキップ: ${classification.reason}`);
    if (!dryRun) {
      const existingId = classification.similar_to[0].id;
      const reTitle = newHypotheses.map(h => h.name).join(' / ') || todayTheme;
      const commentBody = `本日再度同じ抽象構造のアイデアが生成されました: "${reTitle}"\n\nドメイン: ${domainId} | テーマ: ${todayTheme}`;
      writeFileSync('/tmp/dup_comment.md', commentBody);
      try {
        gh(`issue comment ${existingId} --repo ${REPO} --body-file /tmp/dup_comment.md`);
        console.log(`既存Issue #${existingId} にコメント追加`);
      } catch (e) {
        console.warn('コメント追加失敗:', e.message);
      }
    }
    process.exit(0);
  }
}

// --- 10. 推奨アクション判定 ---
function getRecommendedAction(score) {
  if (score == null) return 'monitor';
  if (score >= 8) return 'promote-to-marketing-test';
  if (score >= 5) return 'monitor';
  return 'skip';
}

const recommendedAction = getRecommendedAction(mirukarteScore);

// --- 11. Issue本文を組み立て ---
const hypothesesList = newHypotheses.length > 0
  ? newHypotheses
      .sort((a, b) => (Number(b.score) || 0) - (Number(a.score) || 0))
      .map(h => {
        const badge = h.recommended === true || h.recommended === 'true' ? ' ⭐推奨' : '';
        const score = h.score ? ` [${h.score}/50]` : '';
        return `- **${h.name}**${score}${badge} (${h.solution_type}) — ${h.summary}`;
      }).join('\n')
  : '_（サマリー抽出なし）_';

// JSONブロックを本文から除去（Issue上では不要）
let bodyWithoutJson = content
  .replace(/```json\s*\n[\s\S]*?\n```/, '')
  .replace(/```structured_attrs\s*\n[\s\S]*?\n```/, '')
  .trim();

// 関連Issue情報を追加
if (classification.action === 'create_issue_with_relation' && classification.similar_to.length > 0) {
  bodyWithoutJson += '\n\n## 関連Issue（自動検出）\n' +
    classification.similar_to.map(s =>
      `- #${s.id} ${s.title} (類似度 ${(s.score * 100).toFixed(0)}%)`
    ).join('\n');
}

const scorePrefix = mirukarteScore != null ? `【適合度${mirukarteScore}】` : '';
const issueTitle = `${scorePrefix}${newHypotheses.map(h => h.name).join(' / ') || '調査レポート'} (${today})`;

const issueBody = [
  `> テーマ: **${todayTheme}** | ドメイン: ${domainId} | スポーク: ${spokeId} | ${today}`,
  '',
  '## 仮説サマリー',
  '',
  hypothesesList,
  '',
  '---',
  '',
  bodyWithoutJson,
  '',
  '---',
  '',
  `_生成: DeepSeek Chat | tokens: in=${usage?.prompt_tokens} out=${usage?.completion_tokens} | 重複スキップ: ${skippedCount}件 | 類似度: ${classification.tag}_`,
].join('\n');

console.log('\n' + '='.repeat(60));
console.log(issueTitle);
console.log('='.repeat(60));

if (dryRun) {
  console.log('(dry run: Issue投稿・メール送信・履歴保存をスキップ)');
  console.log('\n--- Issue body (first 1000 chars) ---');
  console.log(issueBody.slice(0, 1000));
  console.log(`\n--- 構造化属性 ---`);
  console.log(JSON.stringify(structuredAttrs, null, 2));
  console.log(`\n--- 類似度判定 ---`);
  console.log(JSON.stringify(classification, null, 2));
  console.log(`\n--- メタ情報 ---`);
  console.log(`ミルカルテ適合度: ${mirukarteScore}/10`);
  console.log(`スポーク: ${spokeId}`);
  console.log(`推奨アクション: ${recommendedAction}`);
  process.exit(0);
}

// --- 12. GitHub Issueに投稿 ---
writeFileSync('/tmp/ideation_issue.md', issueBody);

const labels = [
  'research',
  `spoke:${spokeId}`,
  `domain:${domainId}`,
  `tag:${classification.tag}`,
];

// ラベルを作成（存在しなければ）
for (const label of labels) {
  try { gh(`label create "${label}" --repo ${REPO} --color 0E8A16 --description "" 2>/dev/null`); } catch {}
}

const labelArg = labels.map(l => `--label "${l}"`).join(' ');
let issueUrl;
let issueNumber;
try {
  issueUrl = gh(`issue create --repo ${REPO} --title "${issueTitle.replace(/"/g, '\\"')}" --body-file /tmp/ideation_issue.md ${labelArg}`);
  console.log(`Issue作成: ${issueUrl}`);
  // URLからIssue番号を抽出
  const numMatch = issueUrl.match(/\/issues\/(\d+)/);
  issueNumber = numMatch ? numMatch[1] : null;
} catch (e) {
  console.error('Issue作成に失敗:', e.message);
  process.exit(1);
}

// --- 13. メールでIssue URLを通知 ---
if (process.env.GMAIL_USERNAME && process.env.GMAIL_APP_PASSWORD) {
  const transporter = createTransport({
    host: 'smtp.gmail.com',
    port: 465,
    secure: true,
    auth: {
      user: process.env.GMAIL_USERNAME,
      pass: process.env.GMAIL_APP_PASSWORD,
    },
  });

  const similarInfo = classification.similar_to.length > 0
    ? `  └ 関連Issue: ${classification.similar_to.map(s => `#${s.id} "${s.title}" (類似度${(s.score * 100).toFixed(0)}%)`).join(', ')}`
    : '';

  const emailSubject = `【事業アイデア】${scorePrefix}${todayTheme} (${today})`;
  const emailBody = [
    `■ ミルカルテ適合度: ${mirukarteScore ?? '---'}/10点`,
    `■ 帰属スポーク: ${spokeId}`,
    `■ 推奨アクション: ${recommendedAction}`,
    `■ 類似度判定: ${classification.tag}`,
    similarInfo,
    '',
    `---`,
    '',
    `本日の新規事業調査レポートです。`,
    '',
    `テーマ: ${todayTheme}`,
    `ドメイン: ${domainId}`,
    `仮説: ${newHypotheses.map(h => h.name).join(' / ') || 'レポート参照'}`,
    '',
    `▼ レポートを読む`,
    issueUrl,
  ].join('\n');

  await transporter.sendMail({
    from: `事業アイデアbot <${process.env.GMAIL_USERNAME}>`,
    to: process.env.GMAIL_USERNAME,
    subject: emailSubject,
    text: emailBody,
  });

  console.log('メール通知を送信しました。');
} else {
  console.log('GMAIL環境変数が未設定のためメール送信をスキップ。');
}

// --- 14. 履歴保存 ---
// 従来のフラット履歴
const newEntry = {
  date: today,
  theme: todayTheme,
  domainId,
  spokeId,
  hash: contentHash,
  summary: newHypotheses.map(h => h.summary).join(' / ') || content.slice(0, 200),
  hypothesisNames: newHypotheses.map(h => h.name),
  mirukarteScore,
  issueUrl,
  tokens: { input: usage?.prompt_tokens, output: usage?.completion_tokens },
};

history.push(newEntry);

// 直近180日分だけ保持
const cutoff = new Date();
cutoff.setDate(cutoff.getDate() - 180);
const cutoffStr = cutoff.toISOString().slice(0, 10);
const trimmed = history.filter(h => h.date >= cutoffStr);

writeFileSync(dir + 'results_history.json', JSON.stringify(trimmed, null, 2) + '\n');

// 構造化履歴を個別JSONファイルとして保存
if (structuredAttrs && issueNumber) {
  mkdirSync(historyDir, { recursive: true });
  const historyEntry = {
    id: issueNumber,
    title: newHypotheses.map(h => h.name).join(' / ') || todayTheme,
    generated_at: new Date().toISOString(),
    domain_id: domainId,
    spoke_id: spokeId,
    mirukarte_score: mirukarteScore,
    structured_attrs: structuredAttrs,
  };
  writeFileSync(
    historyDir + `${today}-issue-${issueNumber}.json`,
    JSON.stringify(historyEntry, null, 2) + '\n'
  );
  console.log(`構造化履歴を保存: ${today}-issue-${issueNumber}.json`);
}

// ローテーション状態は不要（重み付きランダム選択に移行）
// rotation_state.json は後方互換のため残すが更新は不要

console.log('履歴を保存しました。');
process.exit(0);
