# PLAN-POSITIONS — 觀察模式／持有模式：進場價 −10% 底線＋持股盯盤推播

狀態：計畫（2026-10-05）。主持＋實作：Claude；審查：Gemini + Groq。延續 PLAN-LEVELS.md（關鍵價位）。
用戶原話：「（進場價 −10% 上限）這個我想要兩種，一個是我加入的時候是要觀察這個策略選出來的股價如何，另一種是如果我有買入我打成本價在哪，你在關注」。
用戶決定（AskUserQuestion）：只有「持有」（有填成本價）的股票發 Telegram；觀察中的只在網頁標示。檢查時間：盤中每小時＋收盤後。

## 1. 目標與驗收
1. **觀察模式**（沒填成本價）：參考價＝加入日收盤價（現有 `_added_prices`），停損不低於 參考價 ×0.9。
2. **持有模式**（填了成本價）：參考價＝成本價，停損不低於 成本 ×0.9；網頁顯示持有損益。
3. 持有股：盤中 9～13 點每小時、收盤後 14:40，檢查「跌破停損」「碰到目標價」，發 Telegram；同一股、同一種通知、同一天只發一次。盤中訊息標「預警，收盤確認才算」。
4. 觀察股：網頁上標「已跌破停損」「已到目標」，不推播。
5. 既有關鍵價位規則（PLAN-LEVELS.md 第 8 節）不變；底線只在比原停損高時生效。

## 2. 證據（research/levels/trailing.py，39,537 樣本，40 天，含成本）
| 停損 | 平均 | 最差 5% | 平均最大回撤 |
|---|---|---|---|
| 目前線上規則（第 8 節） | +2.39% | −16.9% | 12.1% |
| 線上規則＋不低於進場價 ×0.9 | +2.15% | −13.2% | 11.4% |
強勢、強勢延伸、拉回延伸、前段、後段結論一致：少約 0.25～0.5 個百分點報酬，最差 5% 改善 3.5～5 個百分點。

## 3. 現況
- 觀察清單：Supabase `chip_watchlist`（stock_id/name/added_at/note/memo）是清單唯一來源；本機 SQLite `watchlist` 表（Fly volume，持久）另存 memo（`/api/watchlist/{sid}/memo` 只寫本機）。`/api/watchlist/summary` 會依 Supabase 補／刪本機列，保留本機欄位。
- `_added_prices(rows)` 從 price_daily 查加入日收盤。
- 關鍵價位：`_levels_for(sid)`（10 分鐘快取）→ `/api/levels/{sid}`、`/api/levels?ids=`；盤中 `_fetch_for_scan` 會抓 Yahoo、含今日即時 K 棒。
- Telegram：`tg_send`（設定分頁或 env TELEGRAM_TOKEN/CHAT_ID）、`push_log` 表（stock_id, signal_emoji, signal_title, pushed_at, ok）。
- 排程：server 啟動時建 APScheduler（觀察清單籌碼 9～13 點整點、15:00；price_cache 14:30 …）。

## 4. 設計

### 4.1 資料
- 本機 SQLite `watchlist` 加欄位 `cost REAL`、`cost_at TEXT`（chip_tracker_v2 既有的 ALTER TABLE try/except 模式）。不動 Supabase schema（PostgREST 不能改表；成本是個人資料，跟 memo 一樣存本機）。
- `POST /api/watchlist/{sid}/cost` body `{cost: number|null}`：null／0／空 → 清除（回到觀察模式）；需 0 < cost < 100000，且有最新收盤價時須在 0.2～5 倍之間（擋打錯小數點，避免假警報）；股票必須在觀察清單內（否則 404）。寫入時記 `cost_at`（台灣時間 ISO 字串，與 added_at 同格式）。受既有 `_auth_guard` 保護（POST）。
- `/api/watchlist/summary` 每列多回 `cost`、`cost_at`。

### 4.2 價位（price_levels.py 新純函式 `apply_entry_floor(lv, entry, kind)`）
- 輸入 compute_levels 結果、參考價、kind（`cost`／`added`）。不改原 dict（回新 dict）。
- `floor = entry × 0.9`。加 `lv["entry"] = {price, kind, floor, pnl_pct}`（pnl_pct＝現價／參考價 −1）。
- 若原停損為 None 或 `floor > 原停損`：停損改成 floor，`basis="entry10"`，label「成本 X −10% 底線，收盤跌破出場」或「加入價 X −10% 底線…」，原停損移到 `stop_before_floor`。
  - 若 `floor ≥ 支撐`：支撐移到 `struct_support`（已有就保留原 struct_support）、`support=None`（維持「有支撐時停損 < 支撐」）。
  - 若 `floor ≥ 現價`：`stop["breached"]=True`、label 前加「已跌破」、rr／downside_pct＝None。
