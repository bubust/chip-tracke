# Chip-Tracker 更新日誌

---

## 2026-10-02

### feat: 新分頁「🏦 庫藏股」— 追蹤公司買回自家股票（時間、數量、價格區間、執行率）
**資料來源：** 公開資訊觀測站「庫藏股買回資訊彙總」（t35sc09），上市＋上櫃，依董事會決議日分段查詢。
**修改：**
- 新增 `treasury/`（parser / fetcher / db / router）：表頭關鍵字對應欄位（支援 MOPS 兩列表頭、單欄「起~迄」、Big5 CSV），同公司同決議日視為同一次買回，期滿後申報的執行結果覆蓋更新、空值不蓋舊值。
- 每筆欄位：決議日、目的、金額上限、預定買回股數（張）、價格區間、買回期間、是否執行完畢、已買回股數、執行率、已買回金額、平均買回價、佔股本比例、未執行完畢原因。
- 衍生：狀態（進行中／未開始／期滿待申報／已結束）、剩餘天數、現價在買回區間的位置、離價格上限 %、決議日至今漲跌、現價相對買回均價（股價取自 price_daily 快取）。
- API：`/api/treasury/list`、`/stock/{id}`（歷次買回＋平均執行率）、`/active`、`/status`、`POST /refresh`、`POST /import`。
- 排程：每個交易日 18:40 更新近 180 天；資料表空的時候啟動先回補 3 年；連續 3 段連不上就先停止並把原因顯示在畫面。
- 伺服器被 MOPS 擋時的備案：畫面「匯入 CSV／HTML」，或本機跑 `python treasury_sync.py` 抓好推上線。
- 前端（`treasury-frontend/treasury.js`，dashboard 內嵌分頁）：狀態篩選、期間／市場／目的／搜尋／現價在區間內、可排序表格、摘要卡、點列展開歷次買回＋開 K 線＋加觀察清單（來源＝庫藏股）；觀察清單與策略篩選股名旁加 🏦庫藏 標記。
- 測試：`python -m pytest tests/test_treasury.py -q`（8 項）。

### feat: 回測重新設計（PLAN-BACKTEST）— 預設用我的策略、隔日開盤進場、ATR 停損、扣成本、批量真的用策略訊號
**問題：** 回測面板預設跑 MA10 假跌破；「批量回測此策略」拿今天選出的股票去跑 MA10 假跌破，沒用到策略進場條件；收盤價進場、只看收盤停損、重複進場、沒扣成本、沒用還原股價。
**修改：**
- 新增 `backtest_engine.py`（純函式，單股/批量共用）：訊號隔天開盤進場（可選訊號日收盤）、持倉中不重複進場、初始停損 2×ATR(14, Wilder)＋移動停損 2.5×ATR（只上移）＋最多持有 60 天；固定 %、均線（收盤成立隔天開盤出場）、時間停損、停利為選項；盤中高低價觸價、跳空用開盤價、同日停損停利算停損；漲跌停一價到底不進場／出場順延；扣來回 0.585%；未平倉另列不計入統計。
- 成績卡：一句話結論＋期望值、勝率、賺賠比、獲利因子、最大單筆虧損、最大連虧、最大回撤、平均持有天數、同期買進持有對照、權益曲線、出場原因分佈、全部交易明細；少於 10 筆標示樣本太少。
- `yahoo_price._parse_yahoo_json(adjusted=True)` 讀 adjclose；回測一律用還原 OHLC（漲跌停判斷用原始價）。
- 新增 `backtest_service.py`：還原日 K 當日快取、策略 mask 快取（SQLite WAL＋busy_timeout，key 含還原資料 hash；只有背景 worker 寫入）、批量背景單一 worker＋進度輪詢；批量股票池＝近 20 日平均成交金額前 100 大（上限 300），所有交易合併統計；結果依策略參數＋出場/停損/成本＋日期快取。
- `/api/backtest/fbd`、`/api/backtest/strategy-batch` 改用新引擎（舊參數 holding_days / stop_loss / trailing_low_days 仍可用）；指數回測不變。
- 前端：回測面板預設帶入入口策略（策略掃描頁 → 該策略；觀察清單 → 來源欄位；都沒有 → S1），MA10 假跌破移到選單最後；只顯示一張卡。
- 測試：`python -m pytest tests/test_backtest_engine.py -q`（19 項）。

## 2026-09-10

