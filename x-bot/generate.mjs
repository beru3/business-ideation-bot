// X投稿文の自動生成
//   node generate.mjs --account aio-checker
//
// 環境変数: {PREFIX}_X_*, DEEPSEEK_API_KEY
import OpenAI from 'openai';
import { loadContext, readJSON, writeJSON } from './lib/context.mjs';
import { join } from 'node:path';

const ctx = loadContext();
const { config, paths, slug } = ctx;

if (!process.env.DEEPSEEK_API_KEY) {
  console.error('環境変数が未設定: DEEPSEEK_API_KEY');
  process.exit(1);
}

const ai = new OpenAI({
  baseURL: 'https://api.deepseek.com',
  apiKey: process.env.DEEPSEEK_API_KEY,
});

// 1. 過去の投稿を取得（重複防止）
const posted = readJSON(paths.posted, []);
const queue = readJSON(paths.queue, []);
const recentTexts = posted.slice(-20).map(p => p.text);
const queueTexts = queue.map(q => q.text);
const existingTexts = [...recentTexts, ...queueTexts].map(t => `- ${t}`).join('\n');

// 2. learnings.json からフィードバック指示を取得
const learnings = readJSON(paths.learnings, {});
const accountLearnings = learnings.accounts?.[slug] || {};
const generateInstructions = accountLearnings.generate_instructions || '';

// 3. ブリーフ情報を読み込み
const repoRoot = join(ctx.root, '..');
const brief = readJSON(join(repoRoot, config.briefPath), {});

// 4. ナレッジインサイトから関連知見を抽出
const knowledgePath = join(repoRoot, 'bot', 'validate_input.json');
const knowledgeData = readJSON(knowledgePath, {});
const allInsights = knowledgeData.knowledge_insights || [];

function scoreInsight(insight) {
  const searchFields = [
    insight.target_who || '',
    insight.target_industry || '',
    insight.pain_point || '',
    insight.automation_opportunity || '',
    insight.market_hint || '',
    ...(insight.tags || []),
  ].join(' ').toLowerCase();

  const keywords = [
    ...(config.hashtags || []).map(h => h.replace('#', '')),
    ...(config.persona || '').split(/[、。\s]+/),
    ...(config.targetPersona || '').split(/[、。\s]+/),
    ...(brief.pain_statement || '').split(/[、。\s]+/),
  ].filter(k => k.length >= 2).map(k => k.toLowerCase());

  let score = 0;
  for (const kw of keywords) {
    if (searchFields.includes(kw)) score++;
  }
  return score;
}

const scoredInsights = allInsights
  .map(i => ({ ...i, _score: scoreInsight(i) }))
  .filter(i => i._score > 0)
  .sort((a, b) => b._score - a._score)
  .slice(0, 10);

const knowledgeBlock = scoredInsights.length > 0
  ? scoredInsights.map(i =>
    `- [ID:${i.id}] ペイン: ${i.pain_point || ''} → 機会: ${i.automation_opportunity || ''} (${(i.tags || []).join(', ')})`
  ).join('\n')
  : '';

console.log(`[${slug}] ナレッジ: ${allInsights.length}件中${scoredInsights.length}件を関連知見として抽出`);

// 6. DeepSeekで投稿文を生成
const GENERATE_COUNT = config.generateCount || 3;
const today = new Date().toISOString().slice(0, 10);

const systemPrompt = `あなたはXアカウント「${config.account}」の投稿文を作成するライターです。

【ペルソナ】
${config.persona}

【ターゲット】
${config.targetPersona || brief.target_persona || ''}

【投稿ルール】
- 1投稿は140文字以内（日本語）。Xの文字数制限に収まること。
- ハッシュタグは1-2個まで: ${(config.hashtags || []).join(', ')}
- 問いかけ・データ・時事ネタを活用する。
- 投稿タイプを混ぜる: 問題提起 / 解決策ヒント / 数字・統計 / LP誘導 / スレッド
- LP誘導投稿は${GENERATE_COUNT}件中1件程度。URL: ${config.lpUrl || ''}
- リンク付き投稿は、リンクなしでも意味が通じる文章にする（リンクは自動でリプライに分離）。
- 禁止: 政治、災害、攻撃的表現、他社サービス批判

【マーケブリーフの訴求ポイント】
- 痛み: ${brief.pain_statement || ''}
- 差別化: ${brief.differentiator || ''}
- CTA: ${brief.cta_design || ''}
- 価格: ${brief.pricing_hint || ''}
${(brief.knowledge_backed_tactics || []).length > 0 ? `- ナレッジ由来の戦術:\n${brief.knowledge_backed_tactics.map(t => `  - ${t}`).join('\n')}` : ''}

${knowledgeBlock ? `【マーケティングナレッジ（投稿の訴求角度・表現に活かすこと）】\n${knowledgeBlock}` : ''}

【過去の投稿・キュー内の投稿（重複しないこと）】
${existingTexts || '（なし）'}

${generateInstructions ? `【フィードバックからの指示（重要: 必ず従うこと）】\n${generateInstructions}` : ''}`;

const userPrompt = `今日は${today}です。新しい投稿文を${GENERATE_COUNT}件作成してください。

以下のJSON形式で出力してください。他の文章は不要です。
[
  { "text": "投稿文1", "type": "問題提起" },
  { "text": "投稿文2", "type": "数字・統計" },
  { "text": "投稿文3", "type": "LP誘導" }
]`;

console.log(`[${slug}] DeepSeek APIで${GENERATE_COUNT}件の投稿文を生成中…`);

const response = await ai.chat.completions.create({
  model: 'deepseek-chat',
  messages: [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: userPrompt },
  ],
  temperature: 0.8,
  max_tokens: 1500,
});

const content = response.choices[0].message.content.trim();

// 7. JSONパース
let generated;
try {
  const jsonStr = content.replace(/^```json?\s*\n?/m, '').replace(/\n?```\s*$/m, '');
  generated = JSON.parse(jsonStr);
} catch (e) {
  console.error('JSONパースに失敗:', e.message);
  console.error('raw:', content);
  process.exit(1);
}

if (!Array.isArray(generated) || generated.length === 0) {
  console.error('生成結果が空です');
  process.exit(1);
}

// 8. queue.json に追加
const dateTag = today.replace(/-/g, '');
const newEntries = [];
for (let i = 0; i < generated.length; i++) {
  const text = generated[i].text?.trim();
  if (!text) continue;
  const entry = {
    id: `auto-${dateTag}-${i + 1}`,
    text,
    type: generated[i].type || 'unknown',
    generatedAt: new Date().toISOString(),
  };
  queue.push(entry);
  newEntries.push(entry);
  console.log(`  生成: [${entry.id}] (${entry.type}) ${text.slice(0, 60)}…`);
}

writeJSON(paths.queue, queue);
console.log(`\n[${slug}] ${newEntries.length}件をキューに追加（キュー合計: ${queue.length}件）`);
