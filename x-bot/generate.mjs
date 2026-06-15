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

// 1. 過去の投稿を取得（重複防止 — 角度サマリー方式）
const posted = readJSON(paths.posted, []);
const queue = readJSON(paths.queue, []);
const recentTexts = posted.slice(-20).map(p => p.text);
const queueTexts = queue.map(q => q.text);
const existingTexts = [...recentTexts, ...queueTexts].map(t => `- ${t}`).join('\n');

// 使用済みの「角度」を抽出してDeepSeekに明示的に禁止する
const allExisting = [...posted.slice(-20), ...queue];
const usedAngles = [...new Set(allExisting.map(p => {
  const t = p.text || '';
  if (t.includes('87.7%') || t.includes('28件') || t.includes('9件')) return '数字: 87.7%/28件/9件';
  if (t.includes('従業員5人')) return '角度: 従業員5人でも対象';
  if (t.includes('あと4ヶ月') || t.includes('あと数ヶ月')) return '角度: 施行まであとXヶ月';
  if (t.includes('研修の証跡、もう残して')) return '角度: 証跡もう残してますか';
  if (t.includes('まだ大丈夫')) return '角度: まだ大丈夫と思ってませんか';
  return null;
}).filter(Boolean))];
const usedAnglesBlock = usedAngles.length > 0
  ? `\n【使い過ぎている角度（これらは絶対に使わないこと）】\n${usedAngles.map(a => `- ${a}`).join('\n')}`
  : '';

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

// 6. キューキャップ: 溢れていたら生成をスキップ
const MAX_QUEUE = config.maxQueueSize || 15;
if (queue.length >= MAX_QUEUE) {
  console.log(`[${slug}] キュー ${queue.length}件 ≥ 上限 ${MAX_QUEUE}件 → 生成スキップ`);
  process.exit(0);
}

// 7. 投稿タイプを動的に選択（最近使っていないタイプを優先）
const ALL_TYPES = ['問題提起', '解決策ヒント', '数字・統計', 'LP誘導', '時事ネタ', '業種別シーン'];
const recentTypes = [...posted.slice(-10), ...queue].map(p => p.type).filter(Boolean);
const typeCounts = {};
for (const t of recentTypes) typeCounts[t] = (typeCounts[t] || 0) + 1;
const sortedTypes = ALL_TYPES.slice().sort((a, b) => (typeCounts[a] || 0) - (typeCounts[b] || 0));
const GENERATE_COUNT = config.generateCount || 3;
const selectedTypes = sortedTypes.slice(0, GENERATE_COUNT);

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
${usedAnglesBlock}

【重複防止の厳守ルール】
- 上記の投稿と同じ数字・同じ切り口・同じ冒頭フレーズの投稿は絶対に生成しない。
- 「使い過ぎている角度」に該当する表現は一切使わない。
- 毎回必ず新しい切り口（具体的な業種シーン、法律の条文、実務のあるある、時事ニュース等）を使うこと。
- 同じ統計データの繰り返しは禁止。別の数字・別のソースを使う。

${generateInstructions ? `【フィードバックからの指示（重要: 必ず従うこと）】\n${generateInstructions}` : ''}`;

const typeExamples = selectedTypes.map((t, i) => `  { "text": "投稿文${i + 1}", "type": "${t}" }`).join(',\n');
const userPrompt = `今日は${today}です。新しい投稿文を${GENERATE_COUNT}件作成してください。

今回は以下のタイプで書いてください（最近使っていないタイプを優先選定しました）:
${selectedTypes.map((t, i) => `${i + 1}. ${t}`).join('\n')}

以下のJSON形式で出力してください。他の文章は不要です。
[
${typeExamples}
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

// 8. 類似度チェック: 既存投稿と似すぎる生成物を弾く
function bigrams(text) {
  const clean = text.replace(/https?:\/\/\S+/g, '').replace(/[#＃@＠\s]/g, '');
  const set = new Set();
  for (let i = 0; i < clean.length - 1; i++) set.add(clean.slice(i, i + 2));
  return set;
}
function similarity(a, b) {
  const sa = bigrams(a);
  const sb = bigrams(b);
  let overlap = 0;
  for (const g of sa) if (sb.has(g)) overlap++;
  return overlap / Math.max(sa.size, sb.size, 1);
}
const existingTextList = [...recentTexts, ...queueTexts];

// 9. queue.json に追加（X加重文字数バリデーション付き）
// Xの上限は加重280: 日本語等=2, 英数=1, URL=23。超過すると403で投稿失敗しキューが詰まる
function weightedLength(text) {
  const t = text.replace(/https?:\/\/\S+/g, 'U'.repeat(23));
  let n = 0;
  for (const ch of t) {
    n += ch.codePointAt(0) <= 0x10ff ? 1 : 2;
  }
  return n;
}
const WEIGHTED_LIMIT = 280;

const dateTag = today.replace(/-/g, '');
const newEntries = [];
for (let i = 0; i < generated.length; i++) {
  const text = generated[i].text?.trim();
  if (!text) continue;
  const len = weightedLength(text);
  if (len > WEIGHTED_LIMIT) {
    console.warn(`  スキップ: 文字数超過 (加重${len}/${WEIGHTED_LIMIT}) ${text.slice(0, 40)}…`);
    continue;
  }
  // 類似度チェック: 既存と60%以上似ていたら弾く
  const maxSim = Math.max(0, ...existingTextList.map(e => similarity(text, e)));
  if (maxSim > 0.6) {
    console.warn(`  スキップ: 類似度 ${(maxSim * 100).toFixed(0)}% — ${text.slice(0, 40)}…`);
    continue;
  }
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
