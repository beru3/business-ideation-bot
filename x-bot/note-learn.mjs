// note記事 分析 — メトリクスを分析し、次回の記事戦略を出力
//   node note-learn.mjs
//
// 環境変数: DEEPSEEK_API_KEY
// 入力: x-bot/accounts/*/note_metrics.json, note_posted.json, bot/validate_input.json
// 出力: x-bot/shared/learnings.json (note_articles セクション)
import OpenAI from 'openai';
import { listAccounts, readJSON, writeJSON } from './lib/context.mjs';
import { join, fileURLToPath } from 'node:path';
import { readFileSync, existsSync } from 'node:fs';

const ROOT = join(fileURLToPath(import.meta.url), '..');
const PROJECT_ROOT = join(ROOT, '..');

// ナレッジ496件をロード（存在する場合のみ）
const knowledgePath = join(PROJECT_ROOT, 'bot', 'validate_input.json');
let knowledgeInsights = [];
if (existsSync(knowledgePath)) {
  try {
    const raw = JSON.parse(readFileSync(knowledgePath, 'utf8'));
    knowledgeInsights = Array.isArray(raw) ? raw : (raw.insights || raw.data || []);
    console.log(`ナレッジ ${knowledgeInsights.length} 件をロード`);
  } catch (e) {
    console.warn('ナレッジ読み込みスキップ:', e.message);
  }
}

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
  const metricsPath = join(ROOT, 'accounts', slug, 'note_metrics.json');
  const postedPath = join(ROOT, 'accounts', slug, 'note_posted.json');
  const metrics = readJSON(metricsPath, []);
  const posted = readJSON(postedPath, []);

  if (metrics.length < 2) {
    console.log(`[${slug}] noteメトリクスが2週分未満。分析にはもう1週間待ってください。`);
    continue;
  }

  console.log(`\n=== [${slug}] note記事 分析 ===`);

  const latest = metrics[metrics.length - 1];
  const prev = metrics[metrics.length - 2];

  // 記事ごとの成長率を計算（ナレッジIDも紐付け）
  const articleGrowth = latest.articles.map(a => {
    const prevArticle = prev.articles.find(p => p.noteId === a.noteId);
    const pvGrowth = prevArticle ? a.pv - prevArticle.pv : a.pv;
    const likeGrowth = prevArticle ? a.likes - prevArticle.likes : a.likes;
    const postedEntry = posted.find(p => p.noteUrl === a.url);
    return {
      title: a.title,
      url: a.url,
      totalPv: a.pv,
      totalLikes: a.likes,
      weeklyPvGrowth: pvGrowth,
      weeklyLikeGrowth: likeGrowth,
      type: postedEntry?.type || 'unknown',
      knowledgeIds: postedEntry?.knowledgeIds || [],
    };
  });

  // PV成長率でソート
  const sorted = [...articleGrowth].sort((a, b) => b.weeklyPvGrowth - a.weeklyPvGrowth);

  // ナレッジからトップ記事に関連するインサイトを抽出
  const topArticleTitle = sorted[0]?.title || '';
  let knowledgeSection = '';
  if (knowledgeInsights.length > 0) {
    // 記事に紐付いたナレッジIDを収集
    const usedIds = new Set(articleGrowth.flatMap(a => a.knowledgeIds));
    const usedInsights = knowledgeInsights
      .filter(k => usedIds.has(String(k.id)) || usedIds.has(`ID#${k.id}`))
      .slice(0, 10);

    // SEO/コンテンツ関連のナレッジも上位5件抽出
    const seoInsights = knowledgeInsights
      .filter(k => {
        const text = `${k.title || ''} ${k.insight || ''} ${k.tags || ''}`.toLowerCase();
        return text.includes('seo') || text.includes('タイトル') || text.includes('コンテンツ')
          || text.includes('記事') || text.includes('見出し') || text.includes('cta');
      })
      .slice(0, 5);

    if (usedInsights.length > 0 || seoInsights.length > 0) {
      knowledgeSection = `\n## 適用済みナレッジインサイト（マーケティング侍由来）\n`;
      if (usedInsights.length > 0) {
        knowledgeSection += `### 記事に適用済み\n${usedInsights.map(k => `- ID#${k.id}: ${k.insight || k.title || ''}`).join('\n')}\n`;
      }
      knowledgeSection += `### SEO/コンテンツ関連ナレッジ（参考）\n${seoInsights.map(k => `- ID#${k.id}: ${k.insight || k.title || ''}`).join('\n')}\n`;
      knowledgeSection += `\nこれらのナレッジのうち、PV上位記事に効いていると推定されるIDを effective_knowledge_ids に含めてください。\n`;
    }
  }

  const analysisPrompt = `以下はnoteアカウントの記事パフォーマンスです（週次比較）。

## 全体サマリー
- 総PV: ${latest.total_pv}（前週比: +${latest.total_pv - prev.total_pv}）
- 総スキ: ${latest.total_likes}（前週比: +${latest.total_likes - prev.total_likes}）
- 記事数: ${latest.articles.length}本

## 記事別パフォーマンス（週次PV増分順）
${sorted.map(a => {
    const kIds = a.knowledgeIds.length > 0 ? ` [知識:${a.knowledgeIds.join(',')}]` : '';
    return `- "${a.title}" [${a.type}] PV:${a.totalPv}(+${a.weeklyPvGrowth}) スキ:${a.totalLikes}(+${a.weeklyLikeGrowth})${kIds}`;
  }).join('\n')}
${knowledgeSection}
## コンテキスト
- ターゲット: 法務部がない中小企業の経営者・管理部門
- 目的: SEO流入 → LP → リード獲得
- 競合: freee法対応ガイド、大手法務メディア

以下のJSON形式で分析結果を出力してください:
{
  "top_article": "最もPV成長が高い記事タイトル",
  "top_article_reason": "なぜこの記事が伸びているか（推定）",
  "underperforming": "最もPV成長が低い記事タイトル",
  "underperforming_fix": "この記事を改善する具体的なアクション",
  "next_topics": ["次に書くべき記事テーマ3つ（既存記事の成功パターンを踏まえて）"],
  "title_pattern": "効いているタイトルの共通パターン",
  "content_instructions": "次回の記事執筆時に従うべき具体的な指示。200文字以内。",
  "effective_knowledge_ids": ["PV上位記事に効いていると推定されるナレッジID（例: ID#1311）"],
  "ineffective_patterns": "効いていない記事の共通パターン（避けるべき）"
}`;

  try {
    const res = await ai.chat.completions.create({
      model: 'deepseek-chat',
      messages: [
        { role: 'system', content: 'あなたはSEO・コンテンツマーケティングの分析者です。noteの記事パフォーマンスを分析し、次の記事戦略を提案してください。' },
        { role: 'user', content: analysisPrompt },
      ],
      temperature: 0.3,
      max_tokens: 1200,
    });

    const content = res.choices[0].message.content.trim();
    const jsonStr = content.replace(/^```json?\s*\n?/m, '').replace(/\n?```\s*$/m, '');
    const analysis = JSON.parse(jsonStr);

    // learnings.json に note_articles セクションとして保存
    if (!learnings.accounts[slug]) learnings.accounts[slug] = {};
    learnings.accounts[slug].note_articles = {
      ...analysis,
      analyzed_at: new Date().toISOString(),
      articles_analyzed: latest.articles.length,
      total_pv: latest.total_pv,
      total_likes: latest.total_likes,
      weekly_pv_growth: latest.total_pv - prev.total_pv,
    };

    console.log('分析完了:');
    console.log(`  トップ記事: ${analysis.top_article}`);
    console.log(`  理由: ${analysis.top_article_reason}`);
    console.log(`  次のテーマ: ${analysis.next_topics.join(', ')}`);
    console.log(`  執筆指示: ${analysis.content_instructions}`);
    if (analysis.effective_knowledge_ids?.length > 0) {
      console.log(`  効いたナレッジ: ${analysis.effective_knowledge_ids.join(', ')}`);
    }
  } catch (e) {
    console.error(`[${slug}] 分析失敗:`, e.message);
  }
}

learnings.updated_at = new Date().toISOString();
writeJSON(learningsPath, learnings);
console.log('\nlearnings.json を更新しました。');
