# PLAN-LINK-LOG（/claudex-loop 方式，2026-10-09）
- 主持／計畫／實作：Claude Code（Opus 5.5）；計畫審查與最終程式檢查：Gemini＋Groq
- 用戶：「你們討論看看有沒有關聯性」（產業輪動規律）＋股票連動性（龍頭、跟進第二名）＋處置股雙刀（講義：權證小哥 處置神器）；之前已授權中間不用問、做到上線
- 計畫：PLAN-LINK.md；審查上限 5 輪；最終檢查 2 輪

## 第 1 輪（10-09）C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/link/review/r1.json — Gemini REVISE（F1 high、F2/F3 medium、F4 low）；Groq REVISE（F1/F2 high、F3/F4 medium、F5/F6 low）
Round 1 dispositions:
- Gemini F1 / Groq F4 (short leg infeasible for retail; 0.2% too low): ACCEPTED. Primary tests are now long-only and retail-feasible: (i) buy the high-correlation peer at d0 open, (ii) buy the disposed stock after release. The short-leg pair is secondary, only for first-time dispositions (second dispositions require pre-delivered securities for every order), assuming a margin short at d0 open with full collateral; short cost sensitivity {0.2%, 0.5%, 1%}. Put warrants not modeled (no history) and stated.
- Gemini F2 / Groq F1 (current sector map back-filled): ACCEPTED as sensitivity analysis. No point-in-time classification is available; run all sectors and again excluding the categories TWSE created in 2023 (綠能環保, 數位雲端, 運動休閒, 居家生活, 其他); conclusions only where both agree; disclosed on the website.
- Gemini F3 / Groq F2 / Groq F5 (multiple testing, few overlapping events): ACCEPTED. Primary hypotheses fixed: sector H1 RANGE->BULL and H2 EMERGING_LEADER; follow-second F1 with 5-day hold; everything else exploratory. Month-block bootstrap p-values per event type with Benjamini-Hochberg across the family; event types with < 30 events are labeled insufficient and get no trading rule.
- Gemini F4 (report counts per variant): ACCEPTED.
- Groq F3 (Granger / transfer entropy, liquidity tiers): PARTIALLY ACCEPTED. The lead measure is a 1-lag cross-correlation difference (a simple Granger-style check), shown descriptively only; trading use requires the follow-second research to pass. All stocks are already restricted to the liquidity pool (>= 500 lots/day). Transfer entropy rejected as unnecessary for this descriptive use.
- Groq F6 (refresh/caching): ACCEPTED. Disposition/attention lists fetched daily at 18:10 with 30-minute cache; correlations/deviation/lead computed nightly after the price update and stored; stale data shown with its date.

## 第 2 輪（10-09）C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/link/review/r2.json — Gemini REVISE（F1 medium、F2 low）；Groq REVISE（F1 high、F2/F3 medium、F4/F5 low）
Round 2 dispositions:
- Gemini F1 (hypothesis for the long-only peer trade): ACCEPTED. Hypothesis = capital spill-over/substitution: when a hot stock is disposed (batch matching, pre-delivery), speculative money rotates to same-theme, highly correlated, normally tradable peers, which should beat the sector average during the disposition window. Primary version only when the disposed stock has a positive deviation vs the peer (peer relatively cheap, as in the handout); the unconditional version is exploratory. Benchmarks: other sector members' average and random-date same rule.
- Gemini F2 (liquidity filter everywhere): ACCEPTED. All traded stocks must be in the pool on the signal day; the disposed stock is checked on the day before disposition (volume shrinks during disposition; disclosed).
- Groq F1 (BH for follow-second family): ACCEPTED (whole F1-F3 x holding family; disposition family too).
- Groq F2 (short leg): already optional/secondary; labeled "需能融券（進階）" on the site.
- Groq F3 (position sizing/exposure): ACCEPTED. Account sims: 10 slots x 10%, max 100% exposure, max drawdown reported; site suggests <= 10% per position.
- Groq F4 (one-day lag): ACCEPTED, disclosed on the site.
- Groq F5 (methodology disclosure): ACCEPTED, each research box has a "how it's computed" note (period, event count, OOS result, BH-adjusted p, data freshness).

## 第 3 輪（10-09）C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/link/review/r3.json — Gemini APPROVED；Groq APPROVED（無 finding）
- **計畫核准**：SHA256 3f44506e31577e66eb7f8359dae2399126dfc89335047f97d6b1495a61db753a

