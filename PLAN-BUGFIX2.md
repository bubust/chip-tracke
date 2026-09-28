# PLAN-BUGFIX2.md
## 七個 Bug 修正計畫

### Goal
修正深度分析、總經面板、權證掃描的七個 UI/資料問題

### Observable Acceptance Criteria
- 友達(2409)籌碼 tab：三大法人顯示非零數字（T86 或 FinMind 有值）
- 基本 tab：市值、52週區間、Beta 至少顯示其中一項
- 財務 tab：友達顯示 EPS/毛利率（非「暫時無法取得」）
- 新聞 tab：多筆新聞按日期降序排列（最新在最上面）
- 總經面板廣度：顯示「淨廣度%」= (上漲-下跌)/總家數×100，範圍 -100~+100，不顯示 100%
- 上櫃指數（OTC）：有數值（非「—」）
- 權證掃描：顯示「N 個標的 | 總成交量 X 張 | 總金額 Y 萬」加總列

---

## Scope 1 — server.py 深度分析三修

### Bug 1: 法人資料全 0（_deep_chip）
**問題**: TWSE T86 fallback URL 舊格式
```
舊: https://www.twse.com.tw/fund/T86
新: https://www.twse.com.tw/rwd/zh/fund/T86
```
**修法**: 更新 URL（server.py line ~1270）

### Bug 3: 財務資料無 fallback（_deep_financial）
**問題**: FinMind 回傳空陣列 `data = []` 時直接 `return None`，不進 Yahoo Finance fallback
**位置**: server.py line 1454-1455
**修法**: `if not data:` 改為 `if not data: raise ValueError("finmind_no_data")`
所以 except block 會觸發 Yahoo Finance fallback

### Bug 4: 新聞不排序（_deep_news）
**問題**: Google News RSS / cnyes / Yahoo 各 source 直接 return，無日期排序
**修法**: 
- 每個 source 在 return 前 `items.sort(key=lambda x: x["date"], reverse=True)`
- Google RSS：已有 `date_str = parsedate_to_datetime(pub).strftime("%Y-%m-%d")`，直接可排序

### Bug 2: 基本tab缺市值等（_deep_fundamental，低優先）
**問題**: Yahoo Finance v10 quoteSummary 在 Render.com 可能 geo-blocked
**修法**: 加 TWSE openapi 備用資料源取「在外流通股」：
`https://openapi.twse.com.tw/v1/opendata/t187ap05_L` (上市公司基本資料含普通股數)
若能取得 shares_outstanding + close_price → 估算市值

---

## Scope 2 — regime/fetcher.py 廣度指標重設計

### Bug 5: 廣度顯示 100%（fetch_twse_market_breadth）
**問題**: `breadth_pct = up / (up+down+flat) * 100`
當 down=0（TWSE 解析失敗或確實極少下跌日）→ 100%

**新定義「淨廣度 Net Breadth」**:
- 公式: `net_breadth = (up - down) / total * 100`
- 範圍: -100（全跌）~ +100（全漲），0 = 持平
- 更能反映多空力道比，不受 flat 家數干擾

**修法**:
1. `fetch_twse_market_breadth` 改寫計算：
   ```python
   net_breadth = round((up - down) / total * 100, 2)
   # 不再存 breadth_pct = up/total*100
   upsert_series(conn, dt_iso, "BREADTH_50MA", net_breadth, "TWSE_MI")
   ```
2. 清舊資料（DB 端）：刪除 BREADTH_50MA >= 99.5 的錯誤記錄
3. wrong_breadth 條件更新：`value >= 99.5 OR value <= -99.5`

**前端調整** (regime-frontend/index.html):
- SERIES_LABELS: `BREADTH_50MA: '淨廣度%'`
- ABS_KEYS（不做%變化，顯示絕對值）√ 已在 ABS_KEYS
- valStr: 顯示 `+57.3%` / `-12.1%`（加正負號）
- interpretSignal: 重設閾值：
  - > +30: 🟢 廣度強勁（多頭）
  - > -30: 🟡 廣度中性
  - ≤ -30: 🔴 廣度偏弱（空頭）
- 進度條 CSS 中心點改為 50%（讓 -100~+100 正確顯示）

---

## Scope 3 — OTC 指數資料源

### Bug 6: 上櫃指數 (OTC) 無資料
**問題**: `^TWOII` Yahoo Finance 無資料（geo-blocked 或 ticker 已變動）

**修法**: 在 `fetch_all()` 後，若 OTC series 今日無資料，嘗試 TPEx openapi:
```
https://www.tpex.org.tw/openapi/v1/TPEX_Indexes
```
回傳結構為日期+各指數收盤。解析 "上市(OTC)加權指數" 欄位。
若失敗，靜默略過（非阻塞）。

**位置**: `regime/fetcher.py` 在 `fetch_all()` 函式後加 `fetch_tpex_otc_index(days=30)` 函式

---

## Scope 4 — 權證掃描 UI 加總

### Bug 7: 掃描沒有加總顯示
**問題**: `renderScanner()` 沒有 summary 統計列

**修法**: 在 `renderScanner()` 的表格上方加一條 summary bar：
```html
<div class="scan-summary">
  📊 <b>N</b> 個標的 ·
  總成交量 <b>X 張</b> ·
  總金額 <b>Y 萬</b>
</div>
```
計算：
- 標的數 = unique underlying_code 個數（Set）
- 總成交量 = sum(r.volume for all rows) 張
- 總金額 = sum(r.turnover for all rows) / 10000 萬

同樣加到 `renderScannerUnderlying()` 的彙總列：
- 顯示 N 個標的 / 認購 X 張 / 認售 Y 張 / 合計 Z 張

---

## Non-Goals
- 不改動 FinMind token 邏輯
- 不引入新 python 套件
- 不修改 K 線圖

---

## Key Decisions
| # | 決策 | 選擇 | 理由 |
|---|------|------|------|
| D1 | 廣度公式 | (up-down)/total*100 | 不受 down=0 影響，範圍對稱有意義 |
| D2 | OTC 備用源 | TPEx openapi | 官方免費不需 token，格式穩定 |
| D3 | 財務 fallback | 拋出 ValueError 觸發既有 Yahoo path | 最小改動 |
| D4 | 舊廣度資料 | 啟動時清除 >= 99.5 的錯誤值 | 避免持續顯示舊錯誤資料 |

---

## Changed Files
1. `server.py` — Bug1: T86 URL；Bug3: financial fallback；Bug4: news sort；Bug2: TWSE shares
2. `regime/fetcher.py` — Bug5: breadth net formula + 清舊資料；Bug6: OTC TPEx fallback
3. `regime-frontend/index.html` — Bug5: 廣度顯示調整（label/threshold/format）
4. `warrant-frontend/app.js` — Bug7: summary bar in renderScanner + renderScannerUnderlying

## Verification
```
手動:
- 友達(2409) 深度分析 → 籌碼/財務 有數字
- 新聞 tab → 最新在前
- 總經面板廣度 → 顯示淨廣度%（非100%）
- 總經面板上櫃指數 → 非「—」（需等下次 regime refresh）
- 權證掃描 掃描tab → 顯示加總 bar
```
