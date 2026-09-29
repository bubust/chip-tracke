# Plan: 三項 Bug 修正

**Host:** Claude Code | **Builder:** Claude | **Inspector:** Gemini+Groq

---

## Goal

修正用戶回報的三個問題：
1. 假跌破策略移到第二個位置
2. 權證掃描器找到 0 筆（TWSE geo-blocking）
3. 帶入 K 線圖非常久（CDN 慢 + 未用本地快取）

---

## Fix 1 — 假跌破移至第二個策略

**File:** `scanner.py` 行 30-47

**現況：** S_FBD 在 STRATEGIES dict 第 9 位（S_PB 後面）
**修法：** 將 S_FBD 移到 S1 之後（第 2 位）

```python
STRATEGIES = {
    "S1":       "雙MACD選股（多）",
    "S_FBD":    "假跌破買進",          # ← 移到第 2
    "S1_SHORT": "雙MACD選股（空）",
    "S2":       "二次確認買進（W底）",
    ...
}
```

---

## Fix 2 — 權證掃描器 0 筆（geo-blocking fallback）

**File:** `warrant/router.py` 行 121-172

**根因：** Render.com 境外 IP 被 TWSE geo-block → `fetch_twse_daily()` 回 HTML → `[]`
→ `twse_vol` 空 → 所有 2000 支權證全 skip

**修法：**
- 在 `fetch_twse_daily()` 中，加入 `openapi.twse.com.tw` 作為第二個嘗試 URL（openapi 較不被封鎖）
- 在 router.py，當 `twse_vol` 仍空時，以 DB 的 warrants 表作為 fallback：
  - 直接回傳 `issued_lots >= 1000` 且未到期的全部活躍權證，不過濾 volume
  - 在 scanner cache 的 `mode` 欄位標記 `"盤外(無量能資料)"`

---

## Fix 3 — K 線圖載入慢

**Files:** `dashboard.html`

**根因：**
1. `_loadLWC()` 從 `unpkg.com` 載 LightweightCharts JS — 境外 CDN 慢
2. `api_stock_ohlcv` 每次直接打 Yahoo Finance，沒用本地 price_daily 快取

**修法：**
1. `_loadLWC()` 改先試 `jsDelivr`（台灣 CDN 速度快），加 10 秒 timeout，失敗後退回 unpkg
2. `api_stock_ohlcv` 先嘗試 `price_cache.get_stock_ohlcv(stock_id, days=730)` — 如有資料且在 4 天內直接回傳；快取缺才打 Yahoo Finance

---

## Acceptance Criteria

1. 策略筛选 tab 中，假跌破排第 2 個
2. 權證掃描器盤外時，即使 TWSE geo-blocked 也顯示有結果（fallback 模式）
3. 點擊個股打開 K 線圖，應在 3 秒內顯示圖表（有本地快取的情況下）

---

## Non-goals

- 不修改假跌破的判斷邏輯
- 不更換 LightweightCharts 版本

---

## Verification

- [ ] `scanner.py` STRATEGIES dict 確認 S_FBD 在第 2 位
- [ ] `warrant/flow.py` `fetch_twse_daily()` 有 openapi fallback
- [ ] `warrant/router.py` twse_vol 空時使用 DB fallback
- [ ] `dashboard.html` `_loadLWC()` 使用 jsDelivr 並有 timeout
- [ ] `server.py` `api_stock_ohlcv` 先查 price_daily 再查 Yahoo
