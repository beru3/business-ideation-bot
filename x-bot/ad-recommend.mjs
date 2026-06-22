// 広告ブースト推奨 — 高パフォーマンス投稿を特定しIssueに通知
//   node ad-recommend.mjs   … 全アカウントの推奨を生成
//
// 環境変数: GH_TOKEN
import { listAccounts, readJSON } from './lib/context.mjs';
import { execSync } from 'node:child_process';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(fileURLToPath(import.meta.url), '..');
const gh = (args) => execSync('gh ' + args, { encoding: 'utf8' });

const accounts = listAccounts();
if (accounts.length === 0) {
  console.log('アカウントが見つかりません。');
  process.exit(0);
}

const today = new Date().toISOString().slice(0, 10);
const sections = [`## 広告ブースト推奨（${today}週）\n`];

for (const slug of accounts) {
  const historyPath = join(ROOT, 'accounts', slug, 'metrics_history.json');
  const configPath = join(ROOT, 'accounts', slug, 'config.json');
  const history = readJSON(historyPath, []);
  const config = readJSON(configPath, {});

  // 過去7日間
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 7);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  const recentDays = history.filter(h => h.date >= cutoffStr);
  const allPosts = recentDays.flatMap(d => d.metrics || []);

  if (allPosts.length === 0) {
    sections.push(`### @${config.account || slug}\n- データなし\n`);
    continue;
  }

  // エンゲージメント率を計算
  const postsWithRate = allPosts
    .filter(p => p.impressions >= 300)
    .map(p => ({
      ...p,
      engagementRate: p.impressions > 0
        ? ((p.likes + p.retweets + p.replies) / p.impressions * 100)
        : 0,
    }))
    .sort((a, b) => b.engagementRate - a.engagementRate);

  // 上位20%かつ2%以上
  const threshold = Math.max(
    postsWithRate.length > 0 ? postsWithRate[Math.floor(postsWithRate.length * 0.2)]?.engagementRate || 2 : 2,
    2,
  );

  const recommended = postsWithRate
    .filter(p => p.engagementRate >= threshold)
    .slice(0, 1); // 週1件まで

  if (recommended.length === 0) {
    sections.push(`### @${config.account || slug}\n- 今週は推奨なし（エンゲージメント率が基準未満）\n`);
  } else {
    for (const p of recommended) {
      const tweetUrl = `https://x.com/${config.account}/status/${p.tweetId}`;
      sections.push(
        `### @${config.account || slug}\n` +
        `- **推奨**: [この投稿](${tweetUrl})\n` +
        `  imp: ${p.impressions} / ♥: ${p.likes} / RT: ${p.retweets} / eng rate: ${p.engagementRate.toFixed(1)}%\n` +
        `  → Xアプリで「投稿をプロモート」→ 予算¥500-1,000/日で3日間テスト\n`,
      );
    }
  }
}

const body = sections.join('\n');
console.log(body);

// GitHub Issueに通知
try {
  const { writeFileSync } = await import('node:fs');
  writeFileSync('/tmp/ad_recommend.md', body);
  gh('issue comment 2 --repo beru3/business-ideation-bot --body-file /tmp/ad_recommend.md');
  console.log('Issue に推奨を投稿しました。');
} catch (e) {
  console.error('Issue投稿に失敗:', e.message);
}
