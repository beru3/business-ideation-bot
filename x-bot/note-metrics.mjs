// note記事メトリクス取得
//   node note-metrics.mjs --account hourei-navi
//
// 環境変数: NOTE_EMAIL, NOTE_PASSWORD
// 出力: x-bot/accounts/{slug}/note_metrics.json
import { parseAccount, readJSON, writeJSON } from './lib/context.mjs';
import { chromium } from 'playwright';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';

const ROOT = join(fileURLToPath(import.meta.url), '..');
const slug = parseAccount();
const accountDir = join(ROOT, 'accounts', slug);
const config = JSON.parse(readFileSync(join(accountDir, 'config.json'), 'utf8'));

const email = process.env.NOTE_EMAIL;
const password = process.env.NOTE_PASSWORD;

if (!email || !password) {
  console.error('環境変数が未設定: NOTE_EMAIL, NOTE_PASSWORD');
  process.exit(1);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext();
const page = await context.newPage();

try {
  // 1. noteにログイン
  console.log(`[${slug}] noteにログイン中...`);
  await page.goto('https://note.com/login');
  await page.waitForTimeout(2000);

  // ログインフォームが表示されるか、既にログイン済みかチェック
  const loginBtn = page.locator('a:has-text("ログイン"), button:has-text("ログイン")');
  if (await loginBtn.count() > 0) {
    await page.getByPlaceholder('mail@example.com').fill(email);
    await page.locator('#password').fill(password);
    await page.getByRole('button', { name: 'ログイン' }).click();
    await page.waitForTimeout(3000);
  }

  // 2. ダッシュボードAPIからPVデータ取得
  console.log(`[${slug}] ダッシュボードからメトリクス取得中...`);

  // Cookie付きでAPIを直接呼ぶ
  const cookies = await context.cookies();
  const cookieHeader = cookies.map(c => `${c.name}=${c.value}`).join('; ');

  // 全期間のPVデータ
  const response = await page.evaluate(async () => {
    const res = await fetch('/api/v1/stats/pv?filter=all&page=1&sort=pv');
    return res.json();
  });

  const noteStats = response?.data?.note_stats || [];
  const totalPv = response?.data?.total_pv || 0;
  const totalLike = response?.data?.total_like || 0;
  const totalComment = response?.data?.total_comment || 0;

  // 3. 記事ごとのメトリクスを整形
  const today = new Date().toISOString().slice(0, 10);
  const articles = noteStats.map(s => ({
    noteId: s.key,
    title: s.name || '',
    url: `https://note.com/${config.noteAccountId || slug.replace(/-/g, '_')}/n/${s.key}`,
    pv: s.read_count || 0,
    likes: s.like_count || 0,
    comments: s.comment_count || 0,
  }));

  const report = {
    measured_at: today,
    slug,
    total_pv: totalPv,
    total_likes: totalLike,
    total_comments: totalComment,
    articles,
  };

  // 4. 履歴に追記
  const historyPath = join(accountDir, 'note_metrics.json');
  const history = readJSON(historyPath, []);

  // 同日のデータがあれば上書き、なければ追加
  const existingIdx = history.findIndex(h => h.measured_at === today);
  if (existingIdx >= 0) {
    history[existingIdx] = report;
  } else {
    history.push(report);
  }

  // 直近30日分のみ保持
  const trimmed = history.slice(-30);
  writeJSON(historyPath, trimmed);

  // 5. コンソール出力
  console.log(`\n[${slug}] note メトリクスレポート (${today})`);
  console.log(`  総PV: ${totalPv}  総スキ: ${totalLike}  総コメント: ${totalComment}`);
  console.log('  ---');
  for (const a of articles) {
    console.log(`  ${a.title.slice(0, 40).padEnd(42)} PV:${String(a.pv).padStart(5)} スキ:${String(a.likes).padStart(3)}`);
  }
  console.log(`\n  保存先: ${historyPath}`);

} finally {
  await browser.close();
}