## 實作與結果（10-09，Claude 實作）
- research/link/：fetch_sectors.py（正式站 34 產業 2,102 檔）、fetch_disposal.py（處置 4,914 筆、注意 43,475 筆，2021-01 起）、sector_study.py、follow_study.py、disposal_study.py、report_link.py。
- 研究時發現正式站產業輪動「歷史列」的波段點用到後 10 天資料（今天那列沒問題）→ 研究改成只用已確認的波段點（跟正式站今天算的一樣）。
- 產業輪動：盤整轉多頭 741 次，之後 20 天超額 +0.21%、勝率 48%（隨機 −0.02%／45%），BH p=0.41；其他狀態也沒有可用優勢（產業指數突破前高 +0.4%、排除新分類 BH p=0.0495 壓線但幅度太小）→ **沒有可交易的規律**。
- 跟進第二名：733 次先發動；主要假設 F1 抱 5 天 樣本內 −0.76%、樣本外 −0.87%、勝率約 3 成，同產業隨機一檔差不多 → **沒有優勢**。
- 處置股：主要假設（處置時買高相關配對股、正偏差）超額 +1.1%、BH p=0.23 不顯著；講義雙刀（空處置股＋多配對）每組 −1.6%～−2.2% → 不建議；最有希望＝出關後買＋負偏差 抱 20 天 +9.6%（84 次、樣本內外都正，BH p=0.13 未確認，探索性）；處置前後每天統計樣本內外一致（第一次處置出關前 2 天 +1.3%、出關後第一天 −1.05%，跟講義相符）。
- 網站：🔗 連動／處置 分頁（個股連動查詢、各產業先發動＋跟進候選、處置股：快被處置／處置中／今天出關＋雙刀候選＋處置前後統計）、K 線「🔗 連動」按鈕、產業輪動成份股連 K 線＋分析；研究結論都標「回測沒有優勢」；沒有通過的不推 Telegram。
- 驗證：連動股相關係數／偏差率 跟手算一致（2408↔2344 0.905／+6.37%、3081↔3163 0.703／+16.8%）；全市場算一次 3 秒；pytest 188 passed；畫面截圖（桌機／手機）無錯誤。

## 最終程式檢查（fresh session；builder＝Claude；base e1a9c3c）
- 第 1 輪：Gemini gemini-2.5-flash REVISE（F1 high、F2/F3 low）C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/link/review/inspect1_gemini.json；Groq：A REVISE、B APPROVED、C REVISE（C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/link/review/inspect_groq_A～C.json）
Final inspection round 1 dispositions:
- Gemini F1 (linkage pool lacks the ex-rights/capital-reduction 60-bar guard): ACCEPTED. linkage._pool now excludes stocks with a >10.5% close or open jump vs previous close within the last 60 bars (same rule as research gap60); price_daily open is loaded; unit test added; pool 745 -> 717 on 2026-10-08.
- Gemini F2 (no Telegram for movers/disposal pairs): REJECTED by design. The plan pushes only research-validated items; both follow-the-second and disposition double-blade failed, so they are shown on the page with "no backtested edge" and not pushed (documented in link_routes docstring).
- Gemini F3 (first-mover definition): REJECTED. The 10-day definition is the pre-registered one used by the research (follow_study.py); clarified in the docstring.
- Groq A-F1 (gap_recent returns a scalar): REJECTED, false. DataFrame.iloc[-60:].any() reduces per column (axis 0) and returns a Series; covered by test_pool_excludes_recent_ex_rights_gap.
- Groq A-F2 (correlation not normalised): REJECTED, false. Columns are centred and divided by their L2 norm, so Z.T @ Z is exactly Pearson; test_corr_matrix_matches_numpy compares with np.corrcoef.
- Groq C-F1 (date format in crash push): REJECTED. taiex_series index is YYYYMMDD strings (regime DB dates stripped of '-', FMTQIK converted); covered by test_crash_today_state.
- Groq C-F2 (unsynchronised refresh flag): ACCEPTED. Replaced with a threading.Lock (non-blocking acquire).
- Groq C-F3 (sanitiser import timing): REJECTED. _clean imports server lazily at request time, when server is already loaded (same pattern as best_routes).
- Groq B (disposal.py): APPROVED.
- 第 2 輪（第 1 輪之後的修改：linkage._pool 除權缺口、link_routes 鎖）：Gemini **gemini-3.5-flash-lite** APPROVED（2.5-flash 當天 20 次免費額度用完、2.5-flash-lite／2.0-flash 已下架）C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/link/review/inspect2.json；Groq 當天 token 額度用完，背景重試中（結果補記）。
