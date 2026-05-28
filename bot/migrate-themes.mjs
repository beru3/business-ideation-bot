#!/usr/bin/env node
// themes.json v1 (flat array) → v2 (domain-weighted) マイグレーション
//
// 使い方: node bot/migrate-themes.mjs [input.json] [output.json]
//   デフォルト: bot/themes.json → bot/themes.json (上書き)

import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const dir = fileURLToPath(new URL('./', import.meta.url));
const inputPath = process.argv[2] || dir + 'themes.json';
const outputPath = process.argv[3] || inputPath;

const raw = JSON.parse(readFileSync(inputPath, 'utf8'));

if (!Array.isArray(raw)) {
  console.log('既にv2形式です。マイグレーション不要。');
  process.exit(0);
}

const MEDICAL_KEYWORDS = ['医療', 'ヘルスケア', 'クリニック', '病院', '診療', '薬局', '看護', '歯科'];
const CARE_KEYWORDS = ['介護', '福祉', 'ケアマネ', '認知症', '高齢者', 'シニア'];

const coreMedical = raw.filter(t => MEDICAL_KEYWORDS.some(k => t.includes(k)));
const careAdjacent = raw.filter(t =>
  CARE_KEYWORDS.some(k => t.includes(k)) && !coreMedical.includes(t)
);
const wildCard = raw.filter(t => !coreMedical.includes(t) && !careAdjacent.includes(t));

const v2 = {
  version: '2.0',
  domains: [
    { id: 'core_medical', weight: 50, themes: coreMedical.length > 0 ? coreMedical : ['医療・ヘルスケア'] },
    { id: 'care_adjacent', weight: 30, themes: careAdjacent.length > 0 ? careAdjacent : ['介護・福祉'] },
    { id: 'wild_card', weight: 20, themes: wildCard },
  ],
};

writeFileSync(outputPath, JSON.stringify(v2, null, 2) + '\n');
console.log(`マイグレーション完了: ${outputPath}`);
console.log(`  core_medical: ${v2.domains[0].themes.length}件`);
console.log(`  care_adjacent: ${v2.domains[1].themes.length}件`);
console.log(`  wild_card: ${v2.domains[2].themes.length}件`);
