# PLAN-B70 審查紀錄（append-only）

- 2026-10-13 角色：host＝Claude Code（規劃、實作）；計畫審查＝Gemini＋Groq（claudex-review2.py，依用戶設定不用 Codex）；最終程式檢查＝Gemini＋Groq（新 session）
- 模型：Gemini 依 GEMINI_REVIEW_MODEL（預設 gemini-3.6-flash，503／429 時改 gemini-2.5-flash）；Groq openai/gpt-oss-120b
- 授權：計畫＋實作＋部署（push → GH Actions → Fly），用戶 /claudex-loop 指示「討論哪邊需要更正」並逐項要求修改
- 上限：計畫 5 輪、修正 2 輪、程式檢查 2 輪；inspect=on
== Round 1 review log ==
- R1 Gemini gemini-2.5-flash: APPROVED — The plan (PLAN-B70) is comprehensive, addressing key user requests for AI report enhancements, new indicators, and critical bug fixes in the linkage and market ranking pages. The proposed quantitative research (R1, R2, R3) is robust, employing walk-forward validation, two-half + full-sample adoption
  - F1 [low] The research protocols (R1, R2, R3) do not explicitly state whether ETFs are included in or excluded from the stock universe for pattern and level analysis. Given that ETFs can behave differently from individual stocks, 
  - F2 [low] The plan proposes applying 'Hongye's 16 patterns' (originally for daily K-bars) to weekly K-bars without explicit research on their direct transference or potential need for weekly-specific pattern tuning. While R2 will 
  - F3 [low] The plan states that `chip_course` data (including `inst_daily`) will 'refresh to latest trading day when scanning' for the market ranking. If this refresh is triggered synchronously with every API request to `/api/marke
  - F4 [low] The new 'Delisted Stocks Double Blade' (處置股雙刀) tab is introduced as a button in the linkage page layout, but no details regarding its functionality, data sources, or implementation are provided within the plan.
- R1 Groq openai/gpt-oss-120b: REVISE — Plan B70 is comprehensive but has material issues: potential look‑ahead bias and multiple‑testing risk in the research protocol, insufficient statistical validation, incomplete API fallback handling, backward‑compatibility gaps for shortened AI reports, and missing edge‑case coverage (ETFs, new list
  - F1 [high] Walk‑forward validation uses two half‑year periods but evaluates many variants (MA20, MA100, weekly pivots, monthly slope) without correcting for multiple‑testing, risking false‑positive adoption.
  - F2 [high] Weekly K‑bar aggregation for the current week labels "本週到目前" but later uses the same bar for pattern detection, which may incorporate intra‑day data not available at report time.
  - F3 [medium] Gemini quota handling is described, but Google Search quota and failure modes are not fully addressed; a Google Search failure would break the two‑stage news retrieval.
  - F4 [medium] AI report length is reduced from ~5k characters to ≤1.2k characters, which may break UI components that assume longer text blocks or specific section counts.
  - F5 [medium] Market‑ranking page now filters ETFs by default but the exclusion toggle may not work for newly listed ETFs lacking historical volume; new listings also lack MA100 or weekly‑pivot data, leading to nulls or errors.
  - F6 [low] Weekly aggregation and moving‑average calculations assume continuous trading days; holidays can produce gaps that affect ATR and slope calculations.
  - F7 [low] The test plan covers core functions but lacks tests for API failure scenarios, new‑listing edge cases, and UI rendering of shortened AI reports.
- R1 result file: C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/ad7b5c22-2086-4531-86c0-9a91c8c91216/scratchpad/b70_r1.json
Round-1 dispositions (plan updated, see section 8):
Groq F1 multiple testing: ACCEPTED in modified form — fixed pre-registered variant list (7 for R1, 2 for R3), no post-hoc variants/threshold changes, plus monthly block-bootstrap (2,000x) 95% CI lower bound > 0 required in addition to both-halves + magnitude thresholds. No p-values because samples overlap.
Groq F2 partial week: ACCEPTED — research uses completed weeks only; UI shows the in-progress week's pattern without backtest stats.
Groq F3 search fallback: ACCEPTED — stage-1 cached 12h per stock; any stage-1 failure degrades to system news only, report labeled 'no web search'; stage 2 never fails because of stage 1.
Groq F4 UI compat for shorter reports: REJECTED — renderer (_dpMd) is generic markdown, independent of length/sections.
Groq F5 ETF/new listings: PARTIAL — tests added for <30 bars and ETF without volume (ratio blank); REJECTED falling back to MA20 when MA100 missing (would mislabel the MA20/MA100 regime); UI already shows 'fewer than 100 bars'.
Groq F6 holiday forward-fill: REJECTED — moving averages are on trading days (same as charting software); ISO-week aggregation naturally handles short weeks; test added for a 4-day week.
Groq F7 tests: ACCEPTED (API failure mocks, new listing, holiday week).
Gemini F1 ETF universe: ACCEPTED — research excludes codes starting with 00.
Gemini F3 refresh latency: ACCEPTED — refresh in background thread, max 60s, fetch_log skips done days, fallback to latest inst_daily.
Gemini F4 disposal tab: CLARIFIED — existing disposal section moved into a tab unchanged.
== Round 2 ==
- R2 Gemini gemini-2.5-flash: APPROVED — This is a comprehensive and well-structured plan addressing significant improvements in the AI stock analysis, key price levels research, linked stocks page, and market ranking features. The plan demonstrates a strong understanding of quantitative research best practices, including robust methods fo
- R2 Groq openai/gpt-oss-120b: APPROVED — The plan addresses all previously raised concerns, respects the fixed multiple‑testing protocol, handles API failures and quota limits, and adds comprehensive tests for new edge cases. Minor backward‑compatibility impact on the market‑ranking API is noted.
  - F1 [low] The /api/market/scan response schema changes (三大法人合計 now a simple sum, new 连买连卖 fields). External consumers may rely on the previous weighted calculation.
- 兩家 APPROVED；核准綁定 PLAN-B70.md sha256=37d6540b9fe83c22999bedffac0dbde13bab89affcfdf85079e6c7afba6359d5
- R2 Groq F1（low）處置：/api/market/scan 只有 dashboard 與推播用，保留 whale_flow_lots 欄位名（值改為真正三者相加），新增欄位不刪舊欄位

## 研究結果（實作階段，2026-10-13）
- R3 月線斜率（research/course/mslope.py → results/mslope_result.json，40.2 萬樣本）：斜率分組 x20：<0 −0.67%、0～0.4 −0.18%、0.4～1 +0.92%、1～3 +2.19%、>3 +3.46%（兩段都同方向）；預先登錄組合 C3（>1%、乖離 0～3%）x20 −0.11%（1,167 筆）、C5（0～5%）+0.59%（2,677 筆，CI [−1.29, 2.90]）→ 兩個都**未通過** → S_MSLOPE 照用戶要求上線（用 C5），標「⚠ 回測沒有優勢」；觀察清單月斜率欄附「斜率 >1% 本身 +2.19%」說明
- R2 週 K（research/deep/hongye.py --weekly → hongye_weekly_result.json，7 萬週樣本）：週大紅K x20 +3.18%（高檔 +4.98%，兩段都正）；週墓碑線-上漲 −0.97%（高檔 −0.03% vs 高檔基準 +2.35%）；週倒T −2.17%（273 筆）→ 常數 KBAR_W_STATS／BAND_BASE_W
- R1 關鍵價位結合宏爺線（research/levels/hongye_levels.py → hongye_levels_result.json，21,193 樣本、1,423 檔，現行＝price_levels.compute_levels）：7 個版本**全部未通過** → price_levels 不改
  - S_MA20 diff −2.7（CI [−4.3, −1.4]）、S_MA100 +0.6（CI [−2.1, 2.4]；多箱 +3.1 單一格局未驗證、不採用）、S_NEAR −0.5、P_WEEK −1.8（CI [−2.5, −1.0]）
  - X_BULL 每筆 −0.11%、X_BOX −0.25%（最差 5% −22.2% vs −18.1%）、T_WEEK +0.20%（CI [−0.07, 0.46]，未達 +0.3）

## 程式檢查（2026-10-13，pre-build commit 5b5c797，builder＝Claude）
- 第 1 輪（新 session）Gemini 2.5-flash：後端包 REVISE（F1 第 1 段摘要與系統新聞沒合併去重、F2 Google News when:30d 沒有退路）→ 兩點都採納並修正（_news_block 標題前 14 字去重；沒有 <item> 就不帶 when 重查，pubDate 過濾 30 天）；前端包（dashboard.html／notes.js diff）APPROVED
- Groq gpt-oss-120b：3 次都作業失敗（json_validate_failed ×2、max completion tokens ×1）→ **不算通過，程式檢查只有 Gemini 單一審查者**
- 第 2 輪（新 session）Gemini：F1 修正確認；F2 邏輯正確但缺專屬測試（medium）、30 天截止用本機時區（low）→ 都採納：加 test_deep_news_falls_back_without_when、截止日改台灣時間
- 檢查輪數用完（2/2）：上面最後兩個小修（測試＋時區一行）**沒有再經外部檢查**
- 最終：pytest 260 passed；本機截圖（不帶 FINMIND_TOKEN）全市場排行／連動三分頁／觀察清單月斜率／深度分析技術與 AI 分頁／手機版，無 JS 錯誤；AI 報告 3481 中文約 1,022 字、近 30 天消息 5 則都有日期
