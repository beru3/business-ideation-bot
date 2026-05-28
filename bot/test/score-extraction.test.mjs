import { describe, it, expect } from 'vitest';

function extractMirukarteScore(content) {
  const match = content.match(/総合スコア[\s\S]*?(\d+(?:\.\d+)?)\s*[\/／]\s*10/)
    || content.match(/適合度[\s\S]*?(\d+(?:\.\d+)?)\s*[\/／]\s*10/);
  return match ? parseFloat(match[1]) : null;
}

function extractStructuredAttrs(content) {
  const match = content.match(/```structured_attrs\s*\n([\s\S]*?)\n```/);
  if (!match) return null;
  try {
    return JSON.parse(match[1]);
  } catch {
    return null;
  }
}

describe('extractMirukarteScore', () => {
  it('should extract integer score', () => {
    expect(extractMirukarteScore('## 総合スコア\n8/10点')).toBe(8);
  });

  it('should extract decimal score', () => {
    expect(extractMirukarteScore('総合スコア: 7.5/10点（+ボーナス1点）')).toBe(7.5);
  });

  it('should return null for missing score', () => {
    expect(extractMirukarteScore('no score here')).toBeNull();
  });

  it('should handle newline after colon', () => {
    expect(extractMirukarteScore('## 総合スコア:\n9/10点')).toBe(9);
  });
});

describe('extractStructuredAttrs', () => {
  it('should extract valid JSON from structured_attrs block', () => {
    const content = `some text

\`\`\`structured_attrs
{
  "data_source_type": "regulated_format",
  "target_industry": "medical-clinic",
  "revenue_model": "saas-subscription",
  "value_layer": "both",
  "regulation_level": "high-medical"
}
\`\`\`

more text`;

    const attrs = extractStructuredAttrs(content);
    expect(attrs).toEqual({
      data_source_type: 'regulated_format',
      target_industry: 'medical-clinic',
      revenue_model: 'saas-subscription',
      value_layer: 'both',
      regulation_level: 'high-medical',
    });
  });

  it('should return null for missing block', () => {
    expect(extractStructuredAttrs('no block here')).toBeNull();
  });

  it('should return null for invalid JSON', () => {
    const content = '```structured_attrs\n{invalid}\n```';
    expect(extractStructuredAttrs(content)).toBeNull();
  });
});
