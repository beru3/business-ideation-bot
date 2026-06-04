"""
DeepSeek API で検索シグナルから事業仮説を生成

signals_raw.json の検索結果を分析し、事業仮説を生成する。
Supabase の既存仮説と重複チェックを行い、新規のみ出力。

Usage:
  python bot/hypothesize.py            # 仮説生成
  python bot/hypothesize.py --dry      # API呼び出しのみ、ファイル保存しない
  python bot/hypothesize.py --no-dedup # 重複チェックなし
"""
import json
import os
import sys
from datetime import datetime, timezone

SIGNALS_FILE = "bot/signals_raw.json"
OUTPUT_FILE = "bot/signals_hypotheses.json"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Supabase
SUPABASE_URL = "https://fkyapyaiqigqdyjyop.supabase.co"
SUPABASE_KEY = os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZreWFweWFpcWlncWRmZHlqeW9wIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDQ2ODU1OCwiZXhwIjoyMDk2MDQ0NTU4fQ.hoy8AVtQePHU5TcQHxhBxT736yvtWSNItzpwAdtm5cg",
)

MAX_TOKENS = 16000

SYSTEM_PROMPT = """あなたは新規事業アイデア生成の専門家です。
検索結果のシグナル（ツイート、記事、レビュー等）を分析し、
ソフトウェアビジネスの仮説を構造化して出力してください。

## 出力ルール
- JSON配列で出力（```json ... ``` で囲む）
- 各仮説は以下のフィールドを含む:
  - title: 仮説名（具体的・簡潔に）
  - problem: 課題の詳細（検索結果から得た具体的証拠を含む）
  - solution: ソリューション案（MVPレベルで実現可能なもの）
  - target_who: ターゲットユーザー（具体的なペルソナ）
  - signal_source: シグナルの出典（どの検索結果から着想したか）
  - signal_evidence: 根拠となるシグナルの引用・要約
  - founder_fit: 個人開発者の適合度スコア（後述）

## founder_fit スコアリング（各0-2, 合計10点）
- build_ops: 構築・運用の技術的実現性（LLM/API/Web技術で作れるか）
- acquisition: 顧客獲得の容易さ（コンテンツマーケ・SEO・SNSでリーチ可能か）
- domain: ドメイン知識の必要度（低い方が高スコア）
- asset_independence: 資産・在庫不要か（SaaS/ツール型が高スコア）
- unit_economics: 単位経済性（月額課金・LTV高い方が高スコア）
- total: 合計
- rationale: 各軸の簡潔な根拠

## 重要
- 抽象的なアイデアではなく、シグナルから裏付けられた具体的な仮説のみ出力
- 既存の有名SaaSと同じものは出さない（差別化要素を明示）
- 日本市場の中小企業（従業員5-300名）をメインターゲットとする
- 3-5個の仮説を出力
"""


def _fetch_existing_hypotheses():
    """Supabase から既存仮説の名前・サマリーを取得（重複チェック用）。"""
    try:
        from supabase import create_client
        db = create_client(SUPABASE_URL, SUPABASE_KEY)
        result = db.table("hypotheses").select("name, summary").execute()
        return result.data
    except Exception as e:
        print(f"  Warning: Supabase dedup check failed: {e}")
        return []


def _build_dedup_context(existing):
    """既存仮説をプロンプトに含めるためのテキストを生成。"""
    if not existing:
        return ""

    lines = ["## 既出の仮説（これらと重複するアイデアは出さないでください）"]
    for h in existing:
        name = h.get("name", "")
        summary = (h.get("summary") or "")[:100]
        lines.append(f"- {name}: {summary}")
    return "\n".join(lines)


def _build_signal_summary(signals_data):
    """検索結果をDeepSeek用のコンパクトなテキストに変換。"""
    signals = signals_data.get("signals", [])
    if not signals:
        return ""

    parts = []
    for sig in signals:
        query = sig.get("query", "")
        results = sig.get("results", [])
        if not results:
            continue

        parts.append(f"\n### 検索: {query}")
        for r in results:
            title = r.get("title", "")
            snippet = r.get("snippet", "")[:200]
            url = r.get("url", "")
            is_tweet = r.get("is_tweet", False)
            source_tag = "[Tweet]" if is_tweet else "[Web]"
            parts.append(f"- {source_tag} {title}")
            if snippet:
                parts.append(f"  > {snippet}")

    return "\n".join(parts)


def _call_deepseek(prompt):
    """DeepSeek API を呼び出して仮説を生成。"""
    try:
        from openai import OpenAI
    except ImportError:
        print("Error: openai package not installed. Run: pip install openai")
        sys.exit(1)

    if not DEEPSEEK_API_KEY:
        print("Error: DEEPSEEK_API_KEY not set.")
        sys.exit(1)

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
    )

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=MAX_TOKENS,
        temperature=0.7,
    )

    return response.choices[0].message.content