### commit d4332dc — fix: 觀察清單現價改回 Yahoo Finance（與 K 線同源）
**問題：** 一系列 MIS/MI_INDEX 嘗試均失敗（MI_INDEX 是盤後報表、MIS z="-" 部分封鎖、TPEX 全封鎖）。
**突破：** K 線圖的現價一直是正確的，因為它用 Yahoo Finance `regularMarketPrice`（chart meta）。
**修改：** `api_watchlist_prices` 和 `api_watchlist_summary` 改回 `fetch_prices_for_stocks`（Yahoo Finance v8 chart API），與 K 線圖同一來源。
**調查結論：** Yahoo Finance 個別股票查詢從 Render 可連；MIS 對 TSE 股票 z 欄位封鎖；MI_INDEX 是盤後報表非即時；TPEX 全封鎖。

### commit (廢棄系列) — MIS/MI_INDEX/TPEX 各種嘗試
**問題：** 上一版改用 TWSE/TPEX OpenAPI，但這兩個是「昨日收盤」資料，不是盤中即時價；MIS API 的 `z` 欄位盤中對大多數股票仍回傳 "-"（成交前為空），造成「只有少數股票有現價」。
**根本原因：** TWSE OpenAPI (`STOCK_DAY_ALL`) 每日盤後才更新一次，非盤中即時。MIS 按個別股票查詢，部分股票未開始成交時 z="-"，無法全市場覆蓋。
**修改：**
- `server.py` → `_fetch_all_prices()` 改為兩個真正的即時來源：
  - **TSE（上市）**：`TWSE MI_INDEX`（`www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=ALLBUT0999`）→ `data8` 陣列，每筆成交後即更新，盤中最即時
  - **OTC（上櫃）**：`TPEX stk_wn1430`（`www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php`）→ `aaData` 陣列
- MI_INDEX `data8` 欄位：`[代號(0), 名稱(1), 成交量(2), ..., 收盤(8), 漲跌方向(9), 漲跌(10)]`
- 漲跌方向判斷：`color:green` = 跌（取負值）；`color:red` = 漲（取正值）
- change_pct = 漲跌值 / (收盤 - 漲跌值) × 100
- `api_watchlist_prices` / `api_watchlist_summary` 統一使用此 helper，刪除 `_mis_prices()`
- 保留 20s TTL 快取避免頻繁打 API

### commit 29bfb4c — fix: 現價改用 TWSE+TPEX OpenAPI（全市場覆蓋，20s TTL快取）（已被上版取代）
**問題：** MIS API 只回傳已成交股票的即時價，大多數股票 z="-" 造成現價不更新。
**根本原因（事後發現）：** 改用的 TWSE/TPEX OpenAPI 其實是昨日收盤資料，不是真正即時。



### commit c16f58d — fix: summary改MIS價格 + 策略/市場掃描結果localStorage持久化
**問題：** 現價仍顯示 0.00%（summary 端點還在用 Yahoo Finance，Render 被封 IP）；策略篩選和全市場排行結果在頁面重整後消失。
**修改：**
- `server.py` → `api_watchlist_summary()` 改用 TWSE MIS API 抓即時現價（與 `/api/watchlist/prices` 邏輯一致）
- `dashboard.html` → 新增 `lsSaveScreen()` / `lsLoadScreen()` / `lsSaveMkt()` / `lsLoadMkt()`
- 策略全市場掃描完成後自動存入 localStorage
- 全市場排行掃描完成後自動存入 localStorage
- `init()` 讀回 localStorage，頁面重整後自動還原掃描結果

---

### commit ae864fe — fix: 從策略加入清單時正確儲存來源標籤
**問題：** 從策略篩選頁「+ 加入清單」，若股票已在清單裡，`INSERT OR IGNORE` 不更新 note，導致「來源」顯示「點擊編輯」。
**修改：**
- `server.py` → `api_add_watchlist()` 改為：新股票 INSERT；已存在股票且帶有策略名稱時 UPDATE note（同步 Supabase）
- `dashboard.html` → `addFromMarket()` 已存在股票時更新 `_wlData` cache 中的 note，toast 顯示「已更新來源」

---

### commit 80f82a6 — fix: 現價自動刷新改用 TWSE MIS 即時報價
**問題：** `/api/watchlist/prices`（自動刷新端點）用 Yahoo Finance，Render.com IP 被封，每次回傳空結果，現價不動。
**修改：**
- `server.py` → `api_watchlist_prices()` 改用 `mis.twse.com.tw/stock/api/getStockInfo.jsp`
- 上市（twse）→ `tse_XXXX.tw`；上櫃（tpex）→ `otc_XXXX.tw`
- 盤中取 `z`（成交價）；盤後/未開盤取 `y`（昨收參考價）

---

## 部署方式
push 到 GitHub main branch → Render 自動部署（約 2-3 分鐘）