- 否則：停損不變（底線較低，沒有作用），仍回 `entry`。
- rr／downside_pct 依新停損重算（breached 時 None）。
- **實作時發現的設計錯誤（已修正）**：價位每次都用「當下價格」重算，股價跌下去時支撐／停損會跟著往下找新低點，所以「現價 < 現在算出的停損」永遠不成立，通知永遠不會發。改為：
  - `_levels_for` 另外算一次「到前一根 K 棒為止」的價位，只存精簡的 `prev = {date, stop, target}`（不另外快取全部欄位）。
  - `apply_entry_floor(lv, entry, kind="added", prev=None)`（prev 有預設值，舊呼叫相容）的 `alerts`：`stop_ref` ＝ prev 停損與參考價 ×0.9 中「有值者」的最大值（兩者都沒有 → None、stop_hit=False）；`target_ref` ＝ prev 目標；`stop_hit`＝現價（最後一根收盤／盤中即時價）< stop_ref；`target_hit`＝最後一根最高 ≥ target_ref。沒有 prev（資料不足 31 根）時退回用現在的停損／目標。
  - 網頁的「已跌破停損」「已到目標」也用這個（＝今天跌破昨天的停損線），符合實際操作：盯的是昨晚看到的那條線。
  - compute_levels 新增回傳欄位 `high`＝最後一根最高（純新增）。
- floor ≥ 目標價只會發生在 floor > 現價（目標價 > 現價），也就是 breached；此時 stop_hit 為真、target 不影響判斷。

### 4.3 API
- `_watch_ref(sid)`：查本機 watchlist 列 → 有 cost 用 (cost,'cost')；否則有 added_at 用 `_added_prices` 的 (價,'added')；不在清單 → None。
- `/api/levels/{sid}`、`/api/levels?ids=`：`_levels_for`（快取不含個人參考價）之後套 `apply_entry_floor`。
- `GET /api/positions/check?dry=1`：跑一次檢查，回傳會發的通知（dry=1 不發、不記錄），給驗證與除錯；需登入保護（加入 `_AUTH_READ_PREFIXES`）。

### 4.4 盯盤（server.py）
- `check_positions(phase)`，phase＝`intraday`／`close`：
  - 只取有 cost 的觀察清單股票。逐檔 `_levels_for(sid, fresh=True)`（`fresh` 先 `_levels_cache.pop(sid)` 再算，確保用即時價）→ `apply_entry_floor(cost, prev)`，用 `alerts`（對昨天的停損／目標）判斷。
  - `stop_hit`：intraday →「⚠️ 盤中跌破停損 X（收盤確認才算）」；close →「🛑 收盤跌破停損 X，依規則出場」。
  - `target_hit`：「🎯 碰到目標價 X」（兩種 phase 同一種）。
  - 訊息內容：代號 股名、現價、成本與損益%、停損（label）、目標。
  - 通知種類（各自同股同日最多一則）：`stop_warn`（盤中預警）、`stop_close`（收盤確認）、`stop_clear`（盤中有預警、收盤站回停損之上 →「✅ 收盤站回，預警解除」）、`target`（碰到目標，盤中／收盤共用同一種，不重發）。盤中預警與收盤確認刻意是兩種通知：一個提醒盯盤、一個是規則上的出場訊號。
  - 去重：`push_log` 以 `signal_title`＝`pos:{type}:{YYYYMMDD}`（不含 phase）查同股同日，有成功紀錄（ok=1）就不發；發送後寫 push_log（ok 欄位記結果，失敗下次可重試）。
  - Telegram 沒設定 → 只記 log，不例外。
- 排程：盤中 9～13 點每小時第 5 分（避開整點籌碼更新）、收盤後 14:40（price_cache 14:30 之後）；週一～五；台灣時區。

### 4.5 前端（dashboard.html）
- 關鍵價位明細（showLevels）加「持有設定」：成本價輸入框＋儲存＋清除；說明「有填＝持有模式：停損不低於成本 −10%，盤中每小時＋收盤後檢查，跌破停損或碰到目標發 Telegram；沒填＝觀察模式：用加入日收盤價 −10%，只在網頁標示」。顯示目前參考價、底線、損益。
- 觀察清單「關鍵價位」欄：持有中在「標」前加 💼；basis=entry10 時停損旁標「成本−10%」或「加入−10%」；`alerts.stop_hit` → 欄位背景紅、加「已跌破停損」；`alerts.target_hit` → 加「已到目標」。
- 儲存成本後：更新 `_wlData` 的 cost、清掉該股 `_levelsData` 快取並重抓。
- K 線價位線：entry10 時停損線名「成本−10%」／「加入−10%」。

### 4.6 不做
- 不存股數／不算金額損益；不做多筆加碼成本平均；不改 Supabase schema；不推播觀察股。

## 5. 驗證
- 單元：`apply_entry_floor` 各情況（底線生效、不生效、floor ≥ 支撐時支撐移走、已跌破、沒有原停損、rr 重算、不改原 dict、alerts 用 prev 的停損／目標＋底線）；一個「價格一路跌」的序列驗證：用 prev 判斷會觸發 stop_hit，而用現在重算的停損不會（回歸測試，防止再犯）；`check_positions` 用假的 levels／tg_send：盤中預警發一次、同日盤中再跑不重發、收盤確認另發一次、收盤站回發預警解除、目標盤中發過收盤不重發、Telegram 失敗記 ok=0 且下次重試、沒成本的股票不發；驗證 signal_title 格式 `pos:{type}:{YYYYMMDD}` 與訊息含「⚠️ 盤中跌破停損」「🛑 收盤跌破停損」「🎯」；`_levels_for(fresh=True)` 確實重算。
- API：TestClient 測 `/api/watchlist/{sid}/cost` 設定／清除／不在清單 404／不合理值 400。
- 全部 pytest。
- 線上：`/api/levels/{sid}` 有 entry（kind=added）；`/api/positions/check?dry=1` 正常回傳（不發送）。不在用戶真實清單上寫入測試成本。