def _parse_hypotheses(raw_text):
    """DeepSeek の出力からJSON配列を抽出。"""
    # ```json ... ``` ブロックを探す
    import re
    match = re.search(r"```json\s*([\s\S]*?)```", raw_text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # ブロックなしでもJSON配列を探す
    match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", raw_text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    print(f"  Warning: Could not parse hypotheses from response")
    print(f"  Raw text (first 500 chars): {raw_text[:500]}")
    return []


def _bigrams(text):
    """テキストから2文字グラムの集合を生成（日本語対応）。"""
    text = text.lower().replace(" ", "").replace("　", "")
    return {text[i:i+2] for i in range(len(text) - 1)} if len(text) >= 2 else set()


def _similarity(text_a, text_b):
    """2つのテキストの類似度を0-1で返す（Jaccard係数、2-gram）。"""
    a = _bigrams(text_a)
    b = _bigrams(text_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_duplicate(hypothesis, existing):
    """既存仮説と重複するかチェック（2-gram Jaccard類似度）。"""
    new_title = hypothesis.get("title", "")
    new_problem = hypothesis.get("problem", "")

    for h in existing:
        old_name = h.get("name") or ""
        old_summary = h.get("summary") or ""

        # タイトル類似度 0.4 以上で重複判定
        title_sim = _similarity(new_title, old_name)
        if title_sim >= 0.4:
            return True, old_name

        # 問題文の類似度 0.3 以上で重複判定
        problem_sim = _similarity(new_problem, old_summary)
        if problem_sim >= 0.3:
            return True, old_name

    return False, ""


def hypothesize(dry_run=False, skip_dedup=False):
    """メイン: シグナルから仮説を生成し、重複排除して保存。"""
    if not os.path.exists(SIGNALS_FILE):
        print(f"Error: {SIGNALS_FILE} が見つかりません。")
        sys.exit(1)

    with open(SIGNALS_FILE, encoding="utf-8") as f:
        signals_data = json.load(f)

    signal_summary = _build_signal_summary(signals_data)
    if not signal_summary:
        print("検索結果がありません。先に bot/search.py を実行してください。")
        sys.exit(1)

    # 既存仮説を取得（重複チェック用）
    existing = []
    dedup_context = ""
    if not skip_dedup:
        existing = _fetch_existing_hypotheses()
        dedup_context = _build_dedup_context(existing)
        print(f"  Existing hypotheses for dedup: {len(existing)}")

    # プロンプト構築
    stats = signals_data.get("search_stats", {})
    prompt_parts = [
        f"# 検索シグナル分析 ({stats.get('queries_searched', '?')}クエリ, {stats.get('total_results', '?')}件)",
        "",
        signal_summary,
    ]
    if dedup_context:
        prompt_parts.extend(["", "---", "", dedup_context])

    prompt_parts.extend([
        "",
        "---",
        "",
        "上記のシグナルを分析し、事業仮説を3-5個生成してください。",
    ])

    prompt = "\n".join(prompt_parts)
    print(f"  Prompt length: {len(prompt)} chars")
    print(f"  Calling DeepSeek API ({DEEPSEEK_MODEL})...")

    raw_response = _call_deepseek(prompt)
    print(f"  Response length: {len(raw_response)} chars")

    hypotheses = _parse_hypotheses(raw_response)
    print(f"  Parsed hypotheses: {len(hypotheses)}")

    # 重複排除
    if not skip_dedup and existing:
        unique = []
        for h in hypotheses:
            is_dup, dup_name = _is_duplicate(h, existing)
            if is_dup:
                print(f"  DEDUP: '{h.get('title', '')}' ~ '{dup_name}'")
            else:
                unique.append(h)
        print(f"  After dedup: {len(unique)} (removed {len(hypotheses) - len(unique)})")
        hypotheses = unique

    if not hypotheses:
        print("新規仮説がありません（全て既出と重複）。")
        return

    for h in hypotheses:
        fit = h.get("founder_fit", {})
        score = fit.get("total", "?") if isinstance(fit, dict) else "?"
        print(f"  - [{score}/10] {h.get('title', '?')}")

    if dry_run:
        print("\n[DRY RUN] ファイル保存をスキップ")
        return

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(hypotheses, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {OUTPUT_FILE}")
    print(f"Next: python bot/ideation.py post-signals [--dry]")


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    no_dedup = "--no-dedup" in sys.argv
    hypothesize(dry_run=dry, skip_dedup=no_dedup)
