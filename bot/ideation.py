"""
ネタ量産エンジン

リアルタイム信号から事業仮説を生成し、ナレッジで補強・市場検証を経て
GitHub Issueに起票する。

パイプライン:
  信号収集 → 仮説生成 [シグナル発] → 市場検証 [検証済] → テストマーケ

Usage (Claude Code内で実行):
  python bot/ideation.py post-signals     # シグナル発仮説をIssue投稿
  python bot/ideation.py validate         # 市場検証対象Issue取得
  python bot/ideation.py validate-post    # 検証済みIssueを投稿
  各コマンドに --dry を付けるとdry run
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
SIGNALS_HYPOTHESES_FILE = "bot/signals_hypotheses.json"
SIGNALS_FILTERED_FILE = "bot/signals_filtered.json"
VALIDATE_FILE = "bot/ideation_validate.json"


def get_db():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ──────────────────────────────────────────────
# post-signals: シグナル発仮説をIssue投稿
# ──────────────────────────────────────────────
def cmd_post_signals(dry_run=False):
    # フィルタ済みファイルがあればそちらを優先
    if os.path.exists(SIGNALS_FILTERED_FILE):
        source_file = SIGNALS_FILTERED_FILE
        with open(source_file, encoding="utf-8") as f:
            data = json.load(f)
        hypotheses = data.get("passed", data) if isinstance(data, dict) else data
        print(f"フィルタ済みファイルから読み込み: {len(hypotheses)}件")
    elif os.path.exists(SIGNALS_HYPOTHESES_FILE):
        source_file = SIGNALS_HYPOTHESES_FILE
        with open(source_file, encoding="utf-8") as f:
            hypotheses = json.load(f)
        print(f"未フィルタファイルから読み込み: {len(hypotheses)}件")
    else:
        print(f"Error: 仮説ファイルが見つかりません。")
        print("先に collect → search → hypothesize → filter を実行してください。")
        sys.exit(1)

    if not isinstance(hypotheses, list):
        hypotheses = [hypotheses]

    db = get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    posted = 0
    skipped = 0

    for hyp in hypotheses:
        name = hyp.get("title", hyp.get("name", "無題"))
        # founder_fit can be nested object or flat score
        fit = hyp.get("founder_fit", {})
        score = fit.get("total") if isinstance(fit, dict) else hyp.get("founder_fit_score")
        action = _get_action(score)

        if action == "archive":
            print(f"  SKIP (archive): {name} (score={score})")
            skipped += 1
            continue

        score_prefix = f"【適合度{score}】" if score is not None else ""
        title = f"{score_prefix}{name} ({today})"

        # Build founder fit detail text
        fit_detail = ""
        if isinstance(fit, dict) and fit.get("rationale"):
            fit_detail = (
                f"| 軸 | スコア |\n|---|---|\n"
                f"| 構築・運用 | {fit.get('build_ops', '-')}/2 |\n"
                f"| 顧客獲得 | {fit.get('acquisition', '-')}/2 |\n"
                f"| ドメイン | {fit.get('domain', '-')}/2 |\n"
                f"| 資産独立 | {fit.get('asset_independence', '-')}/2 |\n"
                f"| ユニエコ | {fit.get('unit_economics', '-')}/2 |\n"
                f"| **合計** | **{fit.get('total', '-')}/10** |\n\n"
                f"{fit.get('rationale', '')}"
            )

        body_parts = [
            f"> シグナル発 | ソース: {hyp.get('signal_source', '---')} | 適合度: {score or '---'}/10 | {today}",
            "",
            "## 仮説サマリー",
            "",
            hyp.get("problem", hyp.get("summary", "")),
            "",
            "---",
            "",
            "## 検出シグナル",
            "",
            hyp.get("signal_evidence", ""),
            "",
            "---",
            "",
            "## 詳細",
            "",
            f"**ターゲット:** {hyp.get('target_who', '')}",
            "",
            f"**課題:** {hyp.get('problem', hyp.get('pain_point', ''))}",
            "",
            f"**ソリューション:** {hyp.get('solution', hyp.get('solution_type', ''))}",
            "",
            "---",
            "",
            "## 本人適合度スコア",
            "",
            fit_detail or hyp.get("founder_fit_detail", "_（採点なし）_"),
            "",
            "---",
            "",
        ]

        # ナレッジ裏付け情報があれば追加
        filter_detail = hyp.get("filter_detail")
        if filter_detail:
            body_parts.extend([
                "## ナレッジ裏付け",
                "",
                f"**判定:** {hyp.get('filter_verdict', '')} (確信度: {filter_detail.get('confidence', '')})",
                "",
                f"**理由:** {filter_detail.get('reasoning', '')}",
                "",
                f"**裏付けナレッジ (ID={filter_detail.get('best_match_id', '')}):** {filter_detail.get('best_match_reason', '')}",
                "",
                "---",
                "",
            ])

        body_parts.append(
            f"_生成: Claude Code (signal) | signal_source: {hyp.get('signal_source', '')}_"
        )

        issue_body = "\n".join(body_parts)

        if dry_run:
            print(f"\n  [DRY RUN] {title}")
            print(f"  Source: {hyp.get('signal_source')}, Score: {score}")
            print(f"  Body: {issue_body[:200]}...")
            posted += 1
            continue

        labels = ["シグナル発"]
        _create_issue(title, issue_body, labels)

        db.table("hypotheses").insert({
            "name": name,
            "insight_ids": [],
            "summary": hyp.get("problem", hyp.get("summary", "")),
            "target_who": hyp.get("target_who", ""),
            "solution_type": hyp.get("solution", hyp.get("solution_type", "")),
            "confidence_score": score or 0.0,
            "status": action,
        }).execute()

        posted += 1
        print(f"  POSTED: {title}")

    print(f"\nDone! Posted: {posted}, Skipped: {skipped}")


# ──────────────────────────────────────────────
# validate: 市場検証対象Issue取得
# ──────────────────────────────────────────────
def cmd_validate(dry_run=False):
    target_labels = ["シグナル発"]
    validated_issues = _fetch_issues_by_label("検証済")

    already_validated = set()
    for vi in validated_issues:
        for label in target_labels:
            for candidate in _fetch_issues_by_label(label):
                if f"#{candidate['number']}" in (vi.get("body") or ""):
                    already_validated.add(candidate["number"])

    all_targets = []
    for label in target_labels:
        issues = _fetch_issues_by_label(label)
        for issue in issues:
            if issue["number"] not in already_validated:
                all_targets.append({
                    "issue_number": issue["number"],
                    "issue_title": issue["title"],
                    "issue_body": issue["body"],
                    "issue_url": issue.get("url", f"https://github.com/{REPO}/issues/{issue['number']}"),
                    "source_label": label,
                })

    print(f"市場検証対象: {len(all_targets)}件 (検証済: {len(already_validated)})")

    if not all_targets:
        print("検証対象のIssueがありません。")
        return

    # ナレッジベースのインサイトも検証の参照材料として含める
    db = get_db()
    result = db.table("knowledge_insights").select(
        "id, target_who, target_industry, pain_point, existing_solution, "
        "automation_opportunity, market_hint, tags, confidence"
    ).execute()

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "targets": all_targets,
        "knowledge_insights_count": len(result.data),
        "knowledge_insights": result.data,
        "validation_criteria": {
            "competitive_gap": "競合の隙 (0-3): 競合なし(3) / 弱い競合のみ(2) / 差別化可能(1) / 大手独占(0)",
            "demand_evidence": "需要の確認 (0-3): 明確(3) / ある程度(2) / 微妙(1) / なし(0)",
            "revenue_viability": "収益成立性 (0-2): 成り立つ(2) / ギリギリ(1) / 非現実的(0)",
            "timing": "タイミング (0-2): 今がベスト(2) / 悪くない(1) / 遅い/早すぎ(0)",
            "threshold_pass": 7,
            "threshold_hold": 4,
        },
    }

    with open(VALIDATE_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nValidation data saved to {VALIDATE_FILE}")
    print(f"  ナレッジインサイト: {len(result.data)}件（検証の参照材料）")
    print(f"\nNext: Claude Code で各IssueについてExa等で競合調査・需要裏取りを実施し、")
    print(f"  結果を {VALIDATE_FILE} の validated_results キーに追加してください。")
    print(f"  完了後、`python bot/ideation.py validate-post` で検証済Issueとして起票。")


# ──────────────────────────────────────────────
# validate-post: 検証済み仮説をIssue投稿
# ──────────────────────────────────────────────
def cmd_validate_post(dry_run=False):
    if not os.path.exists(VALIDATE_FILE):
        print(f"Error: {VALIDATE_FILE} が見つかりません。")
        sys.exit(1)

    with open(VALIDATE_FILE, encoding="utf-8") as f:
        data = json.load(f)

    results = data.get("validated_results", [])
    if not results:
        print("validated_results が見つかりません。Claude Codeで検証結果を追加してください。")
        sys.exit(1)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    posted = 0
    skipped = 0
    closed = 0

    for res in results:
        name = res.get("name", "無題")
        origin_issue = res.get("origin_issue_number")
        market_score = res.get("market_fit_score")
        founder_score = res.get("founder_fit_score")

        if market_score is not None and market_score < 4:
            print(f"  CLOSE (market_score={market_score}): {name}")
            if not dry_run and origin_issue:
                subprocess.run(
                    f'gh issue close {origin_issue} --repo {REPO} --comment "市場検証の結果、市場適合度{market_score}/10のため却下"',
                    shell=True,
                    capture_output=True,
                    encoding="utf-8",
                )
            closed += 1
            continue

        if market_score is not None and market_score < 7:
            print(f"  HOLD (market_score={market_score}): {name}")
            skipped += 1
            continue

        score_prefix = ""
        if founder_score is not None and market_score is not None:
            score_prefix = f"【適合{founder_score}/市場{market_score}】"

        title = f"{score_prefix}{name} ({today})"

        body_parts = [
            f"> 検証済 | 元Issue: #{origin_issue} | 適合度: {founder_score or '---'}/10 | 市場適合度: {market_score or '---'}/10 | {today}",
            "",
            "## 検証サマリー",
            "",
            res.get("validation_summary", ""),
            "",
            "---",
            "",
            "## 競合調査",
            "",
            res.get("competitive_analysis", "_（未調査）_"),
            "",
            "---",
            "",
            "## 需要の裏取り",
            "",
            res.get("demand_evidence", "_（未調査）_"),
            "",
            "---",
            "",
            "## 収益モデル検証",
            "",
            res.get("revenue_model", "_（未検証）_"),
            "",
            "---",
            "",
            "## ナレッジによる補強",
            "",
            res.get("knowledge_reinforcement", "_（該当なし）_"),
            "",
            "---",
            "",
            "## 市場適合度スコア",
            "",
            f"- 競合の隙: {res.get('score_competitive_gap', '---')}/3",
            f"- 需要の確認: {res.get('score_demand_evidence', '---')}/3",
            f"- 収益成立性: {res.get('score_revenue_viability', '---')}/2",
            f"- タイミング: {res.get('score_timing', '---')}/2",
            f"- **合計: {market_score or '---'}/10**",
            "",
            "---",
            "",
            "## 最小反証実験（更新版）",
            "",
            res.get("falsification_test", "_（未設計）_"),
            "",
            "---",
            "",
            f"_検証: Claude Code (market-validation) | 元Issue: #{origin_issue}_",
        ]

        issue_body = "\n".join(body_parts)

        if dry_run:
            print(f"\n  [DRY RUN] {title}")
            print(f"  Origin: #{origin_issue}, Market: {market_score}, Founder: {founder_score}")
            print(f"  Body: {issue_body[:200]}...")
            posted += 1
            continue

        labels = ["検証済"]
        _create_issue(title, issue_body, labels)

        posted += 1
        print(f"  POSTED: {title}")

    print(f"\nDone! Posted: {posted}, Hold: {skipped}, Closed: {closed}")


# ──────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────
def _get_action(score):
    if score is None:
        return "monitor"
    if score >= 8:
        return "promote-to-deep-research"
    if score >= 5:
        return "monitor"
    return "archive"


def _fetch_issues_by_label(label):
    """gh CLI で指定ラベルのIssueを取得"""
    result = subprocess.run(
        f'gh issue list --repo {REPO} --label "{label}" --state open --json number,title,body,url --limit 100',
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        print(f"Error fetching issues: {result.stderr.strip()}")
        return []
    return json.loads(result.stdout)


def _create_issue(title, body, labels):
    """GitHub Issue を gh CLI で作成"""
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(body)
        tmpfile = f.name

    try:
        for label in labels:
            subprocess.run(
                f'gh label create "{label}" --repo {REPO} --color 0E8A16 --description "" 2>/dev/null',
                shell=True,
                capture_output=True,
            )

        safe_title = title.replace('"', '\\"')

        result = subprocess.run(
            f'gh issue create --repo {REPO} --title "{safe_title}" --body-file "{tmpfile}"',
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            issue_url = result.stdout.strip()
            print(f"    Issue: {issue_url}")
            for label in labels:
                subprocess.run(
                    f'gh issue edit {issue_url} --add-label "{label}"',
                    shell=True,
                    capture_output=True,
                )
        else:
            print(f"    Issue creation failed: {result.stderr.strip()}")
    finally:
        os.unlink(tmpfile)


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    dry = "--dry" in sys.argv

    commands = {
        "post-signals": lambda: cmd_post_signals(dry_run=dry),
        "validate": lambda: cmd_validate(dry_run=dry),
        "validate-post": lambda: cmd_validate_post(dry_run=dry),
    }

    if cmd in commands:
        commands[cmd]()
    else:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(commands.keys())}")
        sys.exit(1)
