// 新規事業アイデア自動調査bot
//   node research.mjs        … 調査実行 → Issue投稿 → メール通知 → 履歴保存
//   node research.mjs --dry  … 調査のみ（Issue投稿・メール送信・履歴保存なし）
//
// 必要な環境変数:
//   DEEPSEEK_API_KEY
//   GH_TOKEN（Issue作成用）
//   GMAIL_USERNAME, GMAIL_APP_PASSWORD（メール通知用）
import OpenAI from 'openai';
import { createTransport } from 'nodemailer';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { execSync } from 'node:child_process';

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

// --- 1. テーマ選択（ローテーション） ---
const themes = JSON.parse(readFileSync(dir + 'themes.json', 'utf8'));
const state = JSON.parse(readFileSync(dir + 'rotation_state.json', 'utf8'));

const nextIndex = (state.lastIndex + 1) % themes.length;
const todayTheme = themes[nextIndex];
const cycleNum = nextIndex === 0 && state.lastIndex >= 0
  ? state.completedCycles + 1
  : state.completedCycles;

console.log(`テーマ: ${todayTheme} (${nextIndex + 1}/${themes.length}, cycle ${cycleNum})`);

// --- 2. 過去の結果を取得（重複判定用） ---
const history = JSON.parse(readFileSync(dir + 'results_history.json', 'utf8'));
const pastHashes = new Set(history.map(h => h.hash));
const pastSummaries = history
  .filter(h => h.theme === todayTheme)
  .slice(-3)
  .map(h => h.summary);

const avoidText = pastSummaries.length > 0
  ? `\n\n【過去にこのテーマで出した仮説（重複しないこと）】\n${pastSummaries.map(s => `- ${s}`).join('\n')}`
  : '';

// --- 3. プロンプト構築 ---
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

このテーマで、過去に失敗したアプリ・サービス・スタートアップを起点に、現代で再起動可能な新規事業の機会仮説を生成してください。

上記パイプライン（Step 1〜5）に沿って分析し、最後に以下のJSON形式で仮説サマリーを出力してください（本文の分析の後に追記）。

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
      "falsification_test": "最小反証実験の概要（1文）"
    }
  ]
}
\`\`\`${avoidText}`;

// --- 4. DeepSeek APIで調査実行 ---
console.log('DeepSeek APIで調査実行中…');

const response = await ai.chat.completions.create({
  model: 'deepseek-chat',
  messages: [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: userPrompt },
  ],
  temperature: 0.7,
  max_tokens: 8000,
});

const content = response.choices[0].message.content.trim();
const usage = response.usage;
console.log(`トークン: input=${usage?.prompt_tokens}, output=${usage?.completion_tokens}`);

// --- 5. 重複判定 ---
const contentHash = createHash('sha256').update(content).digest('hex').slice(0, 16);

if (pastHashes.has(contentHash)) {
  console.log('完全重複のためスキップ。');
  process.exit(0);
}

// JSONサマリーを抽出
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

// 仮説名の重複チェック（類似度ベース: トークン重複率50%以上で重複とみなす）
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

// --- 6. Issue本文を組み立て ---
const hypothesesList = newHypotheses.length > 0
  ? newHypotheses.map(h => `- **${h.name}** (${h.solution_type}) — ${h.summary}`).join('\n')
  : '_（サマリー抽出なし）_';

// JSONブロックを本文から除去（Issue上では不要）
const bodyWithoutJson = content.replace(/```json\s*\n[\s\S]*?\n```/, '').trim();

const issueBody = [
  `> テーマ: **${todayTheme}** | ${cycleNum + 1}巡目 | ${today}`,
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
  `_生成: DeepSeek Chat | tokens: in=${usage?.prompt_tokens} out=${usage?.completion_tokens} | 重複スキップ: ${skippedCount}件_`,
].join('\n');

const issueTitle = `【${todayTheme}】${newHypotheses.map(h => h.name).join(' / ') || '調査レポート'} (${today})`;

console.log('\n' + '='.repeat(60));
console.log(issueTitle);
console.log('='.repeat(60));

if (dryRun) {
  console.log('(dry run: Issue投稿・メール送信・履歴保存をスキップ)');
  console.log('\n--- Issue body ---');
  console.log(issueBody);
  process.exit(0);
}

// --- 7. GitHub Issueに投稿 ---
writeFileSync('/tmp/ideation_issue.md', issueBody);

const labelArg = `--label "research"`;
let issueUrl;
try {
  // ラベルが無い場合に備えて作成（既にあればスキップ）
  try { gh(`label create research --repo ${REPO} --color 0E8A16 --description "自動調査レポート" 2>/dev/null`); } catch {}

  issueUrl = gh(`issue create --repo ${REPO} --title "${issueTitle.replace(/"/g, '\\"')}" --body-file /tmp/ideation_issue.md ${labelArg}`);
  console.log(`Issue作成: ${issueUrl}`);
} catch (e) {
  console.error('Issue作成に失敗:', e.message);
  process.exit(1);
}

// --- 8. メールでIssue URLを通知 ---
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

  const emailSubject = `【事業アイデア】${todayTheme} (${today})`;
  const emailBody = [
    `本日の新規事業調査レポートです。`,
    '',
    `テーマ: ${todayTheme}`,
    `仮説: ${newHypotheses.map(h => h.name).join(' / ') || 'レポート参照'}`,
    '',
    `▼ レポートを読む`,
    issueUrl,
    '',
    `---`,
    `${cycleNum + 1}巡目 | ${nextIndex + 1}/${themes.length}テーマ`,
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

// --- 9. 履歴保存 ---
const newEntry = {
  date: today,
  theme: todayTheme,
  hash: contentHash,
  summary: newHypotheses.map(h => h.summary).join(' / ') || content.slice(0, 200),
  hypothesisNames: newHypotheses.map(h => h.name),
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

// ローテーション状態を更新
const newState = {
  lastIndex: nextIndex,
  completedCycles: cycleNum,
  recentThemes: [...state.recentThemes.slice(-9), todayTheme],
};
writeFileSync(dir + 'rotation_state.json', JSON.stringify(newState, null, 2) + '\n');

console.log('履歴を保存しました。');
process.exit(0);
