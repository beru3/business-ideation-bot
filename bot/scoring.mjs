// 本人適合度（Founder-Fit）スコアの抽出と推奨アクション判定
//
// 旧「ミルカルテ適合度」は医療ドメインに特化しすぎており、独立探索器の目的
// （医療外も含めて当てにいく）と矛盾していたため、ドメイン非依存の
// 「本人適合度」へ張り替えた。スコアは生成モデルではなく批判モデル（critic）が
// 減点法で採点した結果を、機械可読タグ FOUNDER_FIT_SCORE から厳密に抽出する。

// critic 出力から `FOUNDER_FIT_SCORE: X/10` 形式を厳密に1つだけ拾う。
// 本文中に併存する [39/50] 等の業績スコア表とは衝突しない。
// 全角コロン・全角スラッシュ・小数点・前後空白を許容する。
export function extractFounderFitScore(content) {
  if (!content) return null;
  const m = content.match(/FOUNDER_FIT_SCORE\s*[:：]\s*(\d+(?:\.\d+)?)/i);
  return m ? parseFloat(m[1]) : null;
}

// 0–10 の本人適合度から、bot の取り回しを決める。
//   >=8  … 深掘り（deep-research）への昇格候補
//   >=5  … 監視（issue 化はするが着手はしない）
//   それ未満 … アーカイブ（issue 化せず履歴のみ）
export function getRecommendedAction(score) {
  if (score == null) return 'monitor';
  if (score >= 8) return 'promote-to-deep-research';
  if (score >= 5) return 'monitor';
  return 'archive';
}
