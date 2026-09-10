# Chip-Tracker 更新日誌

---

## 2026-09-10

### commit (pending) — fix: 現價改用 TWSE MI_INDEX + TPEX 盤中即時行情
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
