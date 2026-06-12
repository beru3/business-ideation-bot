// 直近の投稿をGitHub Issueにコメントとして記録する
//   node log-post.mjs <account-slug> <issue-number>
// 前提: gh CLI が認証済み（カレントディレクトリ＝リポジトリルート）
import { readFileSync, writeFileSync, rmSync } from 'node:fs';
import { execSync } from 'node:child_process';

const [slug, issue] = process.argv.slice(2);
if (!slug || !issue) {
  console.error('usage: node log-post.mjs <account-slug> <issue-number>');
  process.exit(1);
}

const posted = JSON.parse(readFileSync(`x-bot/accounts/${slug}/posted.json`, 'utf8'));
const last = posted[posted.length - 1];
if (!last) {
  console.log(`[${slug}] 投稿履歴なし → ログ記録をスキップ`);
  process.exit(0);
}

const jst = new Date(last.postedAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' });
const quoted = last.text.split('\n').map(l => `> ${l}`).join('\n');
const body = `**${jst}** [${last.type}] ${last.url}\n\n${quoted}`;

const tmp = 'log-post-comment.tmp.md';
try {
  writeFileSync(tmp, body);
  execSync(`gh issue comment ${issue} --body-file ${tmp}`, { stdio: 'inherit' });
  console.log(`[${slug}] Issue #${issue} に投稿ログを記録`);
} catch (e) {
  // ログ記録の失敗は投稿自体の成否に影響させない
  console.error(`[${slug}] Issueログ記録に失敗: ${e.message}`);
} finally {
  rmSync(tmp, { force: true });
}
