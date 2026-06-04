"""
ナレッジベースによる仮説フィルタリング（LLM判定）

DeepSeekが生成した仮説を、マーケティング侍496件のインサイトと照合。
1. 2-gram Jaccardで各仮説に近いナレッジ上位10件を高速に絞り込み
2. DeepSeekに「この仮説はナレッジで裏付けられるか？」を意味的に判定させる

Usage:
  python bot/filter.py              # フィルタリング実行
  python bot/filter.py --dry        # ファイル保存しない
"""
import json
import os
import re
import sys

HYPOTHESES_FILE = "bot/signals_hypotheses.json"
OUTPUT_FILE = "bot/signals_filtered.json"

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

SUPABASE_URL = "https://fkyapyaiqigqdfdyjyop.supabase.co"
SUPABASE_KEY = os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZreWFweWFpcWlncWRmZHlqeW9wIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDQ2ODU1OCwiZXhwIjoyMDk2MDQ0NTU4fQ.hoy8AVtQePHU5TcQHxhBxT736yvtWSNItzpwAdtm5cg",
)

CANDIDATES_PER_HYPOTHESIS = 10  # 2-gram で絞り込む候補数

FILTER_SYSTEM_PROMPT = """あなたはビジネスアイデアの裏付け判定の専門家です。

「仮説」と「ナレッジ（市場調査から得たインサイト）」が与えられます。
ナレッジが仮説の裏付けになるかを判定してください。

## 判定基準
裏付けとは、以下のいずれかに該当すること：
- ナレッジのペイン（pain_point）が、仮説の課題（problem）と同じ問題領域を指している
- ナレッジのターゲット（target_who）が、仮説のターゲットと重なる
- ナレッジの自動化機会（automation_opportunity）が、仮説のソリューションと類似のアプローチ
- ナレッジの市場ヒント（market_hint）が、仮説の市場機会を裏付ける

表現が違っても、意味的に同じ問題・同じ市場を指していれば裏付けありと判定してください。

## 出力フォーマット（厳守）
```json
{
  "verdict": "PASS" または "FAIL",
  "confidence": 0.0〜1.0,
  "reasoning": "判定理由（1-2文）",
  "best_match_id": 最も関連するナレッジのID（数値）,
  "best_match_reason": "そのナレッジが裏付けになる理由（1文）"
}
```
"""


def _bigrams(text):
    """テキストから2文字グラムの集合を生成。"""
    if not text:
        return set()
    text = text.lower().replace(" ", "").replace("\u3000", "")
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


def _find_candidates(hypothesis, insights, top_n=CANDIDATES_PER_HYPOTHESIS):
    """2-gram Jaccardで仮説に近いナレッジ上位N件を高速に絞り込む。"""
    h_text = " ".join([
        hypothesis.get("problem", ""),
        hypothesis.get("solution", ""),
        hypothesis.get("target_who", ""),
    ])

    scored = []
    for ins in insights:
        i_text = " ".join([
            ins.get("pain_point") or "",
            ins.get("automation_opportunity") or "",
            ins.get("target_who") or "",
            " ".join(ins.get("tags") or []),
        ])
        sim = _similarity(h_text, i_text)
        scored.append((sim, ins))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [ins for _, ins in scored[:top_n]]


def _build_filter_prompt(hypothesis, candidates):
    """LLM判定用のプロンプトを構築。"""
    h_section = (
        f"## 仮説\n"
        f"- タイトル: {hypothesis.get('title', '')}\n"
        f"- 課題: {hypothesis.get('problem', '')}\n"
        f"- ソリューション: {hypothesis.get('solution', '')}\n"
        f"- ターゲット: {hypothesis.get('target_who', '')}\n"
    )

    k_lines = ["## ナレッジ候補（上位10件）"]
    for ins in candidates:
        k_lines.append(
            f"\n### ID: {ins.get('id')}\n"
            f"- ペイン: {ins.get('pain_point', '')}\n"
            f"- ターゲット: {ins.get('target_who', '')}\n"
            f"- 自動化機会: {ins.get('automation_opportunity', '')}\n"
            f"- 市場ヒント: {(ins.get('market_hint') or '')[:150]}\n"
            f"- タグ: {', '.join(ins.get('tags') or [])}"
        )

    return f"{h_section}\n{''.join(k_lines)}\n\nこの仮説はナレッジで裏付けられますか？"


