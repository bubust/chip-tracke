# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

台股「戰術中心」網站（正式站 https://qiangni-tactics.fly.dev）＋背後的量化研究。

專案 skill 在 `.claude/skills/`：`backtest-research`（回測研究流程）、`follow-fanny`（跟進她的貼文）、`ship`（收尾、部署、存正式站快照）。

## 溝通
- 用戶用繁體中文；回覆、程式註解、文件、commit 訊息都用**繁體中文白話**（少用術語，數字講清楚是點數還是 %）。
- 用戶追蹤 Threads 上的 @fanny55520（台指期波浪數法）。「跟進」＝把她貼文（截圖）的方法做進網站；這類工作的測試叫 `tests/test_bxx_nest.py` 之類。

## 常用指令
```bash
pip install -r requirements.txt               # 研究腳本另外要 numpy；tests_ui 要 playwright
python -m pytest tests -q                     # 全部測試，不連網，約 40 秒
python -m pytest tests/test_b93_tiers.py -q   # 單一檔；加 -k 名稱 跑單一測試
uvicorn server:app --port 8789                # 本機跑網站（tests_ui 預設連這個 port）
python tests_ui/b91_ui.py http://127.0.0.1:8789 [截圖資料夾]   # 介面檢查（playwright，本機跑、不進 CI）
node --check regime-frontend/wave.js          # 改前端 JS 後的語法檢查
```
- 本機跑過伺服器會在 `chip_data/` 產生 `job_log.jsonl`、`warrant_ingest_log.json`、`warrant_scan.json`、`disposal_cache.json`、`link_movers.json`、`unadjust_fix.json`：刪掉，不要 commit（`*.db` 已經 gitignore）。

## 部署、分支、網路
- push `main` → `.github/workflows/fly-deploy.yml` → Fly.io app `qiangni-tactics`（東京、512MB＋swap、**只開 1 台**：SQLite 在 volume `chip_data`）。部署時把 GitHub secrets 的 `ADMIN_PASSWORD`、`FINMIND_TOKEN` 同步到 Fly。
- 在指定的 `claude/...` 分支開發。合併流程：`git fetch origin main` → 本機 main 快轉到 `origin/main`（別的 session 也會推 main）→ `git merge --no-ff <分支>` → push main（會部署）→ 分支 `git merge --ff-only main` 再 push。不改寫歷史。
- commit 訊息格式：`類型: 白話描述（Bxx）`，類型用 `feat`／`fix`／`research`／`chore`。
- **雲端 session 連不到 Yahoo、FinMind、證交所、正式站。** 要抓資料或存線上快照：加一個暫時的 workflow（`on: push` 限定分支＋`paths:` 指到抓資料的腳本），在 GitHub Actions 跑完把結果 commit 回分支；用完把 workflow 和暫存檔刪掉。範本在 git 歷史：`git show b1fc51b`（b94-fetch.yml）、`git show 1c23ff6`（b93-probe.yml 存線上快照）。
- 程式裡的時間都是台灣時間（Docker `TZ=Asia/Taipei`），排程也是。

## 安全
- 登入保護＝`auth.py`＋環境變數 `ADMIN_PASSWORD`（沒設＝不保護）。**不要計算、寫進程式或重複任何舊的設定密碼或它的雜湊。**
- Claude 不能自己寫 secrets；需要設定時給用戶指令（GitHub secret 或 `flyctl secrets set`）。`chip_data/cache.db` 存設定和 Telegram token，不進 git。

## 架構
- `server.py`：FastAPI 單體（約 4,900 行）。lifespan 裡用 APScheduler 排盤中／盤後工作；重工作一律包 `jobs.heavy(name)`（512MB 同時跑會 OOM：同一時間只跑一個，紀錄在 `chip_data/job_log.jsonl`）。
- 主畫面 `dashboard.html`（單一大檔，約 8,700 行）。其他功能是「套件＋前端資料夾」：`<name>/router.py`、`<name>/db.py`（SQLite 在 `chip_data/`）＋`<name>-frontend/`，在 server.py `include_router`、mount 到 `/<name>/static`：warrant、regime（總經）、sector、positioning、relationship、treasury、mna、cb、discuss、tail、notes。
- 前端檔回 `no-cache`＋ETag（`tests/test_frontend_cache.py`）；改 JS 時要一起改 HTML 裡 `?v=日期代號` 的版本號（例：`regime-frontend/index.html` 的 `wave.js?v=…`）。
- 🌊 大盤解析 `wave/`（前端 `regime-frontend/wave.js`）：
  - `engine.py` 純函式：ZigZag（θ＝max(下限, m×ATR%)），只用收完的 K 棒確認轉折（記在 `ci`），`state_at(t)` 保證不偷看；`count_waves` → 主要／替代劇本（浪名、失效價、目標）；`analyze(deg)`。級數：日 K `small/mid/big`，分 K `intra/intra30/intra15`。
  - `levels.py`（支撐壓力區：`build` 日 K、`build_ultra` 分 K）、`intraday.py`（5 分 K → 15／30／60 分 K 各自數浪）、`futdata.py`（台指期連續月，日盤＋夜盤）、`nest.py`（多層浪名＝她的數法：兩種、三種細微脈動、大中小）、`levelmap.py`（價位梯）、`service.py`（組成一份快照 JSON）、`panel.py`（AI 圓桌：Gemini、Groq、Claude，有金鑰才參加）、`stats.json`（研究結果）。
  - `stock_wave.py`：同一套方法用在個股深度分析；`deep_ai.py` 用 Gemini 寫白話，價位只准用系統算好的。
- 選股與回測：`scanner.py`（S1、S2 W底、S_FBD 假跌破…）、`backtest_engine.py`（純函式）／`backtest_service.py`、`best_strategy.py`（研究選出的方法，`tests/test_best.py` 跟 `research/best` 逐日比對）、`fbd_live.py`（盤中假跌破、13:15 尾盤 Telegram）、`course_live.py`。
- 資料來源：Yahoo（`yahoo_price.py`、`price_cache.py`）、證交所／櫃買 openapi、FinMind（台指期，免費額度會用完）、鉅亨即時報價；Supabase 選配（`supabase_store.py`）。

## 研究慣例（`research/<主題>/`）
- `PLAN*.md` 規則先寫死、跑完不改（跑完才補的要寫明「看到什麼才加」）→ `run*.py` → `REPORT*.md`、`results/*.json`。原始資料放 `research/<主題>/data/`（gitignore，用 Actions 抓）。
- 網站和研究共用同一份純函式（例：`wave/engine.py`、`levels.py`），測試比對兩邊一致。
- 回測判準固定：
  - 跟「同樣距離／同樣條件隨便挑」的對照比（每筆配 5 筆），用月份 block bootstrap 2,000 次，多個檢定一起做 BH；
  - 同一根 K 棒看不到先後，一律保守算停損；成本來回 0.02%；
  - 分樣本內／樣本外或分年看；
  - 結果標 ✅（通過）／△（跟隨機差不多，只當參考）／✗。網站上沒通過的一律標 △。
- 每個工作在根目錄一份 `PLAN-Bxx.md`（大的另有 `PLAN-Bxx-LOG.md`）；`CHANGELOG.md` 在當天日期底下最上面加一段；跟進她的貼文時 `notes-frontend/notes.js` 加一筆。
