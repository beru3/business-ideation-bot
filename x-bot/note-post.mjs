// note記事自動投稿
//   node note-post.mjs --account hourei-navi
//
// 環境変数: NOTE_EMAIL, NOTE_PASSWORD
// 入力: x-bot/accounts/{slug}/note_queue.json
// 出力: x-bot/accounts/{slug}/note_posted.json
import { parseAccount, readJSON, writeJSON } from './lib/context.mjs';
import { chromium } from 'playwright';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFileSync, existsSync } from 'node:fs';

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

// 1. キューから次の記事を取得
const queuePath = join(accountDir, 'note_queue.json');
const postedPath = join(accountDir, 'note_posted.json');
const queue = readJSON(queuePath, []);
const posted = readJSON(postedPath, []);

if (queue.length === 0) {
  console.log(`[${slug}] note投稿キューが空です。`);
  process.exit(0);
}

const article = queue[0];
console.log(`[${slug}] 投稿する記事: ${article.title}`);

// 記事本文をファイルから読み込み
let body = article.body || '';
if (article.filePath && existsSync(article.filePath)) {
  const rawMd = readFileSync(article.filePath, 'utf8');
  // タイトル行（# で始まる最初の行）を除去
  const lines = rawMd.split('\n');
  const titleLineIdx = lines.findIndex(l => l.startsWith('# '));
  if (titleLineIdx >= 0) lines.splice(titleLineIdx, 1);
  // ナレッジ適用フッター（---以降）を除去
  const sepIdx = lines.lastIndexOf('---');
  if (sepIdx >= 0) lines.splice(sepIdx);
  body = lines.join('\n').trim();
  // Markdown記法をプレーンテキストに変換（noteはプレーンテキスト入力）
  body = body
    .replace(/^## \d+\. /gm, '')          // ## 1. → 空
    .replace(/^## /gm, '')                 // ## → 空
    .replace(/^### /gm, '')                // ### → 空
    .replace(/\*\*(.*?)\*\*/g, '$1')       // **bold** → bold
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1\n$2')  // [text](url) → text\nurl
    .replace(/^- /gm, '・')               // - item → ・item
    .replace(/^▶ /gm, '▶ ');              // keep ▶
}

if (!body) {
  console.error(`[${slug}] 記事本文が空です。`);
  process.exit(1);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext();
const page = await context.newPage();

try {
  // 2. noteにログイン
  console.log(`[${slug}] noteにログイン中...`);
  await page.goto('https://note.com/login');
  await page.waitForTimeout(2000);

  const loginForm = page.getByPlaceholder('mail@example.com');
  if (await loginForm.count() > 0) {
    await loginForm.fill(email);
    await page.locator('#password').fill(password);
    await page.getByRole('button', { name: 'ログイン' }).click();
    await page.waitForTimeout(3000);
  }

  // 3. 新規記事作成
  console.log(`[${slug}] 記事を作成中...`);
  await page.goto('https://note.com/notes/new');
  await page.waitForTimeout(3000);

  // AIダイアログを閉じる
  const aiClose = page.locator('dialog button:has-text("閉じる")');
  if (await aiClose.count() > 0) {
    await aiClose.click();
    await page.waitForTimeout(500);
  }

  // タイトル入力
  const titleBox = page.getByRole('textbox', { name: '記事タイトル' });
  await titleBox.click();
  await titleBox.fill(article.title);
  await page.waitForTimeout(300);

  // 本文入力（クリップボードペースト）
  const bodyBox = page.getByRole('textbox').last();
  await bodyBox.click();
  await page.waitForTimeout(300);

  await page.evaluate(text => navigator.clipboard.writeText(text), body);
  await page.keyboard.down('Control');
  await page.keyboard.press('v');
  await page.keyboard.up('Control');
  await page.waitForTimeout(1000);

  // 4. 公開
  console.log(`[${slug}] 公開に進む...`);
  await page.getByRole('button', { name: '公開に進む' }).click();
  await page.waitForTimeout(2000);

  // 不要なハッシュタグを削除（記事内容から自動生成された無関係なもの）
  const tagContainer = page.locator('[class*="hashtag"], [class*="tag"]');
  // 指定ハッシュタグを追加
  if (article.hashtags && article.hashtags.length > 0) {
    const tagInput = page.getByRole('combobox', { name: 'ハッシュタグを追加する' });
    for (const tag of article.hashtags) {
      await tagInput.fill(tag);
      await page.waitForTimeout(500);
      await page.keyboard.press('Enter');
      await page.waitForTimeout(300);
    }
  }

  // 投稿する
  await page.getByRole('button', { name: '投稿する' }).click();
  await page.waitForTimeout(5000);

  // 5. 投稿URL取得
  const currentUrl = page.url();
  // URLからnote記事URLを推定
  const noteUrlMatch = currentUrl.match(/note\.com\/[^/]+\/n\/[a-z0-9]+/);
  const noteUrl = noteUrlMatch ? `https://${noteUrlMatch[0]}` : currentUrl;

  console.log(`[${slug}] 投稿完了: ${noteUrl}`);

  // シェアダイアログを閉じる
  const shareClose = page.locator('dialog button:has-text("閉じる")');
  if (await shareClose.count() > 0) {
    await shareClose.click();
  }

  // 6. キューから除去、posted に追加
  const postedEntry = {
    ...article,
    noteUrl,
    postedAt: new Date().toISOString(),
  };
  posted.push(postedEntry);
  writeJSON(postedPath, posted);

  queue.shift();
  writeJSON(queuePath, queue);

  console.log(`[${slug}] キュー残り: ${queue.length}件`);

} finally {
  await browser.close();
}
