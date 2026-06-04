"""
検索でリアルタイム信号を収集

signals_raw.json のクエリを検索し、結果を追記する。

検索バックエンド:
  1. Exa Search API (推奨: 安定・CI対応)
  2. Playwright + Google (フォールバック: ローカルテスト用)

Usage:
  python bot/search.py              # 全クエリ検索 (Exa優先)
  python bot/search.py --limit 5    # 最初の5クエリのみ
  python bot/search.py --playwright # Playwright強制
"""
import json
import os
import random
import subprocess
import sys
import time
import urllib.parse

SIGNALS_FILE = "bot/signals_raw.json"
MAX_RESULTS_PER_QUERY = 5
WAIT_MIN = 3
WAIT_MAX = 6

# Exa Search API
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")


# ──────────────────────────────────────────────
# Backend 1: Exa Search API (推奨)
# ──────────────────────────────────────────────
def _search_via_api(queries, limit=None):
    """Exa Search API で検索する。安定・CI向け。"""
    try:
        import requests
    except ImportError:
        print("  requests not installed, falling back to Playwright")
        return None

    if not EXA_API_KEY:
        print("  EXA_API_KEY not set, falling back to Playwright")
        return None

    if limit:
        queries = queries[:limit]

    signals = []
    for i, q_info in enumerate(queries):
        query = q_info["query"]

        try:
            resp = requests.post(
                "https://api.exa.ai/search",
                headers={
                    "x-api-key": EXA_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "numResults": MAX_RESULTS_PER_QUERY,
                    "type": "auto",
                    "contents": {
                        "text": {"maxCharacters": 300},
                    },
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [{i+1}/{len(queries)}] API error: {str(e)[:100]}")
            signals.append({
                "query": query,
                "source_collector": q_info.get("collector", ""),
                "source": q_info.get("source", ""),
                "results": [],
                "error": str(e)[:200],
            })
            continue

        is_tweet_query = "site:x.com" in query or "site:twitter.com" in query
        results = []
        for item in data.get("results", [])[:MAX_RESULTS_PER_QUERY]:
            url = item.get("url", "")
            snippet = item.get("text", "")[:300]
            results.append({
                "title": item.get("title", ""),
                "snippet": snippet,
                "url": url,
                "is_tweet": is_tweet_query or "x.com/" in url,
            })

        signals.append({
            "query": query,
            "source_collector": q_info.get("collector", ""),
            "source": q_info.get("source", ""),
            "results": results,
        })

        n = len(results)
        print(f"  [{i+1}/{len(queries)}] {n} results: {query[:60]}...")

        # Rate limit: be gentle with API
        if i < len(queries) - 1:
            time.sleep(0.5)

    return signals


# ──────────────────────────────────────────────
# Backend 2: Playwright + Google (フォールバック)
# ──────────────────────────────────────────────
def _search_via_playwright(queries, limit=None):
    """Playwright を subprocess で実行し、検索結果を収集する。

    ローカルテスト用。CI では CAPTCHA リスクあり。
    """
    if limit:
        queries = queries[:limit]

    script = _generate_search_script(queries)
    script_path = os.path.join(os.path.dirname(__file__), "_search_worker.py")

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            timeout=600,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        if result.returncode != 0:
            print(f"  Search worker error: {stderr[:500]}")
            return []

        signals = []
        for line in stdout.strip().split("\n"):
            if line.strip():
                try:
                    signals.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return signals
    except subprocess.TimeoutExpired:
        print("  Search worker timed out (10min)")
        return []
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)


def _generate_search_script(queries):
    """Playwright を使った検索ワーカースクリプトを生成する。"""
    queries_json = json.dumps(
        [{"query": q["query"], "collector": q.get("collector", ""), "source": q.get("source", "")} for q in queries],
        ensure_ascii=False,
    )
    return f'''
import asyncio
import json
import random
import sys
import urllib.parse

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

QUERIES = {queries_json}
MAX_RESULTS = {MAX_RESULTS_PER_QUERY}
WAIT_MIN = {WAIT_MIN}
WAIT_MAX = {WAIT_MAX}

async def search_google(page, query_info):
    query = query_info["query"]
    params = urllib.parse.urlencode({{"q": query, "hl": "ja"}})
    url = f"https://www.google.com/search?{{params}}"

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        results = await page.evaluate("""
            () => {{
                const items = [];
                const links = document.querySelectorAll('div#search a[href]');
                for (const a of links) {{
                    const href = a.getAttribute('href');
                    if (!href || href.startsWith('/search') || href.startsWith('#')) continue;

                    let url = href;
                    if (href.startsWith('/url?')) {{
                        const match = href.match(/[?&]q=([^&]+)/);
                        if (match) url = decodeURIComponent(match[1]);
                    }}

                    const heading = a.querySelector('h3');
                    const title = heading ? heading.textContent.trim() : '';
                    if (!title) continue;

                    let snippet = '';
                    const container = a.closest('div[data-sokoban]') || a.closest('div.g') || a.parentElement?.parentElement?.parentElement;
                    if (container) {{
                        const spans = container.querySelectorAll('span, em');
                        const texts = [];
                        for (const s of spans) {{
                            const t = s.textContent.trim();
                            if (t && t.length > 10 && t !== title) texts.push(t);
                        }}
                        snippet = texts.slice(0, 3).join(' ').substring(0, 300);
                    }}

                    items.push({{ title, snippet, url }});
                    if (items.length >= MAX_RESULTS) break;
                }}
                return items;
            }}
        """)

        is_tweet_query = "site:x.com" in query or "site:twitter.com" in query
        for r in results:
            r["is_tweet"] = is_tweet_query or "x.com/" in r.get("url", "")

        return {{
            "query": query,
            "source_collector": query_info.get("collector", ""),
            "source": query_info.get("source", ""),
            "results": results,
        }}
    except Exception as e:
        return {{
            "query": query,
            "source_collector": query_info.get("collector", ""),
            "source": query_info.get("source", ""),
            "results": [],
            "error": str(e)[:200],
        }}


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ja-JP",
        )
        page = await context.new_page()

        for i, q in enumerate(QUERIES):
            if i > 0:
                wait = random.uniform(WAIT_MIN, WAIT_MAX)
                await asyncio.sleep(wait)

            result = await search_google(page, q)
            print(json.dumps(result, ensure_ascii=False), flush=True)

            n_results = len(result.get("results", []))
            print(f"  [{{i+1}}/{{len(QUERIES)}}] {{n_results}} results: {{q['query'][:60]}}...", file=sys.stderr, flush=True)

        await browser.close()

asyncio.run(main())
'''


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def search_all(limit=None, force_playwright=False):
    """signals_raw.json のクエリを検索し、結果を追記する。"""
    if not os.path.exists(SIGNALS_FILE):
        print(f"Error: {SIGNALS_FILE} が見つかりません。先に bot/collect.py を実行してください。")
        sys.exit(1)

    with open(SIGNALS_FILE, encoding="utf-8") as f:
        data = json.load(f)

    queries = data.get("queries", [])
    if not queries:
        print("クエリがありません。")
        return

    effective_limit = limit or len(queries)
    print(f"Searching {min(effective_limit, len(queries))} queries...")

    signals = None
    backend = "playwright"

    if not force_playwright:
        signals = _search_via_api(queries, limit=limit)
        if signals is not None:
            backend = "exa_api"

    if signals is None:
        print("Using Playwright backend...")
        signals = _search_via_playwright(queries, limit=limit)

    total_results = sum(len(s.get("results", [])) for s in signals)
    tweet_results = sum(
        sum(1 for r in s.get("results", []) if r.get("is_tweet"))
        for s in signals
    )

    data["signals"] = signals
    data["search_stats"] = {
        "backend": backend,
        "queries_searched": len(signals),
        "total_results": total_results,
        "tweet_results": tweet_results,
    }

    with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nSearch complete! (backend: {backend})")
    print(f"  Queries searched: {len(signals)}")
    print(f"  Total results: {total_results}")
    print(f"  Tweet results: {tweet_results}")


if __name__ == "__main__":
    limit = None
    force_pw = "--playwright" in sys.argv

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--limit" and i < len(sys.argv) - 1:
            limit = int(sys.argv[i + 1])

    search_all(limit=limit, force_playwright=force_pw)
