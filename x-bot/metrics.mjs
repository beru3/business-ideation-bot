// X投稿メトリクス取得
//   node metrics.mjs --account aio-checker
//
// 環境変数: {PREFIX}_X_*
import { loadContext, readJSON, writeJSON } from './lib/context.mjs';
import { execSync } from 'node:child_process';

const ctx = loadContext();
const { slug, config, client, paths } = ctx;
const gh = (args) => execSync('gh ' + args, { encoding: 'utf8' });

// 1. 投稿台帳からツイートIDを取得
const posted = readJSON(paths.posted, []);
const tweetIds = posted.map(p => p.tweetId).filter(Boolean);

if (tweetIds.length === 0) {
  console.log(`[${slug}] 投稿台帳が空です。`);
  process.exit(0);
}

// 2. X API v2でメトリクス取得（100件ずつ）
const allMetrics = [];
for (let i = 0; i < tweetIds.length; i += 100) {
  const batch = tweetIds.slice(i, i + 100);
  const res = await client.v2.tweets(batch, {
    'tweet.fields': 'public_metrics,created_at',
  });
  for (const tweet of (res.data || [])) {
    const entry = posted.find(p => p.tweetId === tweet.id);
    allMetrics.push({
      id: entry?.id || '?',
      tweetId: tweet.id,
      text: (entry?.text || '').slice(0, 40),
      type: entry?.type || 'unknown',
      impressions: tweet.public_metrics.impression_count,
      likes: tweet.public_metrics.like_count,
      retweets: tweet.public_metrics.retweet_count,
      replies: tweet.public_metrics.reply_count,
      quotes: tweet.public_metrics.quote_count,
    });
  }
}

// 投稿順にソート
const idOrder = new Map(posted.map((p, i) => [p.tweetId, i]));
allMetrics.sort((a, b) => (idOrder.get(a.tweetId) ?? 999) - (idOrder.get(b.tweetId) ?? 999));

// 3. レポート生成
const today = new Date().toISOString().slice(0, 10);
const totalImp = allMetrics.reduce((s, m) => s + m.impressions, 0);
const totalLikes = allMetrics.reduce((s, m) => s + m.likes, 0);
const totalRT = allMetrics.reduce((s, m) => s + m.retweets, 0);

const tableHeader = '| ID | タイプ | テキスト | imp | ♥ | RT | 返信 |';
const tableSep    = '|---|---|---|---:|---:|---:|---:|';
const tableRows = allMetrics.map(m =>
  `| ${m.id} | ${m.type} | ${m.text}… | ${m.impressions} | ${m.likes} | ${m.retweets} | ${m.replies} |`
);

const reportMd = [
  `### [${slug}] ${today} メトリクスレポート`,
  '',
  `**合計:** imp ${totalImp} / ♥ ${totalLikes} / RT ${totalRT} / 投稿数 ${allMetrics.length}`,
  '',
  tableHeader,
  tableSep,
  ...tableRows,
].join('\n');

console.log(reportMd);

// 4. フォロワー数を取得
let followerCount = 0;
try {
  const me = await client.v2.me({ 'user.fields': 'public_metrics' });
  followerCount = me.data.public_metrics?.followers_count || 0;
} catch { /* ignore */ }

// 5. メトリクス履歴をJSONに保存
const history = readJSON(paths.metricsHistory, []);
history.push({
  date: today,
  followerCount,
  totalImpressions: totalImp,
  totalLikes,
  totalRetweets: totalRT,
  metrics: allMetrics,
});

// 直近90日分だけ保持
const cutoff = new Date();
cutoff.setDate(cutoff.getDate() - 90);
const cutoffStr = cutoff.toISOString().slice(0, 10);
const trimmed = history.filter(h => h.date >= cutoffStr);
writeJSON(paths.metricsHistory, trimmed);

// 6. GitHub Issue にレポート追記
try {
  const tmpFile = `/tmp/x_metrics_${slug}.md`;
  const { writeFileSync } = await import('node:fs');
  writeFileSync(tmpFile, reportMd);
  gh(`issue comment ${config.metricsIssueNumber || 2} --repo beru3/business-ideation-bot --body-file ${tmpFile}`);
  console.log(`Issue にレポートを追記しました。`);
} catch (e) {
  console.error('Issue更新に失敗:', e.message);
}

console.log(`[${slug}] メトリクス取得完了（フォロワー: ${followerCount}）`);
