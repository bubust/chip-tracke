---
name: ship
description: 這個專案改完東西之後的收尾：測試、清掉暫存檔、commit、合併到 main 部署到 Fly.io、確認部署成功；也包含「用暫時 GitHub Actions workflow 存正式站快照／打 API」的做法（雲端 session 連不到 qiangni-tactics.fly.dev）。只要工作做完要上線、用戶說「部署」「上線」「合併」「推上去」，或需要看正式站現在的資料、確認線上結果，就用這個 skill。
---

# 收尾、部署、看正式站

正式站只有一台（Fly.io `qiangni-tactics`，東京，512MB，SQLite 在 volume），push `main` 就會部署。別的 session 也會推 main，所以合併前一定先 fetch。

## 1. 檢查
- `python -m pytest tests -q`（約 40 秒，全部要過）。改了前端 JS：`node --check <檔案>`，並更新引用它的 HTML 裡的 `?v=日期代號`（例：`regime-frontend/index.html` 的 `wave.js?v=`、`dashboard.html` 的 `notes.js?v=`），不然手機會吃到舊版。
- 有介面改動可以本機跑 `uvicorn server:app --port 8789`，用 `tests_ui/` 的 playwright 腳本或截圖看一次。
- 本機跑過伺服器會產生 `chip_data/job_log.jsonl`、`warrant_ingest_log.json`、`warrant_scan.json`、`disposal_cache.json`、`link_movers.json`、`unadjust_fix.json`：刪掉。`git status` 確認沒有誤加 `chip_data/` 裡的東西。
- 暫時 workflow（`.github/workflows/*-fetch*.yml`、`*-probe.yml`）和暫存資料（`scratch_probe/`、`research/*/data/*.csv` 被 force add 的）用完要刪：資料用 `git rm --cached`。

## 2. commit
- 訊息：`類型: 白話描述（Bxx）`（feat／fix／research／chore），內文一兩句說為什麼；結尾照 session 提供的署名行。不要寫進任何密碼、token。

## 3. 合併部署（照這個順序）
```bash
git push -u origin <分支>
git fetch origin main
git checkout main && git merge --ff-only origin/main
git merge --no-ff <分支> -m "Merge: 白話描述（Bxx）"
git push origin main                      # 觸發 fly-deploy.yml
git checkout <分支> && git merge --ff-only main && git push origin <分支>
```
- 不 rebase、不 force push、不改寫歷史。push 網路失敗才重試（2、4、8、16 秒）。
- 用 GitHub MCP `actions_list`（`list_workflow_runs`，resource_id `fly-deploy.yml`）確認這次部署 `conclusion: success`；失敗就用 `get_job_logs` 看原因再修。

## 4. 看正式站（存線上快照）
- 雲端連不到正式站。寫一支 `scratch_probe/<代號>_probe.py`（用 httpx 打 `https://qiangni-tactics.fly.dev/...`，把 JSON 存成 `scratch_probe/*.json`），加暫時 workflow（範本 `assets/probe-workflow.yml`），push 分支就會跑、把結果 commit 回來。
- 拉下來看完，把 probe 腳本、快照、workflow 一起刪掉再 commit。

## 5. 安全
- 不要計算、寫進或重複舊的設定密碼或它的雜湊；保護靠 `ADMIN_PASSWORD` secret。
- 需要新的 secret 時，給用戶指令自己設（GitHub repo secret；部署流程會同步 `ADMIN_PASSWORD`、`FINMIND_TOKEN` 到 Fly），不要自己寫。
