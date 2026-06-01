// 構造化属性ベースの類似度計算・重複排除
//
// 5属性の重み付き完全一致で類似度スコアを算出し、
// しきい値に基づいて novel / related / horizontal-expansion / duplicate に分類する。

const ATTR_WEIGHTS = {
  data_source_type: 0.30,
  target_industry: 0.25,
  revenue_model: 0.20,
  value_layer: 0.15,
  regulation_level: 0.10,
};

export function calculateSimilarity(newAttrs, historicalAttrs) {
  let score = 0;
  for (const [key, weight] of Object.entries(ATTR_WEIGHTS)) {
    if (newAttrs[key] && newAttrs[key] === historicalAttrs[key]) {
      score += weight;
    }
  }
  return score;
}

// --- 仮説名の類似判定（日本語対応） ---
// 旧実装は split(/\s+/) で空白区切りトークンを前提にしており、空白の無い
// 日本語の仮説名が1トークンに潰れて重複検出が機能していなかった。
// 文字バイグラムの Jaccard 係数に置き換えることで日本語でも機能する。
export function charBigrams(s) {
  const norm = (s || '').toLowerCase().replace(/[\s【】（）()・/／\-_,.、。]/g, '');
  const grams = new Set();
  for (let i = 0; i < norm.length - 1; i++) grams.add(norm.slice(i, i + 2));
  if (norm.length === 1) grams.add(norm);
  return grams;
}

export function nameSimilarity(a, b) {
  const A = charBigrams(a);
  const B = charBigrams(b);
  if (A.size === 0 || B.size === 0) return 0;
  let inter = 0;
  for (const g of A) if (B.has(g)) inter++;
  const union = A.size + B.size - inter;
  return union === 0 ? 0 : inter / union;
}

export function isNameSimilar(a, b, threshold = 0.5) {
  return nameSimilarity(a, b) >= threshold;
}

export function classifyIdea(newIdea, history, config) {
  const { duplicateThreshold, expansionThreshold } = config;

  const similar = history
    .filter(h => h.structured_attrs)
    .map(h => ({
      id: h.id,
      title: h.title,
      score: calculateSimilarity(newIdea.structured_attrs, h.structured_attrs),
      generated_at: h.generated_at,
    }))
    .filter(x => x.score >= 0.5)
    .sort((a, b) => b.score - a.score);

  if (similar.length === 0) {
    return { action: 'create_issue', tag: 'novel', similar_to: [] };
  }

  const topScore = similar[0].score;

  if (topScore >= duplicateThreshold) {
    return {
      action: 'skip_duplicate',
      tag: 'duplicate',
      similar_to: similar.slice(0, 3),
      reason: `既存Issue #${similar[0].id} と類似度${(topScore * 100).toFixed(0)}%`,
    };
  }

  if (topScore >= expansionThreshold) {
    return {
      action: 'create_issue_with_relation',
      tag: 'horizontal-expansion',
      similar_to: similar.slice(0, 3),
      reason: `既存Issue #${similar[0].id} の横展開候補（類似度${(topScore * 100).toFixed(0)}%）`,
    };
  }

  return {
    action: 'create_issue',
    tag: 'related',
    similar_to: similar.slice(0, 3),
  };
}
