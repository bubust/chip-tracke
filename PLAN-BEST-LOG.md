# PLAN-BEST-LOG（/claudex-loop，2026-10-08）
- 主持／計畫／實作：Claude Code（Opus 5.5）；計畫審查與最終程式檢查：Gemini＋Groq（用戶設定，不用 Codex），claude-files/claudex-review2.py
- 計畫：PLAN-BEST.md；審查上限 5 輪；最終檢查 2 輪
- 授權：用戶要「找方法＋做進網站」（AskUserQuestion：勝率高＋期望值正、持有時間都測、補到 5 年、做進網站）
- 資料：scratchpad/best/fetch5y.py 背景下載 2021-10～2026-10 官方日行情（本機，不寫正式站）

## 第 1 輪（10-08 21:23）C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/best/review/r1.json
- Gemini gemini-2.5-flash：APPROVED（F1、F2 low）
- Groq gpt-oss-120b：REVISE（F1 high、F2/F3 medium、F4/F5 low）
Round 1 dispositions (plan updated):
- Groq F1 (multiple testing): ACCEPTED in a practical form. Added (1) a random-entry baseline per exit type with the same year mix: OOS win rate must beat the baseline by >= 5 points and average return must beat it; (2) OOS mean-return 95% CI by month-block bootstrap (2,000 resamples) must exclude 0; (3) report the total number of combos and how many IS top-20 pass OOS. A formal Bonferroni on win rate was not used because the hypotheses are highly correlated (shared signals/exits), the holdout + baseline + bootstrap is the chosen control.
- Groq F2 (portfolio risk sizing / drawdown): ACCEPTED. Added a 1%-risk-per-trade sizing variant (cap 20% per name) next to the 10-slot equal-weight sim; the main pick must have 5-year portfolio max drawdown <= 30%, else the next ranked candidate is used.
- Groq F3 (gap risk): REJECTED with clarification. Exits (including stops) execute at the ACTUAL next-day open price, so the full gap is captured in returns; slippage is an extra cost on top. Using the intraday low to trigger stops would contradict the close-based stop rule the user trades. Plan text clarified.
- Groq F4 (60% threshold arbitrary): REJECTED. The user explicitly chose "win rate >= 60% with positive expectancy" via a question; the plan already reports the best-expectancy alternative and lists the closest 5 if nothing qualifies (no loosening).
- Groq F5 (indicators on raw prices): PARTIALLY ACCEPTED. Raw prices are intentional (must match the user's trading software). Added: measure the share of the main pick's signals within 3 days after an ex-rights/dividend date; if > 5%, add a rule to ignore those signals and recompute.
- Gemini F1 (portfolio drawdown as a criterion): ACCEPTED (see Groq F2).
- Gemini F2 (delisted data continuity): ACCEPTED. Added a data check: the dataset must contain codes that stop appearing before the end, and 3 delisted samples must have no gaps before their last trading day.

## 第 2 輪（10-08 21:44）C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/best/review/r2.json、C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/best/review/r2_groq.json
- Gemini gemini-2.5-flash：APPROVED（沒有 finding）
- Groq gpt-oss-120b：APPROVED（F6～F8 low）
Round 2 dispositions (both reviewers APPROVED; low-priority advice incorporated as clarifications):
- Groq F6 (stop distance formula): ACCEPTED. E3 stop = entry - k*ATR(14, signal day), target = entry + k*ATR. Risk-sizing stop distance = the method's own stop (E3 k*ATR, E5 structural stop); exits without a stop use 2*ATR as the assumed distance.
- Groq F7 (random baseline timing): ACCEPTED. Random entry days are drawn with the same calendar-month distribution as the real signals.
- Groq F8 (expected false positives note): ACCEPTED as reporting only (the report states the number of combos tested and how many IS top-20 pass OOS; no numeric FP estimate because combos are correlated).
- Host addition: 2021-01..09 data downloaded as indicator warm-up only (MA200, 120-bar rule); no trades from that period. Combo count corrected to ~5,000 (46 signals x 3 market filters x 37 exits).
- 計畫 SHA256（含第 2 輪小修）：b4005392f7620291f20377bd73716f7f7396c414569e24e9df2680477e80d939
- 第 3 輪：小修後再送兩位確認（背景跑），研究同步開始

## 第 3 輪（10-09 00:20）C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/best/review/r3.json
- Gemini gemini-2.5-flash：APPROVED（沒有 finding）
- Groq gpt-oss-120b：APPROVED（F1 low）
- Groq F1（ATR 用訊號日會不會偷看）：REJECTED。訊號是第 t 天**收盤後**判斷、第 t+1 天開盤才進場，第 t 天的高低收在下單前就已知道，ATR 算到第 t 天沒有用到未來資料；網站每天 18:00 掃描也是用到當天為止的 ATR，研究跟實作一致。
- **計畫核准**：PLAN-BEST.md SHA256 b4005392f7620291f20377bd73716f7f7396c414569e24e9df2680477e80d939（兩位都 APPROVED，共 3 輪）

## 計畫增修（10-09 凌晨，用戶指示）
- 用戶：「你也可以用我的策略裡面的方式去測試融合」「就盡量測試 中間就別有需要我同意的事情了」→ 加 C 類融合訊號（C1 兩兩配對、C2 策略×個股趨勢、C3 共識、C4 強勢股超賣），篩選規則與三道防運氣關卡不變。
- 加入時間：全部組合還沒跑；只看過引擎測試的 12 個組合（B1_ma200_rsi5／B3_brk55_v2／B4_deep_strong × 4 種出場，用來驗證程式），沒有拿來挑方法。
- 資料修正：官方日行情除權息日漲跌欄是 X（沒有數字），原本「參考價＝收盤−漲跌」行不通 → 改用官方事件表（scratchpad/best/fetch_events.py：TWT49U、TWTAUU、TWTB8U、櫃買 exDailyQ，13,556 筆）。
- 計畫 SHA256：50d0f8485d0db0467689ccf15072abb3ca703b086e3cf11fcc7811f81d7669cd（增修後再送審查）

## 第 4 輪（增修後，10-09 01:00）C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/best/review/r4.json
- Gemini gemini-2.5-flash：APPROVED；Groq gpt-oss-120b：APPROVED（F1～F4 low）
- F1（MA60 上彎會不會偷看）：ACCEPTED 文字補清楚＝今天 MA60 > 5 天前 MA60（程式本來就是這樣）。
- F2（技術分有沒有未來資料）：已確認，deep_verdict.tech_series 只用當天為止的價格（均線、DIF、52 週位置、120 日報酬），沒有財報預估。
- F3（估算的減資日要記錄）：ACCEPTED，全部 5 年只有 6 天用估算（0.0002%），列在報告。
- F4（組合變多要不要提高門檻）：REJECTED，門檻是事先定好的，不在看結果前後改；已先排除訊號 < 400 的配對，三道關卡＋樣本外照舊，報告寫明總組合數。
- 計畫 SHA256：0ab20e2e1074d1b430f1b574fe881a0040cee97fcccbd6f71b953d81b66ffd9f

## 實作進度（10-09 01:00，Claude 實作）
- research/best/：engine.py（資料、除權息、指標、交易模擬、統計）、signals_a.py（現有 18 個策略逐日訊號，520 根視窗＝正式站掃描）、run.py（訊號×濾網×出場全組合、選法、隨機基準、bootstrap、組合模擬）、report.py（中文報告＋網站 summary.json）、verify_live.py（網站版 vs 研究版一致性）。
- 引擎驗證：手算一筆交易報酬一致；台積電 5 年 23 次除權息都抓到；E5 滾動停損重播 vs price_levels.rolling_stop 抽 150 筆 0 不一致；tech_raw 向量版 vs 逐列 0 不一致；小規模全流程（45 組合）跑通。
- 資料檢查：91 檔代號在期末前消失（下市／停牌），抽 3 檔（6172 互億、8488 吉源-KY、4804 大略-KY）首末日之間只缺停牌日。
- 網站：best_strategy.py（訊號、大盤濾網、出場、plan_for、screen_best）、best_routes.py（/api/best/summary、/api/best/watch、18:00 掃描後推播訊號＋持有出場）、scanner／yahoo_price 登記 S_BEST、dashboard 策略按鈕＋說明區＋觀察清單徽章；tests/test_best.py 7 個；pytest 179 passed。CONFIG 等研究結果再填。

## 研究第 1 次結果（10-09 01:36，沒有資料防護）— 保留在 scratchpad/best/results_v1_noguard
- 18,426 個組合（166 訊號：B 28＋C4 3＋A 18＋C1 61 配對＋C2 54＋C3 2；× 3 濾網 × 37 出場）；樣本內合格 112；前 20 名樣本外合格 1：`C1_S_BIAS+S_BREAKBOTTOM|none|E3_t1_s2_20d`（每筆 IS 70.6%／+2.23%、OOS 83.1%／+5.94%，隨機基準 63.3%／+1.12%，bootstrap 下限 +1.01%）→ **組合最大回撤 −35.8%／−34.1% > 30% 沒過** → 照規則沒有主推。
- 原因（事後分析 diag.json）：訊號集中在大跌後（2025-04-10 一天 258 個），崩盤第一波進場連續停損、第二波反彈大賺但帳戶名額只吃得到一小部分。
- 發現資料問題：6669 緯穎 2026-09-02 配股除權（7800→參考價 2615），不還原價格被當成暴跌 → 負乖離／破底翻假訊號、ATR 被撐大（停損算到 1037）。候選方法 1,260 筆裡 74 筆落在這種事件後 60 根內。
- 修正（資料正確性，不是調參數）：單日收盤或開盤比前收跳動 > 10.5%（超過台股 10% 漲跌幅＝一定是除權息／減資／面額變更）之後 60 根（＝季線長度）不出訊號；研究 engine.features gap60、網站 best_strategy.gap_guard 同一套。全部組合重跑，以重跑結果為準。

## 研究最終結果（10-09 02:10，含資料防護）
- 18,426 組合；樣本內合格 116；前 20 名樣本外合格 2（同一訊號 C1_S_BIAS+S_BREAKBOTTOM、none、E3_t1_s2_40d／20d），組合最大回撤 −36.0%／−33.4% 都 > 30% → **照規則沒有主推，不放寬**。
- 網站上線「🔬 研究候選（未全過）」＝最接近過關的 E3_t1_s2_20d（只差回撤 3.4 個百分點）：每筆 全期 77.4%／+4.19%、OOS 83.7%／+6.05%，隨機基準 63.7%／+1.16%，bootstrap 下限 +1.16%；帳戶 年化 +6.2%（10 名額）～+8.8%（1% 風險），同期加權 +23.4%。說明頁有醒目警告＋事後試算（標明不是選方法的依據）。PASSED=False。
- 一致性（verify_live.py）：訊號 300／濾網 100 天／出場 100 筆 0 不一致；pytest 全過；UI 桌機＋手機截圖無錯誤。

## 最終程式檢查（fresh session；builder＝Claude）
- 第 1 輪 C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/best/review/inspect1.json、inspect_groq_A～C.json：Gemini APPROVED；Groq REVISE（A～C 的 findings 逐條驗證後全部 REJECTED，理由見下）；Groq D（dashboard diff）因每日額度用完沒跑，該 diff 由 Gemini 涵蓋。
Inspection round 1 dispositions (all findings verified against the code):
- Gemini gemini-2.5-flash: APPROVED (no findings).
- Groq A-F1 (ATR==0 -> inf in dev/drop): REJECTED. Unreachable inside the pool: a stock with >= 500 lots/day cannot have 14 consecutive bars with zero true range (even limit-locked days have |high - prev close| > 0); research uses the identical numpy semantics, so adding a live-only guard would create a research/live mismatch. The current CONFIG does not use dev/drop.
- Groq A-F2 (empty df -> IndexError): REJECTED. screen_best and watch_plan require len(df) >= 120; if all closes are NaN, n = 0 -> i = -1 -> signal_at returns False and watch_plan returns None (base None).
- Groq A-F3 / B-F4 / C-F6 (style/perf): REJECTED (no behavior change; stops are already rounded to 2 decimals by _fmt).
- Groq B-F1/F2 (missing imports): REJECTED, false positive caused by sending best_strategy.py as two excerpts; the imports are at the top of the file (excerpt 1).
- Groq B-F3 (NaN ATR in plan_for): REJECTED. _fmt returns None for non-finite values, so stop/target become None without exceptions.
- Groq C-F1 (float(cost) ValueError): REJECTED. watchlist.cost is a REAL column validated by the cost API, and watch_plans wraps each stock in try/except (logs and continues).
- Groq C-F2 (entry None into plan_for): REJECTED. plan_for(entry_idx=None) is the documented "signal only" path (status "signal").
- Groq C-F3/F4 (asyncio.run inside a running loop): REJECTED. push_best_signals/exits are only called from _scan_daily_sync, which runs in an APScheduler BackgroundScheduler worker thread with no running event loop (same pattern as the existing check_positions); the HTTP endpoint only calls them with dry=True, which never calls asyncio.run.
- Groq C-F5 (_ymd silent fallback): REJECTED (low impact: falls back to searching the last 10 bars).
- Groq D (dashboard diff): not run — Groq daily token limit (200k) exhausted; the same diff was covered by Gemini (APPROVED).
Post-inspection host changes (need fresh inspection): best_routes.watch_plan only for watchlist items from this method or with cost; with cost, the cost date is the buy day and the signal is the latest one strictly before it; best_strategy dates normalized to YYYYMMDD; screen_best isolates exceptions per stock (_screen_one) so S_BEST errors cannot drop other strategies' results; tests added.
- 第 2 輪 C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/best/review/inspect2.json（檢查第 1 輪後的修改）：Gemini APPROVED；Groq REVISE F1～F3 全部 REJECTED：F1 日期在 _arrays 已統一成 YYYYMMDD 字串（有測試含 YYYY-MM-DD）；F2 大盤資料不足顯示提醒是刻意的；F3 XSS：前端顯示 plan／stop_note／note 都經過 _esc、Telegram 用 html.escape，API 端再跳脫會重複跳脫。
- 檢查輪數用完（2/2）；沒有未處理的接受項。
