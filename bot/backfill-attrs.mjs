#!/usr/bin/env node
// 既存IssueのMarkdown本文からDeepSeekで構造化属性を抽出し、bot/history/ に保存
//
// 使い方:
//   node bot/backfill-attrs.mjs --issue 5
//   node bot/backfill-attrs.mjs --all
//
// 環境変数: DEEPSEEK_API_KEY, GH_TOKEN
import OpenAI from 'openai';
import { execSync } from 'node:child_process';
import { writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const dir = fileURLToPath(new URL('./', import.meta.url));
const historyDir = dir + 'history/';
mkdirSync(historyDir, { recursive: true });

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

const args = process.argv.slice(2);
const isAll = args.includes('--all');
const issueArg = args.find((_, i, a) => a[i - 1] === '--issue');

if (!isAll && !issueArg) {
  console.error('使い方: node bot/backfill-attrs.mjs --issue <number> | --all');
  process.exit(1);
}

async function backfillIssue(issueNumber) {
  const filename = `backfill-issue-${issueNumber}.json`;
  const filepath = historyDir + filename;

  if (existsSync(filepath)) {
    console.log(`  Skip: ${filename} already exists`);
    return;
  }

  console.log(`  Fetching Issue #${issueNumber}...`);
  let issueData;
  try {
    issueData = JSON.parse(gh(`issue view ${issueNumber} --repo ${REPO} --json title,body,createdAt,labels`));
  } catch (e) {
    console.error(`  Issue #${issueNumber} の取得に失敗:`, e.message);
    return;
  }

  const prompt = `以下はGitHub Issueに投稿された新規事業調査レポートです。この内容から以下の構造化属性をJSON形式で抽出してください。

語彙は以下の列挙から厳密に選択すること。該当なしの場合は\`other-XXX\`形式で記述。

\`\`\`json
{
  "data_source_type": "unregulated_paper | regulated_format | api_available | none",
  "target_industry": "medical-clinic | dental | pharmacy | acupuncture | visiting-nursing | care-facility | restaurant-individual | retail-individual | other-XXX",
  "revenue_model": "saas-subscription | usage-based | success-fee | b2b2c-bundled | freemium | one-time",
  "value_layer": "visualization | execution | both | platform",
  "regulation_level": "high-medical | medium-financial | low-general"
}
\`\`\`

また、ミルカルテ適合度スコア（10点満点+ボーナス1点）も算出してください。

出力は以下のJSON形式のみ（説明不要）:
\`\`\`json
{
  "structured_attrs": { ... },
  "mirukarte_score": X.X
}
\`\`\`

---

# Issue #${issueNumber}: ${issueData.title}

${issueData.body.slice(0, 8000)}`;

  console.log(`  DeepSeek APIで属性抽出中...`);
  const response = await ai.chat.completions.create({
    model: 'deepseek-chat',
    messages: [{ role: 'user', content: prompt }],
    temperature: 0.3,
    max_tokens: 1000,
  });

  const content = response.choices[0].message.content.trim();
  const jsonMatch = content.match(/```json\s*\n([\s\S]*?)\n```/) || content.match(/\{[\s\S]*\}/);

  if (!jsonMatch) {
    console.error(`  Issue #${issueNumber}: JSON抽出失敗`);
    return;
  }

  let extracted;
  try {
    const raw = jsonMatch[1] || jsonMatch[0];
    extracted = JSON.parse(raw);
  } catch (e) {
    console.error(`  Issue #${issueNumber}: JSONパース失敗:`, e.message);
    return;
  }

  const historyEntry = {
    id: String(issueNumber),
    title: issueData.title,
    generated_at: issueData.createdAt,
    domain_id: 'unknown',
    spoke_id: 'unassigned',
    mirukarte_score: extracted.mirukarte_score ?? null,
    structured_attrs: extracted.structured_attrs ?? extracted,
  };

  writeFileSync(filepath, JSON.stringify(historyEntry, null, 2) + '\n');
  console.log(`  Saved: ${filename} (score: ${historyEntry.mirukarte_score})`);
}

if (isAll) {
  console.log('全Issueのバックフィルを開始...');
  let issues;
  try {
    issues = JSON.parse(gh(`issue list --repo ${REPO} --label research --state all --json number --limit 100`));
  } catch {
    issues = Array.from({ length: 8 }, (_, i) => ({ number: i + 1 }));
  }
  for (const issue of issues) {
    await backfillIssue(issue.number);
  }
} else {
  await backfillIssue(parseInt(issueArg, 10));
}

console.log('バックフィル完了。');
