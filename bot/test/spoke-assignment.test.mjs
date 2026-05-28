import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const dir = fileURLToPath(new URL('../../', import.meta.url));
const brandsConfig = JSON.parse(readFileSync(dir + 'brands.json', 'utf8'));

function assignSpoke(themeText, config) {
  const matches = config.spokes.map(spoke => ({
    spokeId: spoke.id,
    score: spoke.target_keywords.filter(kw => themeText.includes(kw)).length,
    specificity: spoke.target_keywords.length,
  }));
  matches.sort((a, b) => b.score - a.score || a.specificity - b.specificity);
  return matches[0].score > 0 ? matches[0].spokeId : 'unassigned';
}

describe('assignSpoke', () => {
  const mirukarteCases = [
    '慢性疾患管理（内科・循環器・糖尿病）',
    'クリニック予約・待合最適化',
    '医療事務効率化',
    'オンライン診療・遠隔医療フォロー',
    '予防医療・健診結果フォロー',
  ];

  for (const theme of mirukarteCases) {
    it(`"${theme}" → spoke_mirukarte`, () => {
      expect(assignSpoke(theme, brandsConfig)).toBe('spoke_mirukarte');
    });
  }

  const dentalCases = [
    '歯科クリニック運営最適化',
    'デンタルケア向けSaaS',
    '歯科衛生士の業務支援',
    '歯科レセプト管理',
    '歯科向けオンライン予約',
  ];

  for (const theme of dentalCases) {
    it(`"${theme}" → spoke_dental`, () => {
      expect(assignSpoke(theme, brandsConfig)).toBe('spoke_dental');
    });
  }

  const kaigoCases = [
    '介護事業所運営（給付費明細書ベース）',
    'ケアマネジャー業務支援',
    '認知症ケア・家族支援',
    'サ高住・有料老人ホーム運営',
    '在宅介護家族の負担軽減',
  ];

  for (const theme of kaigoCases) {
    it(`"${theme}" → spoke_kaigo`, () => {
      expect(assignSpoke(theme, brandsConfig)).toBe('spoke_kaigo');
    });
  }

  it('異業種テーマ → unassigned', () => {
    expect(assignSpoke('飲食・フードテック', brandsConfig)).toBe('unassigned');
    expect(assignSpoke('建設・ConTech', brandsConfig)).toBe('unassigned');
  });
});
