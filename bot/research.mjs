// 新規事業アイデア自動調査bot
//   node research.mjs        … 調査実行 → メール送信 → 履歴保存
//   node research.mjs --dry  … 調査のみ（メール送信・履歴保存なし）
//
// 必要な環境変数:
//   DEEPSEEK_API_KEY
//   GMAIL_USERNAME, GMAIL_APP_PASSWORD
import OpenAI from 'openai';
import { createTransport } from 'nodemailer';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

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

## 出力ルール
- 「気合」「成熟した」のような曖昧な根拠は禁止
- 「ブランド」「UX」だけを堀として主張しない
- 実行レイヤーまで含む解法にする（分析・可視化だけで終わらない）
- 日本市場を前提とする`;

const userPrompt = `今日は${today}です。

【調査テーマ】${todayTheme}

このテーマで、過去に失敗したアプリ・サービス・スタートアップを起点に、現代で再起動可能な新規事業の機会仮説を生成してください。

上記パイプライン（Step 1〜4）に沿って分析し、最後に以下のJSON形式で仮説サマリーを出力してください（本文の分析の後に追記）。

\`\`\`json
{
  "theme": "${todayTheme}",
  "hypotheses": [
    {
      "name": "仮説の短い名前",
      "origin_failure": "起点となった失敗事業名",
      "summary": "1-2文の仮説サマリー",
      "change_factor": "変化要因（1-5のいずれか）",
      "solution_type": "SaaS/アプリ/API等"
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
  temperature: 0.85,
  max_tokens: 4000,
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
    console.warn('JSONサマリーのパース失敗（本文レポートは送信します）:', e.message);
  }
}

// 仮説名の重複チェック（過去の同テーマ結果と比較）
const pastNames = new Set(
  history.filter(h => h.theme === todayTheme).flatMap(h => h.hypothesisNames || [])
);
const newHypotheses = hypotheses.filter(h => !pastNames.has(h.name));
const skippedCount = hypotheses.length - newHypotheses.length;

if (skippedCount > 0) {
  console.log(`仮説${skippedCount}件が過去と重複のためスキップ`);
}

if (newHypotheses.length === 0 && hypotheses.length > 0) {
  console.log('全仮説が重複のためメール送信をスキップ。');
  process.exit(0);
}

console.log(`新規仮説: ${newHypotheses.length}件`);

// --- 6. レポート出力 ---
const subjectLine = `【事業アイデア】${todayTheme} - ${newHypotheses.map(h => h.name).join(' / ') || '調査レポート'}`;

console.log('\n' + '='.repeat(60));
console.log(subjectLine);
console.log('='.repeat(60));
console.log(content.slice(0, 500) + '…\n');

if (dryRun) {
  console.log('(dry run: メール送信・履歴保存をスキップ)');
  console.log('\n--- Full content ---');
  console.log(content);
  process.exit(0);
}

// --- 7. Gmail送信 ---
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

  const emailBody = [
    `新規事業アイデア調査レポート（${today}）`,
    `テーマ: ${todayTheme}`,
    `サイクル: ${cycleNum + 1}巡目`,
    '',
    '─'.repeat(40),
    '',
    content,
    '',
    '─'.repeat(40),
    '',
    `生成モデル: DeepSeek Chat`,
    `トークン: input=${usage?.prompt_tokens}, output=${usage?.completion_tokens}`,
    `重複スキップ: ${skippedCount}件`,
  ].join('\n');

  await transporter.sendMail({
    from: `事業アイデアbot <${process.env.GMAIL_USERNAME}>`,
    to: process.env.GMAIL_USERNAME,
    subject: subjectLine,
    text: emailBody,
  });

  console.log('Gmailにレポートを送信しました。');
} else {
  console.log('GMAIL環境変数が未設定のためメール送信をスキップ。');
}

// --- 8. 履歴保存 ---
const newEntry = {
  date: today,
  theme: todayTheme,
  hash: contentHash,
  summary: newHypotheses.map(h => h.summary).join(' / ') || content.slice(0, 200),
  hypothesisNames: newHypotheses.map(h => h.name),
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
