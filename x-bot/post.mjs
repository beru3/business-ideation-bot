// X自動投稿
//   node post.mjs --account aio-checker              … キューから1件投稿
//   node post.mjs --account aio-checker check        … 認証確認のみ
//   node post.mjs --account aio-checker post [THR]   … しきい値付き投稿
//
// 環境変数: {PREFIX}_X_*
import { loadContext, readJSON, writeJSON } from './lib/context.mjs';
import { appendFileSync } from 'node:fs';

const ctx = loadContext();
const { slug, config, client, paths } = ctx;

// モード判定（--account の後の引数）
const args = process.argv.slice(process.argv.indexOf('--account') + 2);
const mode = args[0] || 'post';
const threshold = parseInt(args[1] || '1', 10);

// 認証確認モード
if (mode === 'check') {
  const me = await client.v2.me();
  console.log(`[${slug}] OK: 認証成功 — @${me.data.username}（${me.data.name}）`);
  process.exit(0);
}

if (mode !== 'post') {
  console.error(`不明なモード: ${mode}（check / post のいずれか）`);
  process.exit(1);
}

// --- post モード ---
const queue = readJSON(paths.queue, []);
const posted = readJSON(paths.posted, []);
const postedIds = new Set(posted.map(p => p.id));

// 未投稿の案を抽出
const pending = queue.filter(q => !postedIds.has(q.id));

// GITHUB_OUTPUT に残数を書き出す
if (process.env.GITHUB_OUTPUT) {
  appendFileSync(process.env.GITHUB_OUTPUT, `remaining_${slug}=${pending.length}\n`);
}

if (pending.length < threshold) {
  console.log(`[${slug}] キュー残 ${pending.length}件（しきい値 ${threshold} 未満）→ スキップ`);
  process.exit(0);
}

const target = pending[0];

// 投稿（URLはリプライに分離してリーチ低下を回避）
const urlRegex = /(https?:\/\/\S+)/g;
const extractedUrls = target.text.match(urlRegex);
const mainText = extractedUrls
  ? target.text.replace(urlRegex, '').replace(/\s*→\s*$/, '').trim()
  : target.text;
const tweetText = mainText.length >= 10 ? mainText : target.text;

const res = await client.v2.tweet(tweetText);
const tweetId = res.data.id;
const url = `https://x.com/${config.account}/status/${tweetId}`;

if (extractedUrls && mainText.length >= 10) {
  try {
    await client.v2.tweet(extractedUrls.join('\n'), {
      reply: { in_reply_to_tweet_id: tweetId },
    });
    console.log(`[${slug}] リンクをリプライに分離: ${extractedUrls.join(', ')}`);
  } catch (e) {
    console.log(`[${slug}] リンクリプライ失敗: ${e?.data?.detail || e.message}`);
  }
}

// GITHUB_OUTPUT 更新
if (process.env.GITHUB_OUTPUT) {
  appendFileSync(process.env.GITHUB_OUTPUT, `remaining_${slug}=${pending.length - 1}\n`);
}

// 台帳に記録
posted.push({
  id: target.id,
  text: target.text,
  type: target.type || 'unknown',
  tweetId,
  url,
  postedAt: new Date().toISOString(),
});
writeJSON(paths.posted, posted);

// キューから削除
const updatedQueue = queue.filter(q => q.id !== target.id);
writeJSON(paths.queue, updatedQueue);

console.log(`[${slug}] 投稿: ${target.id} → ${url}`);
