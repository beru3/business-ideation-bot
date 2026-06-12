@echo off
rem X auto-post (local) - X blocks writes from GitHub Actions datacenter IPs (403),
rem so posting runs on a local PC via Task Scheduler.
rem Requires env vars: HOUREI_X_API_KEY / HOUREI_X_API_KEY_SECRET / HOUREI_X_ACCESS_TOKEN / HOUREI_X_ACCESS_TOKEN_SECRET
cd /d "%~dp0.."
git pull --rebase origin master
node x-bot\post.mjs --account hourei-navi post 1
if errorlevel 1 exit /b 1
git add x-bot\accounts\hourei-navi\posted.json x-bot\accounts\hourei-navi\queue.json
git diff --staged --quiet || (git commit -m "chore: x-bot posted ledger update (local post)" && git push origin master)
rem 投稿結果を Issue #42 に記録（失敗しても投稿自体には影響なし）
node x-bot\log-post.mjs hourei-navi 42
