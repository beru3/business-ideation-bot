import { describe, it, expect } from 'vitest';
import { extractFounderFitScore, getRecommendedAction } from '../scoring.mjs';

function extractStructuredAttrs(content) {
  const match = content.match(/```structured_attrs\s*\n([\s\S]*?)\n```/);
  if (!match) return null;
  try {
    return JSON.parse(match[1]);
  } catch {
    return null;
  }
}

describe('extractFounderFitScore', () => {
  it('extracts the machine-readable tag', () => {
    expect(extractFounderFitScore('FOUNDER_FIT_SCORE: 8/10')).toBe(8);
  });

  it('extracts a decimal score', () => {
    expect(extractFounderFitScore('FOUNDER_FIT_SCORE: 6.5/10')).toBe(6.5);
  });

  it('tolerates full-width colon and surrounding text', () => {
    const txt = '最大の懸念: 販路なし\nFOUNDER_FIT_SCORE：4/10\n';
    expect(extractFounderFitScore(txt)).toBe(4);
  });

  it('does NOT collide with a 50-point business-score table (the old bug)', () => {
    const txt = `## 総合評価
| 仮説 | 総合スコア |
| --- | --- |
| 仮説1 | 39/50 |
| 仮説2 | 38/50 |

軸1: 3点 — 資産フル活用
FOUNDER_FIT_SCORE: 7/10`;
    expect(extractFounderFitScore(txt)).toBe(7);
  });

  it('returns null when the tag is absent', () => {
    expect(extractFounderFitScore('スコアは 39/50 です')).toBeNull();
  });
});

describe('getRecommendedAction', () => {
  it('>=8 -> promote-to-deep-research', () => {
    expect(getRecommendedAction(8)).toBe('promote-to-deep-research');
    expect(getRecommendedAction(10)).toBe('promote-to-deep-research');
  });
  it('5..7.9 -> monitor', () => {
    expect(getRecommendedAction(5)).toBe('monitor');
    expect(getRecommendedAction(7.9)).toBe('monitor');
  });
  it('<5 -> archive', () => {
    expect(getRecommendedAction(4)).toBe('archive');
    expect(getRecommendedAction(0)).toBe('archive');
  });
  it('null -> monitor (fail-safe)', () => {
    expect(getRecommendedAction(null)).toBe('monitor');
  });
});

describe('extractStructuredAttrs', () => {
  it('extracts valid JSON from structured_attrs block', () => {
    const content = `text

\`\`\`structured_attrs
{
  "data_source_type": "regulated_format",
  "target_industry": "medical-clinic",
  "revenue_model": "saas-subscription",
  "value_layer": "both",
  "regulation_level": "high-medical"
}
\`\`\`

more`;
    expect(extractStructuredAttrs(content)).toEqual({
      data_source_type: 'regulated_format',
      target_industry: 'medical-clinic',
      revenue_model: 'saas-subscription',
      value_layer: 'both',
      regulation_level: 'high-medical',
    });
  });

  it('returns null for missing block', () => {
    expect(extractStructuredAttrs('no block here')).toBeNull();
  });

  it('returns null for invalid JSON', () => {
    expect(extractStructuredAttrs('```structured_attrs\n{invalid}\n```')).toBeNull();
  });
});
