"""
Phase 2: 市場検証スクリプト

シグナル発Issueを取得し、ナレッジ照合・競合調査・需要裏付けを経て
市場適合度スコアリングを行い、結果をIssueにコメント+ラベル変更する。

また、検証済み仮説にはPhase 3用の「マーケブリーフ」を生成する。

Usage (Claude Code内で実行):
  python bot/validate.py fetch          # 検証対象Issue取得 + ナレッジ準備
  python bot/validate.py post           # 検証結果をIssueに反映
  python bot/validate.py post --dry     # dry run

フロー:
  1. fetch → bot/validate_input.json 生成（Issue + 関連ナレッジ）
  2. Claude Code が各仮説を調査・評価（VALIDATE_PROMPT.md参照）
  3. Claude Code が bot/validate_output.json に結果書き込み
  4. post → Issueコメント・ラベル変更・マーケブリーフ保存
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from supabase import create_client

SUPABASE_URL = "https://fkyapyaiqigqdfdyjyop.supabase.co"
SUPABASE_KEY = os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZreWFweWFpcWlncWRmZHlqeW9wIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDQ2ODU1OCwiZXhwIjoyMDk2MDQ0NTU4fQ.hoy8AVtQePHU5TcQHxhBxT736yvtWSNItzpwAdtm5cg",
)
REPO = "beru3/business-ideation-bot"

INPUT_FILE = "bot/validate_input.json"
OUTPUT_FILE = "bot/validate_output.json"
BRIEFS_DIR = "bot/briefs"


def get_db():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ──────────────────────────────────────────────
# fetch: 検証対象Issue + ナレッジ取得
# ──────────────────────────────────────────────
def cmd_fetch():
    """検証待ちIssueとナレッジインサイトを取得し、validate_input.jsonに保存"""

    # 検証待ち = シグナル発ラベル or ラベルなし（#30-34）でオープン
    # 既に「検証済」ラベルが付いているものは除外
    issues_raw = _gh_json(
        f'gh issue list --repo {REPO} --state open --json number,title,body,labels --limit 50'
    )

    # 検証済み・一次生成・ナレッジ発は除外
    skip_labels = {"検証済", "一次生成"}
    targets = []
    for issue in issues_raw:
        label_names = {l["name"] for l in issue.get("labels", [])}
        if label_names & skip_labels:
            continue
        # ナレッジ発は含める（再評価対象）
        targets.append({
            "number": issue["number"],
            "title": issue["title"],
            "body": issue.get("body", "")[:3000],
            "labels": list(label_names),
        })

    print(f"検証対象Issue: {len(targets)}件")

    # ナレッジインサイト取得
    db = get_db()
    result = db.table("knowledge_insights").select(
        "id, target_who, target_industry, pain_point, existing_solution, "
        "automation_opportunity, market_hint, tags, confidence"
    ).gte("confidence", 0.6).execute()

    insights = result.data
    print(f"ナレッジインサイト: {len(insights)}件 (confidence >= 0.6)")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "targets": targets,
        "knowledge_insights": insights,
        "scoring_criteria": {
            "competitive_gap": "競合の隙 (0-3): 直接競合なし=3 / 弱い競合のみ=2 / 差別化可能=1 / 大手独占=0",
            "demand_evidence": "需要確認 (0-3): 明確な証拠=3 / ある程度=2 / 微妙=1 / なし=0",
            "revenue_viability": "収益成立性 (0-2): 明確に成立=2 / ギリギリ=1 / 非現実的=0",
            "timing": "タイミング (0-2): 今がベスト=2 / 悪くない=1 / 遅い/早すぎ=0",
            "total": "合計10点: 7+→検証済, 4-6→保留, <4→却下",
        },
    }

    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n保存: {INPUT_FILE}")
    print(f"\n次のステップ:")
    print(f"  Claude Code で VALIDATE_PROMPT.md に従い各仮説を調査・評価し、")
    print(f"  結果を {OUTPUT_FILE} に書き込んでください。")
    print(f"  完了後: python bot/validate.py post")


# ──────────────────────────────────────────────
# post: 検証結果をIssueに反映
# ──────────────────────────────────────────────
def cmd_post(dry_run=False):
    """validate_output.json の結果をGitHub Issueに反映"""

    if not os.path.exists(OUTPUT_FILE):
        print(f"Error: {OUTPUT_FILE} が見つかりません。")
        print("Claude Code で検証を実行し、結果を書き込んでください。")
        sys.exit(1)

    with open(OUTPUT_FILE, encoding="utf-8") as f:
        data = json.load(f)

    results = data.get("results", [])
    if not results:
        print("results が空です。")
        sys.exit(1)

    os.makedirs(BRIEFS_DIR, exist_ok=True)

    posted = 0
    closed = 0
    held = 0

    for res in results:
        issue_num = res["issue_number"]
        score = res["market_fit_score"]
        verdict = res["verdict"]  # "pass" | "hold" | "reject"

        comment = _build_comment(res)

        if dry_run:
            print(f"\n  [DRY] #{issue_num} → {verdict} (score={score})")
            print(f"  Comment: {comment[:200]}...")
            if verdict == "pass":
                brief = res.get("marketing_brief", {})
                print(f"  Brief: {json.dumps(brief, ensure_ascii=False)[:200]}...")
            continue

        # コメント投稿
        _gh(f'gh issue comment {issue_num} --repo {REPO} --body-file -', input_text=comment)

        if verdict == "pass":
            # ラベル「検証済」追加 + 「シグナル発」「ナレッジ発」除去
            _gh(f'gh issue edit {issue_num} --repo {REPO} --add-label "検証済"')
            _gh(f'gh issue edit {issue_num} --repo {REPO} --remove-label "シグナル発" 2>/dev/null || true')
            _gh(f'gh issue edit {issue_num} --repo {REPO} --remove-label "ナレッジ発" 2>/dev/null || true')

            # マーケブリーフ保存
            brief = res.get("marketing_brief", {})
            brief["issue_number"] = issue_num
            brief["issue_title"] = res.get("issue_title", "")
            brief["market_fit_score"] = score
            brief_path = os.path.join(BRIEFS_DIR, f"brief_{issue_num}.json")
            with open(brief_path, "w", encoding="utf-8") as f:
                json.dump(brief, f, ensure_ascii=False, indent=2)
            print(f"  PASS #{issue_num} (score={score}) → brief saved")
            posted += 1

        elif verdict == "hold":
            _gh(f'gh issue edit {issue_num} --repo {REPO} --add-label "保留"')
            print(f"  HOLD #{issue_num} (score={score})")
            held += 1

        else:  # reject
            _gh(f'gh issue close {issue_num} --repo {REPO}')
            print(f"  REJECT #{issue_num} (score={score}) → closed")
            closed += 1

    print(f"\nDone! Pass: {posted}, Hold: {held}, Reject: {closed}")

    if posted > 0:
        print(f"\nマーケブリーフが {BRIEFS_DIR}/ に保存されました。")
        print("Phase 3 (テストマーケ素材生成) に進めます。")


# ──────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────
def _build_comment(res):
    """検証結果からIssueコメントを組み立てる"""
    score = res["market_fit_score"]
    verdict_map = {"pass": "検証済 (テストマーケへ)", "hold": "保留", "reject": "却下 (クローズ)"}
    verdict_label = verdict_map.get(res["verdict"], res["verdict"])

    parts = [
        f"## 市場検証結果",
        "",
        f"**判定: {verdict_label}** (市場適合度: {score}/10)",
        "",
        "### スコア内訳",
        "",
        f"| 軸 | スコア |",
        f"|---|---|",
        f"| 競合の隙 | {res.get('score_competitive_gap', '?')}/3 |",
        f"| 需要確認 | {res.get('score_demand_evidence', '?')}/3 |",
        f"| 収益成立性 | {res.get('score_revenue_viability', '?')}/2 |",
        f"| タイミング | {res.get('score_timing', '?')}/2 |",
        f"| **合計** | **{score}/10** |",
        "",
        "### 競合調査",
        "",
        res.get("competitive_analysis", "_未調査_"),
        "",
        "### 需要の裏付け",
        "",
        res.get("demand_evidence", "_未調査_"),
        "",
        "### ナレッジ照合",
        "",
        res.get("knowledge_match", "_該当なし_"),
        "",
        "---",
        f"_検証: Claude Code (Phase 2) | {datetime.now(timezone.utc).strftime('%Y-%m-%d')}_",
    ]
    return "\n".join(parts)


def _gh(cmd, input_text=None):
    """gh CLI コマンドを実行"""
    kwargs = {"shell": True, "capture_output": True, "text": True, "encoding": "utf-8"}
    if input_text:
        kwargs["input"] = input_text
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0 and "already exists" not in result.stderr:
        stderr = result.stderr.strip()
        if stderr:
            print(f"    Warning: {stderr[:200]}")
    return result


def _gh_json(cmd):
    """gh CLI コマンドでJSONを返す"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        print(f"Error: {result.stderr.strip()}")
        return []
    return json.loads(result.stdout)


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    dry = "--dry" in sys.argv

    if cmd == "fetch":
        cmd_fetch()
    elif cmd == "post":
        cmd_post(dry_run=dry)
    else:
        print(f"Unknown command: {cmd}")
        print("Available: fetch, post")
        sys.exit(1)
