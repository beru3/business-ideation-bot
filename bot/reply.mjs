// Issue コメントに対してDeepSeek AIで返信するスクリプト
//
// 環境変数:
//   DEEPSEEK_API_KEY
//   GH_TOKEN
//   ISSUE_NUMBER
//   ISSUE_BODY
//   COMMENT_BODY
//   COMMENT_USER
//   REPO (owner/repo)
import OpenAI from 'openai';
import { execSync } from 'node:child_process';

const { DEEPSEEK_API_KEY, ISSUE_NUMBER, ISSUE_BODY, COMMENT_BODY, COMMENT_USER, REPO } = process.env;

if (!DEEPSEEK_API_KEY || !ISSUE_NUMBER || !COMMENT_BODY) {
  console.error('必要な環境変数が不足しています');
  process.exit(1);
}

const ai = new OpenAI({
  baseURL: 'https://api.deepseek.com',
  apiKey: DEEPSEEK_API_KEY,
});

const gh = (args) => execSync('gh ' + args, { encoding: 'utf8' }).trim();

// --- 1. 過去のコメントを会話履歴として取得 ---
let comments = [];
try {
  const raw = gh(`api repos/${REPO}/issues/${ISSUE_NUMBER}/comments --jq '[.[] | {user: .user.login, body: .body}]'`);
  comments = JSON.parse(raw);
} catch {
  console.warn('コメント履歴の取得に失敗（初回コメントの可能性）');
}

// 直近10件に制限（コンテキスト節約）
const recentComments = comments.slice(-10);

// --- 2. 会話を構築 ---
const systemPrompt = `あなたは新規事業の機会仮説について深掘り議論をするアドバイザーです。

以下はGitHub Issueに投稿された調査レポートです。ユーザーがコメントで質問や深掘りを求めてきたら、レポートの内容を踏まえて具体的に回答してください。

## 回答ルール
- レポートの内容に基づいて回答すること
- 曖昧な回答は避け、数字・事例・具体的なアクションで答えること
- 質問の意図を汲み取り、必要なら追加の分析や代替案を提示すること
- 日本市場を前提とすること
- Markdown形式で読みやすく構造化すること
- 簡潔に回答すること（冗長にしない）`;

const messages = [
  { role: 'system', content: systemPrompt },
  { role: 'user', content: `【調査レポート（Issue本文）】\n\n${ISSUE_BODY}` },
];

// 過去のコメントを会話履歴として追加（最新コメントは除く＝これから回答する分）
for (const c of recentComments.slice(0, -1)) {
  const isBot = c.user === 'github-actions[bot]';
  messages.push({
    role: isBot ? 'assistant' : 'user',
    content: c.body,
  });
}

// 最新のユーザーコメント
messages.push({ role: 'user', content: COMMENT_BODY });

// --- 3. DeepSeek APIで回答生成 ---
console.log(`Issue #${ISSUE_NUMBER} のコメントに返信中…`);
console.log(`質問者: ${COMMENT_USER}`);
console.log(`質問: ${COMMENT_BODY.slice(0, 100)}…`);

const response = await ai.chat.completions.create({
  model: 'deepseek-chat',
  messages,
  temperature: 0.7,
  max_tokens: 4000,
});

const reply = response.choices[0].message.content.trim();
const usage = response.usage;
console.log(`トークン: input=${usage?.prompt_tokens}, output=${usage?.completion_tokens}`);

// --- 4. コメントとして投稿 ---
const footer = `\n\n---\n_AI回答 (DeepSeek Chat) | tokens: in=${usage?.prompt_tokens} out=${usage?.completion_tokens}_`;
const fullReply = reply + footer;

// 一時ファイル経由で投稿（特殊文字対策）
const { writeFileSync } = await import('node:fs');
writeFileSync('/tmp/ai_reply.md', fullReply);

gh(`issue comment ${ISSUE_NUMBER} --repo ${REPO} --body-file /tmp/ai_reply.md`);
console.log(`返信を投稿しました（Issue #${ISSUE_NUMBER}）`);
