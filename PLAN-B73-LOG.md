# PLAN-B73 審查紀錄（append-only）

- 2026-10-14 開始。Host＝Claude Code（Opus 5.5）規劃＋實作；審查者依用戶設定用 Gemini＋Groq（claude-files/claudex-review2.py），不用 Codex。最多 5 輪計畫審查、2 輪程式檢查。
- 授權：用戶要「討論怎麼提高勝率、篩選太多沒參考價值」→ 研究＋網站實作＋部署（沿用前幾批）。
- 用戶決定：勝率＝8%/25% 出場；不設上限只排序；預設全部顯示、品質高排前面。

## 計畫審查（只有 Groq 一個審查者成功；Gemini 全部作業失敗＝不算通過）
- Gemini：2.5-flash 今天 20 次額度用完（429）；3.6-flash、flash-latest、3.7-flash 都 503 高負載 → 計畫沒有 Gemini 意見
- 第 1 輪 Groq REVISE：存活者（駁回：官方每日檔含下市股）、多重檢定（接受：BH 校正）、記憶體（接受：逐檔算小表、不建寬表）、每張股數（駁回：台股都 1000 股／張，問題是股／張混用，用 lots_volume）、覆蓋率門檻（駁回）
- 第 2 輪 Groq 跑了兩次（我的包裝在 Gemini 失敗時重跑）：一次 APPROVED、一次 REVISE → 以 REVISE 為準：bootstrap 寫明是「月份 block」（接受）、切點事先固定 ≥ ⌈K/2⌉（接受）、每個條件各一個測試（接受）
- 第 3 輪 Groq APPROVED；low：月份不完整的頭尾月當自己一塊（接受）、橫斷面排名平手規則（改成「門檻值」寫法：F4＝60 日漲幅 ≥ 股票池 70 百分位數值、F9＝≥ 中位數值，沒有排名平手問題）、API 測試（接受）、4,000 檔（台股普通股約 2,000 檔，逐檔算不受影響）
- 原始回應：research/b73/plan_r*.json；處置全文：
  Round 1 dispositions (coordinator). Gemini 2.5-flash failed (daily quota 429) — not counted.
  - Groq F1 survivorship: REJECTED as stated — research uses official per-day market files = every stock listed that day, including later-delisted ones; pool is decided per day with data up to that day; delisted-while-holding exits at last traded close. Clarified in plan section B.
  - Groq F2 multiple testing: ACCEPTED — only one in-sample-selected combo per strategy goes to OOS; OOS bootstrap one-sided p-values across the 20 strategies are Benjamini-Hochberg corrected, pass requires adjusted p < 0.10.
  - Groq F3 memory: ACCEPTED differently — live computation streams per stock (260 bars each) into a ~2,000 x 10 summary table, cross-sectional ranks on that small table; no big wide pivot.
  - Groq F4 lot sizes: REJECTED — all TW stocks trade in 1,000-share lots; the real issue is mixed share/lot units in price_daily, handled by deep_verdict.lots_volume; test added for the mixed-unit case.
  - Groq F5 coverage threshold: REJECTED (not project practice); concrete tests listed.
  - Groq limitation (re-validation): ACCEPTED as a note — rerun every half year manually.
  
  Round 2 (Groq ran twice because my wrapper retried on Gemini failure: one APPROVED, one REVISE — counted as REVISE; Gemini flash-latest and 3.6-flash both 503, 2.5-flash quota exhausted — not counted):
  - Groq F6 (bootstrap method): ACCEPTED as clarification — it is a block bootstrap: blocks = OOS calendar months, resampled with replacement, trades within a month kept together; fixed seed. Not a daily iid bootstrap.
  - Groq F6' (median split chosen after data): ACCEPTED — split fixed in advance: high = score >= ceil(K/2).
  - Groq F7 (tests): ACCEPTED — one synthetic test per flag F1-F9, NaN/zero price, long zero-volume, pass-rule function with fixed inputs, reproducible bootstrap with fixed seed.
- 核准版本 PLAN-B73.md sha256 前 16 碼 1213f2d610c85949（Groq 單一審查者）

## 實作與研究結果（Claude 寫程式）
- quality.py（F1～F9，研究跟網站同一份）、research/b73/run_quality.py、掃描最後一步 quality.annotate、/api/quality/research、策略篩選頁「⭐ 提高勝率」卡、各策略研究區塊、tests/test_quality.py（10 個）
- 實際資料一致性：2026-10-14 研究版（全歷史）vs 網站版（逐檔最近 300 根）1,952 檔 × 9 條件 0 不一致
- **B2 共用品質分沒通過**：沒有條件讓合併勝率 +3 個百分點（最好的「不追高」+1.6／樣本外 +1.8；大盤季線上、格局多頭、月線上揚樣本外反而 −2～−3）→ 計分條件空 → 不做通用排序
- **B1 只有 S10 漲停通過**：不追高＋成交金額 ≥ 中位數 → 樣本外 31.6% → 41.8%、+1.61% → +5.02%、每天 23.3 → 4.6 檔、BH 校正後 p 0.015；各年 4 年較好（2023 −1.1 點），樣本內只 +2 點。接近：週 MACD、平地一聲雷、W 底、假跌破 +3.4～3.8 點沒到門檻。反例：負乖離樣本內挑的條件樣本外 43.0% → 35.7%
- **跟計畫不同的地方**：計畫寫「B1 通過 → 只看建議濾網開關（預設關）」；實作改成「符合的排前面＋標 ⭐ 建議」，因為用戶選「不設上限、只排序、預設全部顯示」；共用品質分沒通過，所以星等欄不做，只有通過的策略（S10）多一欄
- pytest 297 passed；本機 playwright 桌機／手機 0 JS 錯誤、S10 排序正確
- 研究報告 research/b73/REPORT.md

## 程式檢查（審查者沒寫程式）
- Gemini：3.6-flash、flash-latest 503；**gemini-3.7-flash APPROVED**（PLAN＋quality.py＋run_quality.py＋py.diff＋front.diff 全部）。research/b73/insp_g.json
- Groq：py.diff APPROVED；run_quality.py REVISE「f-string 巢狀引號語法錯誤」→ 駁回（ast.unparse 3.12 寫法，研究程式已完整跑完）；quality.py 兩次 json_validate_failed（作業失敗，不算）
