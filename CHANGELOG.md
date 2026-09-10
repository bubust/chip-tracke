# Chip-Tracker 更新日誌

---

## 2026-09-10

### commit 29bfb4c — fix: 現價改用 TWSE+TPEX OpenAPI（全市場覆蓋，20s TTL快取）
**問題：** MIS API 只回傳已成交股票的即時價，當天還沒成交的股票顯示 0.00%，造成「只有部分股票會跳現價」。
**根本原因：** MIS 的 `z`（成交價）欄位在股票尚未成交時為 "-"，fallback 用昨收 `y` 計算漲跌 = 0%。
**修改：**
- 新增模組級 `_fetch_all_prices()` helper：同時呼叫 TWSE OpenAPI（上市）+ TPEX OpenAPI（上櫃），一次拿全市場現價 + 漲跌幅
- 20 秒 TTL 快取（`_PRICE_ALL`）：多個端點共用，避免每次刷新都打 API
- `api_watchlist_prices` 和 `api_watchlist_summary` 統一使用此 helper
- TWSE/TPEX OpenAPI 特點：政府官方、Render 不封鎖、盤中每 5-20 秒更新、有真正的漲跌幅欄位 `Change`



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