def _call_deepseek(prompt):
    """DeepSeek APIを呼び出す。"""
    from openai import OpenAI

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": FILTER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=500,
        temperature=0.2,
    )
    return response.choices[0].message.content


def _parse_verdict(raw_text):
    """LLMの出力からJSON判定結果を抽出。"""
    match = re.search(r"```json\s*([\s\S]*?)```", raw_text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{[\s\S]*\"verdict\"[\s\S]*\}", raw_text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def filter_hypotheses(dry_run=False):
    """仮説をナレッジベース + LLM判定でフィルタリング。"""
    if not os.path.exists(HYPOTHESES_FILE):
        print(f"Error: {HYPOTHESES_FILE} が見つかりません。")
        sys.exit(1)

    if not DEEPSEEK_API_KEY:
        print("Error: DEEPSEEK_API_KEY not set.")
        sys.exit(1)

    with open(HYPOTHESES_FILE, encoding="utf-8") as f:
        hypotheses = json.load(f)

    print(f"仮説: {len(hypotheses)}件")

    insights = _fetch_insights()
    print(f"ナレッジインサイト: {len(insights)}件")

    if not insights:
        print("ナレッジが取得できません。フィルタリングをスキップします。")
        return

    passed = []
    failed = []

    for i, h in enumerate(hypotheses):
        title = h.get("title", "?")
        fs = h.get("founder_fit", {}).get("total", "?")

        # Step 1: 2-gram で候補絞り込み
        candidates = _find_candidates(h, insights)

        # Step 2: LLM判定
        prompt = _build_filter_prompt(h, candidates)
        try:
            raw = _call_deepseek(prompt)
            verdict = _parse_verdict(raw)
        except Exception as e:
            print(f"  [{i+1}/{len(hypotheses)}] LLM error: {str(e)[:100]}")
            verdict = None

        if verdict is None:
            print(f"  [{i+1}/{len(hypotheses)}] SKIP (parse error) | {title}")
            failed.append({**h, "filter_verdict": "ERROR", "filter_detail": None})
            continue

        is_pass = verdict.get("verdict") == "PASS"
        confidence = verdict.get("confidence", 0)
        reasoning = verdict.get("reasoning", "")
        best_id = verdict.get("best_match_id")
        best_reason = verdict.get("best_match_reason", "")

        status = "PASS" if is_pass else "FAIL"
        mark = ">" if is_pass else " "

        print(f"  {mark} [{i+1}/{len(hypotheses)}] {status} (conf={confidence:.1f}) fit={fs}/10 | {title}")
        print(f"           {reasoning[:80]}")
        if best_reason:
            print(f"           裏付け(ID={best_id}): {best_reason[:80]}")

        entry = {
            **h,
            "filter_verdict": status,
            "filter_detail": {
                "confidence": confidence,
                "reasoning": reasoning,
                "best_match_id": best_id,
                "best_match_reason": best_reason,
            },
        }

        if is_pass:
            passed.append(entry)
        else:
            failed.append(entry)

    print(f"\n結果: {len(passed)}/{len(hypotheses)} 通過")

    if dry_run:
        print("\n[DRY RUN] ファイル保存をスキップ")
        return

    output = {
        "passed": passed,
        "failed": failed,
        "summary": {
            "total": len(hypotheses),
            "passed": len(passed),
            "failed": len(failed),
        },
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    filter_hypotheses(dry_run=dry)
