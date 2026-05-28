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
