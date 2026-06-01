import { describe, it, expect } from 'vitest';
import { calculateSimilarity, classifyIdea } from '../similarity.mjs';

const DEFAULT_CONFIG = {
  duplicateThreshold: 0.85,
  expansionThreshold: 0.65,
};

const MIRUKARTE_ATTRS = {
  data_source_type: 'regulated_format',
  target_industry: 'medical-clinic',
  revenue_model: 'saas-subscription',
  value_layer: 'both',
  regulation_level: 'high-medical',
};

const DENTAL_ATTRS = {
  data_source_type: 'regulated_format',
  target_industry: 'dental',
  revenue_model: 'saas-subscription',
  value_layer: 'both',
  regulation_level: 'high-medical',
};

const RESTAURANT_ATTRS = {
  data_source_type: 'unregulated_paper',
  target_industry: 'restaurant-individual',
  revenue_model: 'saas-subscription',
  value_layer: 'both',
  regulation_level: 'low-general',
};

describe('calculateSimilarity', () => {
  it('identical attrs → 1.0', () => {
    expect(calculateSimilarity(MIRUKARTE_ATTRS, MIRUKARTE_ATTRS)).toBe(1.0);
  });

  it('completely different attrs → 0.0', () => {
    const a = {
      data_source_type: 'regulated_format',
      target_industry: 'medical-clinic',
      revenue_model: 'saas-subscription',
      value_layer: 'both',
      regulation_level: 'high-medical',
    };
    const b = {
      data_source_type: 'none',
      target_industry: 'other-gaming',
      revenue_model: 'one-time',
      value_layer: 'platform',
      regulation_level: 'low-general',
    };
    expect(calculateSimilarity(a, b)).toBe(0.0);
  });

  it('only data_source_type matches → 0.30', () => {
    const a = { ...MIRUKARTE_ATTRS };
    const b = {
      data_source_type: 'regulated_format',
      target_industry: 'other-xyz',
      revenue_model: 'one-time',
      value_layer: 'platform',
      regulation_level: 'low-general',
    };
    expect(calculateSimilarity(a, b)).toBeCloseTo(0.30);
  });

  it('mirukarte vs dental → 0.75 (target_industry differs)', () => {
    const score = calculateSimilarity(MIRUKARTE_ATTRS, DENTAL_ATTRS);
    expect(score).toBeCloseTo(0.75);
  });

  it('mirukarte vs restaurant → 0.35 (revenue_model + value_layer match)', () => {
    // revenue_model: 0.20 + value_layer: 0.15 = 0.35
    const score = calculateSimilarity(MIRUKARTE_ATTRS, RESTAURANT_ATTRS);
    expect(score).toBeCloseTo(0.35);
  });
});

describe('classifyIdea', () => {
  const makeHistory = (attrs, id = '1', title = 'test') => [{
    id,
    title,
    generated_at: '2026-05-27T00:00:00Z',
    structured_attrs: attrs,
  }];

  it('no history → novel', () => {
    const result = classifyIdea({ structured_attrs: MIRUKARTE_ATTRS }, [], DEFAULT_CONFIG);
    expect(result.tag).toBe('novel');
    expect(result.action).toBe('create_issue');
  });

  it('identical → duplicate (score 1.0 >= 0.85)', () => {
    const history = makeHistory(MIRUKARTE_ATTRS);
    const result = classifyIdea({ structured_attrs: MIRUKARTE_ATTRS }, history, DEFAULT_CONFIG);
    expect(result.tag).toBe('duplicate');
    expect(result.action).toBe('skip_duplicate');
  });

  it('mirukarte vs dental → horizontal-expansion (0.75 >= 0.65)', () => {
    const history = makeHistory(MIRUKARTE_ATTRS, '1', 'ミルカルテ');
    const result = classifyIdea({ structured_attrs: DENTAL_ATTRS }, history, DEFAULT_CONFIG);
    expect(result.tag).toBe('horizontal-expansion');
    expect(result.action).toBe('create_issue_with_relation');
    expect(result.similar_to[0].score).toBeCloseTo(0.75);
  });

  it('mirukarte vs restaurant → novel (0.20 < 0.50 filter)', () => {
    const history = makeHistory(MIRUKARTE_ATTRS, '1', 'ミルカルテ');
    const result = classifyIdea({ structured_attrs: RESTAURANT_ATTRS }, history, DEFAULT_CONFIG);
    expect(result.tag).toBe('novel');
  });

  it('history without structured_attrs is skipped', () => {
    const history = [{ id: '1', title: 'old', generated_at: '2026-01-01' }];
    const result = classifyIdea({ structured_attrs: MIRUKARTE_ATTRS }, history, DEFAULT_CONFIG);
    expect(result.tag).toBe('novel');
  });
});

import { nameSimilarity, isNameSimilar, charBigrams } from '../similarity.mjs';

describe('nameSimilarity (Japanese-safe, the #4 bug)', () => {
  it('near-identical Japanese names score high (old tokenizer scored ~0)', () => {
    const a = '医療機関向けAI-SNS運用代行SaaS';
    const b = '医療機関向けAI-SNS運用代行サービス';
    expect(nameSimilarity(a, b)).toBeGreaterThan(0.5);
    expect(isNameSimilar(a, b)).toBe(true);
  });

  it('unrelated names score low', () => {
    expect(isNameSimilar('飲食店AI原価管理アプリ', '建設現場AI検査員')).toBe(false);
  });

  it('identical names → 1.0', () => {
    expect(nameSimilarity('校務AIレポート生成SaaS', '校務AIレポート生成SaaS')).toBeCloseTo(1.0);
  });

  it('handles spaceless single-token Japanese (no whitespace at all)', () => {
    // 旧 split(/\s+/) では1トークンに潰れて overlap 判定不能だった
    expect(charBigrams('在宅医療コーディネート').size).toBeGreaterThan(3);
  });

  it('empty / null safe', () => {
    expect(nameSimilarity('', 'x')).toBe(0);
    expect(nameSimilarity(null, null)).toBe(0);
  });
});
