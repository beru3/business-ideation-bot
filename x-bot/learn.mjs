// フィードバックループ — メトリクスを分析し、次回の生成指示を出力
//   node learn.mjs   … 全アカウントのメトリクスを分析
//
// 環境変数: DEEPSEEK_API_KEY
import OpenAI from 'openai';
import { listAccounts, readJSON, writeJSON } from './lib/context.mjs';
import { readFileSync } from 'node:fs';
import { join, fileURLToPath } from 'node:path';

const ROOT = join(fileURLToPath(import.meta.url), '..');

if (!process.env.DEEPSEEK_API_KEY) {
  console.error('環境変数が未設定: DEEPSEEK_API_KEY');
  process.exit(1);
}

const ai = new OpenAI({
  baseURL: 'https://api.deepseek.com',
  apiKey: process.env.DEEPSEEK_API_KEY,
});

const accounts = listAccounts();
if (accounts.length === 0) {
  console.log('アカウントが見つかりません。');
  process.exit(0);
}

const learningsPath = join(ROOT, 'shared', 'learnings.json');
const learnings = readJSON(learningsPath, { updated_at: null, accounts: {} });

for (const slug of accounts) {
  console.log(`\n=== [${slug}] 学習分析 ===`);

  const historyPath = join(ROOT, 'accounts', slug, 'metrics_history.json');
  const history = readJSON(historyPath, []);

  if (history.length === 0) {
    console.log('メトリクス履歴がありません。スキップ。');
    continue;
  }

  // 過去7日間のメトリクスを取得
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 7);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  const recentDays = history.filter(h => h.date >= cutoffStr);

  if (recentDays.length === 0) {
    console.log('直近7日間のデータがありません。スキップ。');
    continue;
  }

  // 全投稿のメトリクスをフラット化
  const allPosts = recentDays.flatMap(d => d.metrics || []);
  if (allPosts.length === 0) {
    console.log('投稿データがありません。スキップ。');
    continue;
  }

  // エンゲージメント率を計算
  const postsWithRate = allPosts.map(p => ({
    ...p,
    engagementRate: p.impressions > 0
      ? ((p.likes + p.retweets + p.replies) / p.impressions * 100)
      : 0,
  }));

  // タイプ別集計
  const typeStats = {};
  for (const p of postsWithRate) {
    const type = p.type || 'unknown';
    if (!typeStats[type]) typeStats[type] = { count: 0, totalImp: 0, totalEng: 0, rates: [] };
    typeStats[type].count++;
    typeStats[type].totalImp += p.impressions;
    typeStats[type].totalEng += p.likes + p.retweets + p.replies;
    typeStats[type].rates.push(p.engagementRate);
  }

  // 上位・下位投稿
  const sorted = [...postsWithRate].sort((a, b) => b.engagementRate - a.engagementRate);
  const top3 = sorted.slice(0, 3);
  const bottom3 = sorted.slice(-3).reverse();

  // DeepSeekで分析
  const analysisPrompt = `以下はXアカウントの過去7日間の投稿パフォーマンスです。

## タイプ別統計
${Object.entries(typeStats).map(([type, s]) => {
    const avgRate = s.rates.reduce((a, b) => a + b, 0) / s.rates.length;
    return `- ${type}: ${s.count}件, avg imp ${Math.round(s.totalImp / s.count)}, avg eng rate ${avgRate.toFixed(1)}%`;
  }).join('\n')}

## 上位3投稿
${top3.map(p => `- [${p.type}] "${p.text}…" imp:${p.impressions} eng:${p.engagementRate.toFixed(1)}%`).join('\n')}

## 下位3投稿
${bottom3.map(p => `- [${p.type}] "${p.text}…" imp:${p.impressions} eng:${p.engagementRate.toFixed(1)}%`).join('\n')}

## フォロワー推移
${recentDays.map(d => `${d.date}: ${d.followerCount || '?'}`).join(', ')}

以下のJSON形式で分析結果を出力してください:
{
  "top_performing_type": "最も反応が良い投稿タイプ",
  "avg_engagement_rate": "全体の平均エンゲージメント率（数値）",
  "best_patterns": ["効いたパターン1", "効いたパターン2"],
  "avoid_patterns": ["避けるべきパターン1", "避けるべきパターン2"],
  "best_hours": [12, 19],
  "generate_instructions": "次回の投稿生成時に従うべき具体的な指示。200文字以内。"
}`;

  try {
    const res = await ai.chat.completions.create({
      model: 'deepseek-chat',
      messages: [
        { role: 'system', content: 'あなたはSNSマーケティングの分析者です。データに基づいた具体的な改善指示を出してください。' },
        { role: 'user', content: analysisPrompt },
      ],
      temperature: 0.3,
      max_tokens: 800,
    });

    const content = res.choices[0].message.content.trim();
    const jsonStr = content.replace(/^```json?\s*\n?/m, '').replace(/\n?```\s*$/m, '');
    const analysis = JSON.parse(jsonStr);

    learnings.accounts[slug] = {
      ...analysis,
      analyzed_at: new Date().toISOString(),
      posts_analyzed: allPosts.length,
      type_stats: typeStats,
    };

    console.log(`分析完了:`);
    console.log(`  トップタイプ: ${analysis.top_performing_type}`);
    console.log(`  平均eng rate: ${analysis.avg_engagement_rate}%`);
    console.log(`  生成指示: ${analysis.generate_instructions}`);
  } catch (e) {
    console.error(`[${slug}] 分析失敗:`, e.message);
  }
}

learnings.updated_at = new Date().toISOString();
writeJSON(learningsPath, learnings);
console.log(`\nlearnings.json を更新しました。`);
