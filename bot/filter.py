"""
ナレッジベースによる仮説フィルタリング

DeepSeekが生成した仮説を、マーケティング侍496件のインサイトと照合し、
ナレッジで裏付けられた仮説にスコアを付与してランク付けする。

Usage:
  python bot/filter.py              # フィルタリング実行
  python bot/filter.py --dry        # ファイル保存しない
  python bot/filter.py --threshold 0.1  # 最低スコア閾値
"""
import json
import os
import sys

HYPOTHESES_FILE = "bot/signals_hypotheses.json"
OUTPUT_FILE = "bot/signals_filtered.json"

SUPABASE_URL = "https://fkyapyaiqigqdfdyjyop.supabase.co"
SUPABASE_KEY = os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZreWFweWFpcWlncWRmZHlqeW9wIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDQ2ODU1OCwiZXhwIjoyMDk2MDQ0NTU4fQ.hoy8AVtQePHU5TcQHxhBxT736yvtWSNItzpwAdtm5cg",
)

# フィルタリング閾値
DEFAULT_THRESHOLD = 0.05  # knowledge_score がこれ以上の仮説のみ通過


def _bigrams(text):
    """テキストから2文字グラムの集合を生成。"""
    if not text:
        return set()
    text = text.lower().replace(" ", "").replace("　", "")
    return {text[i:i+2] for i in range(len(text) - 1)} if len(text) >= 2 else set()


def _similarity(text_a, text_b):
    """2つのテキストの類似度を0-1で返す（Jaccard係数、2-gram）。"""
    a = _bigrams(text_a)
    b = _bigrams(text_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _fetch_insights():
    """Supabase からナレッジインサイトを全件取得。"""
    try:
        from supabase import create_client
        db = create_client(SUPABASE_URL, SUPABASE_KEY)
        result = db.table("knowledge_insights").select(
            "id, target_who, target_industry, pain_point, "
            "existing_solution, automation_opportunity, market_hint, tags, confidence"
        ).execute()
        return result.data
    except Exception as e:
        print(f"  Error fetching insights: {e}")
        return []


def _score_hypothesis(hypothesis, insights):
    """仮説とナレッジインサイト群を照合し、裏付けスコアと根拠を返す。

    照合ロジック:
    - 仮説の problem/solution/target_who と
      インサイトの pain_point/automation_opportunity/target_who を
      2-gram Jaccard で比較
    - 上位マッチのスコアを重み付き合算
    """
    h_problem = hypothesis.get("problem", "")
    h_solution = hypothesis.get("solution", "")
    h_target = hypothesis.get("target_who", "")
    h_text = f"{h_problem} {h_solution} {h_target}"

    matches = []

    for ins in insights:
        i_pain = ins.get("pain_point", "")
        i_auto = ins.get("automation_opportunity", "")
        i_target = ins.get("target_who", "")
        i_tags = " ".join(ins.get("tags", []))
        confidence = ins.get("confidence", 0.5)

        # 各軸の類似度
        pain_sim = _similarity(h_problem, i_pain)
        solution_sim = _similarity(h_solution, i_auto)
        target_sim = _similarity(h_target, i_target)
        tag_sim = _similarity(h_text, i_tags)

        # 重み付きスコア（problem重視）
        weighted = (
            pain_sim * 0.4 +
            solution_sim * 0.3 +
            target_sim * 0.2 +
            tag_sim * 0.1
        ) * confidence

        if weighted > 0.02:
            matches.append({
                "insight_id": ins.get("id"),
                "pain_point": i_pain[:100],
                "automation_opportunity": i_auto[:100],
                "target_who": i_target[:60],
                "similarity": round(weighted, 4),
                "breakdown": {
                    "pain": round(pain_sim, 3),
                    "solution": round(solution_sim, 3),
                    "target": round(target_sim, 3),
                    "tags": round(tag_sim, 3),
                },
            })

    matches.sort(key=lambda m: m["similarity"], reverse=True)
    top_matches = matches[:5]

    # 総合スコア: 上位マッチの加重平均（上位ほど重みが高い）
    if not top_matches:
        return 0.0, []

    weights = [1.0, 0.6, 0.4, 0.3, 0.2]
    total_w = sum(weights[:len(top_matches)])
    knowledge_score = sum(
        m["similarity"] * weights[i]
        for i, m in enumerate(top_matches)
    ) / total_w

    return round(knowledge_score, 4), top_matches


def filter_hypotheses(dry_run=False, threshold=None):
    """仮説をナレッジベースでフィルタリング・ランク付け。"""
    if threshold is None:
        threshold = DEFAULT_THRESHOLD

    if not os.path.exists(HYPOTHESES_FILE):
        print(f"Error: {HYPOTHESES_FILE} が見つかりません。")
        sys.exit(1)

    with open(HYPOTHESES_FILE, encoding="utf-8") as f:
        hypotheses = json.load(f)

    print(f"仮説: {len(hypotheses)}件")

    # ナレッジ取得
    insights = _fetch_insights()
    print(f"ナレッジインサイト: {len(insights)}件")

    if not insights:
        print("ナレッジが取得できません。フィルタリングをスキップします。")
        return

    # 各仮説をスコアリング
    scored = []
    for h in hypotheses:
        knowledge_score, matches = _score_hypothesis(h, insights)
        scored.append({
            **h,
            "knowledge_score": knowledge_score,
            "knowledge_matches": matches,
        })

    # スコア降順ソート
    scored.sort(key=lambda x: x["knowledge_score"], reverse=True)

    # 結果表示
    print(f"\n{'='*60}")
    print(f"  ナレッジ裏付けスコア (閾値: {threshold})")
    print(f"{'='*60}")

    passed = []
    for h in scored:
        ks = h["knowledge_score"]
        fs = h.get("founder_fit", {}).get("total", "?")
        status = "PASS" if ks >= threshold else "SKIP"
        mark = ">" if ks >= threshold else " "

        print(f"  {mark} [{status}] knowledge={ks:.4f} founder_fit={fs}/10 | {h['title']}")

        if h["knowledge_matches"]:
            top = h["knowledge_matches"][0]
            print(f"           top match (sim={top['similarity']:.4f}): {top['pain_point'][:60]}...")

        if ks >= threshold:
            passed.append(h)

    print(f"\n結果: {len(passed)}/{len(scored)} 通過 (閾値 {threshold})")

    if dry_run:
        print("\n[DRY RUN] ファイル保存をスキップ")
        return

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(passed, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    threshold = DEFAULT_THRESHOLD

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--threshold" and i < len(sys.argv) - 1:
            threshold = float(sys.argv[i + 1])

    filter_hypotheses(dry_run=dry, threshold=threshold)
