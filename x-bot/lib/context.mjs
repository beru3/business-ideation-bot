// Shared context loader for multi-account x-bot
// Usage: import { loadContext } from './lib/context.mjs';
//        const ctx = loadContext(); // reads --account from argv
import { TwitterApi } from 'twitter-api-v2';
import { readFileSync, writeFileSync, existsSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, dirname } from 'node:path';

const ROOT = join(fileURLToPath(import.meta.url), '..', '..');

export function parseAccount() {
  const idx = process.argv.indexOf('--account');
  if (idx === -1 || !process.argv[idx + 1]) {
    console.error('Usage: node <script>.mjs --account <slug>');
    process.exit(1);
  }
  return process.argv[idx + 1];
}

export function listAccounts() {
  const accountsDir = join(ROOT, 'accounts');
  if (!existsSync(accountsDir)) return [];
  return readdirSync(accountsDir, { withFileTypes: true })
    .filter(d => d.isDirectory() && existsSync(join(accountsDir, d.name, 'config.json')))
    .map(d => d.name);
}

export function loadContext() {
  const slug = parseAccount();
  const accountDir = join(ROOT, 'accounts', slug);
  const config = JSON.parse(readFileSync(join(accountDir, 'config.json'), 'utf8'));

  const prefix = config.secretPrefix;
  const envKeys = {
    apiKey: `${prefix}_X_API_KEY`,
    apiSecret: `${prefix}_X_API_KEY_SECRET`,
    accessToken: `${prefix}_X_ACCESS_TOKEN`,
    accessSecret: `${prefix}_X_ACCESS_TOKEN_SECRET`,
  };

  for (const [label, key] of Object.entries(envKeys)) {
    if (!process.env[key]) {
      console.error(`環境変数が未設定: ${key}`);
      process.exit(1);
    }
  }

  const client = new TwitterApi({
    appKey: process.env[envKeys.apiKey],
    appSecret: process.env[envKeys.apiSecret],
    accessToken: process.env[envKeys.accessToken],
    accessSecret: process.env[envKeys.accessSecret],
  });

  return {
    slug,
    config,
    client,
    accountDir,
    root: ROOT,
    paths: {
      queue: join(accountDir, 'queue.json'),
      posted: join(accountDir, 'posted.json'),
      engageHistory: join(accountDir, 'engage_history.json'),
      metricsHistory: join(accountDir, 'metrics_history.json'),
      learnings: join(ROOT, 'shared', 'learnings.json'),
    },
  };
}

export function readJSON(path, fallback) {
  try { return JSON.parse(readFileSync(path, 'utf8')); }
  catch { return fallback; }
}

export function writeJSON(path, data) {
  writeFileSync(path, JSON.stringify(data, null, 2) + '\n');
}
