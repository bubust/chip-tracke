# PLAN-B75 審查紀錄（/claudex-loop）

- 日期：2026-10-21
- 角色：主持／規劃＝Claude Code（Opus 5.5）；計畫審查＝Gemini＋Groq（記憶 feedback_claudex_loop_reviewers：不用 Codex）；實作＝Claude；最終程式檢查＝Gemini＋Groq（新的審查呼叫）
- 模型：Gemini 依 GEMINI_REVIEW_MODEL（預設 gemini-3.6-flash，503 時換 gemini-flash-latest）；Groq openai/gpt-oss-120b（精簡版計畫，因 8,000 TPM，且跟 MyAlbo 正式站共用每日額度 → 最多 2 輪）
- 範圍：PLAN-B75.md（轉折點、超短線 30／60 分 K、台指期版本、期貨＋籌碼綜合研判、融資增減、過熱恐慌上移）
- 授權：用戶以 /claudex-loop 要求實作；沿用過去批次流程（測試 → 推 main → GitHub 自動部署 Fly）
- 輪數上限：計畫 5 輪、修正 2 輪、程式檢查 2 次
- 用戶決定：失效點「你們討論一個合理的處理方式，現在的如果有問題就換掉」；超短線模式；整頁切換加權／台指期；先回測有效的才算；追加融資增減

## 第 1 輪（計畫）
- Groq（精簡摘錄 §2、§3.2～3.5、§6）：REVISE；原始輸出 reviews_b75/plan_r1.json
- Gemini 3.6-flash 503 → gemini-flash-latest：REVISE；原始輸出 reviews_b75/plan_r1_gemini.json
- Gemini gemini-3.6-flash：作業失敗 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand 

### Groq openai/gpt-oss-120b：REVISE
The upgrade introduces valuable features but contains several material concerns that must be addressed before production. Key issues include potential look‑ahead bias in the night‑session handling, statistical‑testing rigor for the pre‑registered selection criteria, continuous‑contract roll logic, timezone consistency, resource safeguards, error‑handling robustness, UI clarity for non‑technical users, and missing automated test coverage. Resolve these points and provide concrete mitigation strategies to obtain approval.
- [high] F1 3.2: Night‑session timing (15:00 T‑1 → 05:00 T) is treated as part of trading day T, but K‑level calculations (especially K3 which waits for i+3 closes) may use data that is not available until after the decision point, creating look‑ahead bias. → Compute K‑levels only after the relevant 5‑minute bar has closed; for intraday alerts use a provisional estimate that is replaced by the confirmed value after the i+3 bar. Document the exact cut‑off time and ensure no future price is used in real‑time signals.
- [medium] F2 2.3: Selection of the ‘best’ key level is based on the highest continuation‑rate minus a placebo set, but multiple thresholds (ATR ranges, percentile windows) are explored without explicit correction for multiple testing, risking data‑snooping. → Apply a pre‑registered multiple‑testing correction (e.g., Bonferroni or Benjamini‑Hochberg) across all candidate configurations, and keep the final rule‑set frozen before out‑of‑sample evaluation. Report the adjusted p‑values in the research documentation.
- [medium] F3 3.2: Continuous‑contract aggregation selects the month with the largest combined day + night volume each session. This can cause abrupt roll‑overs and price gaps that may distort ZigZag thresholds. → Implement a deterministic roll rule (e.g., roll when the front‑month volume falls below 30 % of the next month) and apply a price‑adjustment factor to smooth the transition. Record the roll dates in the database for audit.
- [medium] F4 3.4/3.5: Mixed time representations (epoch seconds, Taiwan local time, cp950 encoding) risk inconsistent timestamps, especially when aggregating 5‑minute bars from different sources. → Standardise all timestamps to UTC internally, convert to Taiwan time only for UI display. Validate that the epoch‑second field in `bars5` matches the start of the 5‑minute interval after conversion. Add unit tests for timezone conversion.
- [low] F5 3.5: Streaming TAIFEX zip files without loading the whole file is correct, but there is no explicit guard against exceeding the 512 MB VM limit if many large files are processed concurrently. → Add a memory‑usage monitor that aborts the import if the process exceeds ~400 MB and logs a clear error. Consider processing files sequentially with a configurable concurrency limit.
- [medium] F6 3.4: Scheduled jobs (premarket, intraday_close, night_close, chips) lack defined retry or fallback mechanisms; a temporary API outage could leave the database stale. → None
- [None] None : None → Wrap each job in a retry wrapper with exponential back‑off (max 3 attempts). On permanent failure, write a status flag and send an alert (e.g., Telegram) so operators can intervene. Also store the last successful run timestamp for each pipeline.
- [low] F7 2.4/6.2: Terminology such as “轉弱點” / “轉強點” may be opaque to non‑expert users, and the UI does not specify how confidence (e.g., statistical significance) is communicated. → None
- [None] None : None → Add hover‑tooltips explaining each term and colour coding. Show the 95 % CI or a simple “significant / not significant” badge next to the continuation‑rate text.
- [medium] F8 Overall: The plan does not describe automated test coverage for the new data pipelines, statistical modules, or UI components. → None
- [None] None : None → Create unit tests for: (a) zip‑stream parsing and aggregation logic, (b) K‑level calculation with simulated data, (c) statistical bootstrap routine, (d) end‑to‑end integration test that mocks external APIs. Aim for ≥80 % coverage of new code.
- coverage：The review covers the provided excerpt (sections 2, 3.2‑3.5, and 6) and evaluates the core functional, statistical, and operational aspects introduced in the plan.
- limitations：Assessment is limited to the excerpt; any omitted sections (e.g., detailed UI mock‑ups, deployment scripts, or security considerations) were not evaluated. The verdict assumes the existing B74 codebase remains unchanged and functional.

### Gemini gemini-flash-latest：REVISE
The plan is thorough and well-aligned with user requirements, but suffers from several material quantitative and architectural defects: (1) contract-roll jump distortion contaminating the night-return regression in F1, (2) look-ahead bias in evaluating chip forward returns from Day T's close when data is published hours later, (3) cache collision in service.py which currently stores global singletons without a symbol key, (4) session-timing logic that will treat TX night sessions as off-hours, and (5) ambiguity in beta selection between gap and r1 targets for the opening estimate.
- [high] F1 6.1 研究 R-F (F1 夜盤報酬定義與結算日換月): On monthly contract settlement day (3rd Wednesday), the day session trades the expiring front month (TX_front), while the night session starting at 15:00 trades the new front month (TX_next). Calculating night session return as Close_night(T) / Close_day(T-1) - 1 without adjusting for the 50-300 point contract spread will inject artificial jumps into F1 twelve times a year, severely distorting the OLS regression, beta, and out-of-sample R². → Enforce same-contract return calculation across rolls: calculate F1 on roll days as TX_next_night_close / TX_next_day_close - 1 (using the next month's day session close as the denominator), or drop settlement-day transition nights from the regression sample.
- [high] F2 6.1 研究 R-F (籌碼指標 fwd5/fwd20 評估起點的看前偏誤): Chip features for day T are published between 15:00 and 21:40 (margin balance around 21:30). Measuring fwd5 and fwd20 from Close(T) (13:30) introduces look-ahead bias because an investor cannot execute at 13:30 based on data released hours later. The return from Close(T) to Open(T+1) is contaminated by overnight moves occurring before or during chip dissemination. → For chip features published post-market on day T (F2, F4, F5, F7), compute forward returns starting from Open(T+1) or Close(T+1). Alternatively, strictly lag all chip metrics by one trading day when modeling Close-to-Close returns.
- [high] F3 5. 台指期版本 & service.py 快取機制: In existing service.py, _cache and _base are single global dictionaries without a symbol key. Adding sym=TX alongside sym=TWII without partitioning the cache will cause race conditions and cache thrashing where TX overwrites TWII (and vice versa) for concurrent client queries. → Refactor _cache and _base in service.py into dictionaries keyed by symbol (e.g., _cache[sym] and _base[sym]), ensuring complete state isolation between TWII and TX snapshots.
- [medium] F4 3.4 排程 & 5. 台指期版本 (Session 判斷與即時輪詢快取): Existing service.py relies on D.is_tw_session(), which only returns True between 09:00 and 13:30. During the TX pre-market (08:45-09:00) and night session (15:00-05:00), is_tw_session() returns False, causing snapshot() to enter the 600-second off-session cache and suppress live futures polling. → Parameterize is_tw_session(sym='TWII') so that when sym='TX', it recognizes both the day session (08:45-13:45) and night session (15:00-05:00) as active, applying the 120s TTL and invoking live futures quotes.
- [medium] F5 6.1 & 6.2 網站呈現 (開盤參考與隔天方向的迴歸標的混淆): Section 6.1 specifies estimating F1 against both r1(T) (Close-to-Close) and gap(T) (Open-to-PrevClose). Section 6.2 specifies using F1 beta for '今天開盤參考', but does not clarify which beta is saved. Using the r1 beta for opening reference will overestimate opening jump by conflating it with full-day intraday drift. → Explicitly designate that the beta for gap(T) is stored and used for '今天開盤參考' (estimated open), while the beta for r1(T) is strictly reserved for the next-day direction indicator.
- [medium] F6 3.4 & 3.5 期交所逐筆檔回補與 512MB 記憶體防護: If chip_data/wave.db is placed on an ephemeral container path, every deployment or VM restart will trigger background downloading and decompression of 30 days of TAIFEX tick zip files (>1.4 GB uncompressed text). This poses CPU starvation and memory spike risks on a 512MB instance. → Ensure chip_data/wave.db is mounted on a persistent volume. Implement a single-pass streaming parser using a compact in-memory dict {(month, bar_5m): [o, h, l, c, v]} to aggregate bars without multiple passes or large memory allocations, and skip dates that already exist in bars5.
- [low] F7 3.3 資料表 (opt_f_bull 欄位資料源): The plan defines opt_f_bull as Foreign (Buy Call - Sell Call) - (Buy Put - Sell Put) amount, but does not clarify whether it extracts daily transaction amounts (成交金額) or open interest amounts (未平倉契約金額). A 60-day z-score requires open interest amounts, as transaction amounts represent high-variance daily flow. → Explicitly specify in §3.3 that opt_f_bull uses TAIFEX/FinMind open interest amount (未平倉金額) rather than daily trading transaction amount (當日成交金額).
- coverage：Reviewed all 13 sections of PLAN-B75 against existing service.py, levels.py, and engine.py, focusing on look-ahead bias, futures contract rolling, trading session boundaries, statistical gating criteria, cache architecture, and Fly.io 512MB operational constraints.
- limitations：Live API schemas for cnyes (鉅亨) charting endpoints could not be tested for live session rollover behavior; verification relies on published TAIFEX calendar specs.

### 處置
Round 1 dispositions (coordinator):
Gemini:
- G-F1 roll distortion in night return: ACCEPTED. §3.2: night rows store ref_close = SAME contract's previous day-session close; night_ret uses it. Live uses cnyes reference price.
- G-F2 chip publication timing: ACCEPTED (modified). Post-close factors F2-F7: (a) next-day target = r(T+1) residual after removing what night return F1(T+1) explains (incremental value beyond night session); (b) 5/20-day targets start from Open(T+1).
- G-F3 cache keyed by symbol: ACCEPTED (§5).
- G-F4 session detection per symbol: ACCEPTED (§5, D.in_session(sym)).
- G-F5 gap beta vs r1 beta: ACCEPTED (§6.1/6.2).
- G-F6 persistent volume / single pass: ACCEPTED as clarification (§3.4/3.5; volume already mounted at /app/chip_data).
- G-F7 option OI amount: ACCEPTED (§3.3).
Groq:
- Q-F1 k3 confirmation look-ahead: ACCEPTED as clarification (§3.2: only closed bars confirm pivots; partial bar = price only). Already k3 needs i+3 close.
- Q-F2 multiple testing in key-level selection: ACCEPTED: BH across the 9 candidate x mode tests; bands/candidates pre-registered, not tuned.
- Q-F3 roll rule + price back-adjustment: REJECTED. Back-adjusting would make support/resistance prices non-tradable historical prices; max-volume roll is deterministic and contract is stored per row. Research night-return distortion handled by G-F1.
- Q-F4 timestamps: ACCEPTED as tests; bars5.ts is epoch seconds (UTC by definition), Taipei conversion only at aggregation/display.
- Q-F5 memory monitor abort: REJECTED (sequential single-file streaming with a lock is sufficient; peak memory is the per-file dict of ~2,000 5-min bars).
- Q-F6 job retry/alerts: PARTIAL: every source uses mark() (UI shows failing sources), cnyes retry once, missed days backfilled from TAIFEX zips at 16:30. No Telegram alerts (avoid spam).
- Q-F7 terminology/significance badge: ALREADY in plan (§2.4 plain-language text and significance wording; §7 every number has one plain line).
- Q-F8 tests: ALREADY in §11 (excerpt did not include it). 80% coverage target rejected.


## 第 2 輪（計畫，只送 Gemini）
- 原始輸出 reviews_b75/plan_r2_gemini.json

### Gemini gemini-flash-latest：REVISE
整體架構嚴密且完整消化了第一輪審查意見（夜盤基準價鎖定同一月份消除結算跳空、收盤後籌碼目標改測夜盤殘差與開盤起算、512MB 單檔逐行串流解析、多重檢定預先登記 BH 校正）。但在分 K 時區繪圖、夜盤跨日與週末交易時段判定上存在兩項實作型實質瑕疵，需於實作前校正以免盤中時段快取失效與前端時間軸偏移。
- [medium] F1 §4.1, §7: LightweightCharts 的時間軸處理存在時區雙重累加風險。若 bars5.ts 為 UTC epoch 秒數，前端直接對時間戳 +8 小時（+28,800 秒），而 LWC 預設的 tick/tooltip 格式化函式會讀取瀏覽器本地時區（台灣用戶為 UTC+8），將導致 09:00 開盤 K 棒在台灣瀏覽器上被顯示為 17:00（累加成 UTC+16）；若非台灣時區用戶則顯示混亂。 → 維持傳遞原始 UTC epoch 秒數至前端，於 LWC 透過 localization.timeFormatter 以及 timescale 格式化器統一指定 timeZone: 'Asia/Taipei'（例如使用 Intl.DateTimeFormat）；或若後端統一平移 8 小時，前端必須顯式覆寫 LWC 格式化器使用 getUTCHours() 顯示，禁止依賴瀏覽器本地時區。
- [medium] F2 §5: TX 交易時段判斷 D.in_session(sym, now) 的夜盤跨午夜與週末邊界未完整定義。台指期夜盤為 15:00～05:00：週五 15:00 開盤的夜盤會延續至週六凌晨 05:00；週日晚上無夜盤；週一凌晨 00:00～05:00 非交易時段。若僅用常規 weekday < 5 與小時判斷，週六凌晨會被誤判為休市（快取跳回 600 秒且不抓即時價），而週一凌晨會被誤判為開盤中。 → 明確定義 TX 盤中判斷邏輯：(1) 日盤：週一至週五 08:45～13:50；(2) 夜盤上半段：週一至週五 15:00～24:00；(3) 夜盤下半段：週二至週六 00:00～05:05。週日全天與週一 00:00～08:44 嚴格判定為休市。
- [low] F3 §3.4: 16:30 期交所逐筆檔回補缺漏日時，若遇到國定假日或颱風假，該日 bars5 根數為 0，排程若每日對過去 30 天內所有缺漏日發送下載請求，會對期交所產生大量 404 請求且每次耗費連線與等待時間。 → 回補排程應先比對 fut_daily（FinMind 日 K 已確認有開盤的交易日清單）或是於第一次遇到 404 時在 wave.db 寫入 non_trading_days 表，後續掃描直接略過已知休假日。
- [low] F4 §6.1, §6.2: 綜合研判方向計算採用通過指標各 +1／-1 加總，對於反向指標（如散戶小台多空比 retail_ratio 預期為反指標）之極性映射需嚴格防呆，避免散戶大幅作多（偏空訊號）被誤加為 +1。 → 在 stats.json 儲存指標回測元資料時，顯式記錄 polarity: 1 或 -1（基於樣本內 beta 或組差符號），方向加總公式應為 sign(current_state) * polarity，確保反向指標在散戶高水位時正確輸出偏空 (-1)。
- coverage：涵蓋波浪轉折點判定（K1-K3 替代遠端失效點）、超短線 30/60 分 K 引擎級數與價位合併、台指期日夜盤整合、連續月契約換月銜接與夜盤基準價、期貨籌碼回測閘門（樣本內外、月份區塊 bootstrap、殘差迴歸）、512MB VM 串流處理及 SQLite 資料庫設計。
- limitations：受限於公開免費資料限制，逐筆檔僅保存期交所近 30 天資料；選擇權法人 OI 金額歷史長度依賴 FinMind 限制；未包含大額交易人與夜盤三大法人盤中即時資料。

### 處置
Round 2 dispositions (coordinator): all 4 ACCEPTED.
- R2 G-F1 LWC timezone: API sends UTC epoch; LWC timeFormatter/tickMarkFormatter use Intl Asia/Taipei (§4.1).
- R2 G-F2 TX session boundaries incl. Friday night -> Saturday 05:05, Sunday/Monday-early closed (§5).
- R2 G-F3 backfill only trading days present in fut_daily (FinMind confirms open); 404/empty recorded, not retried same day (§3.4).
- R2 G-F4 polarity stored per factor; direction = sign(state) * polarity (§6.2).


## 第 3 輪（計畫，只送 Gemini）
- 原始輸出 reviews_b75/plan_r3_gemini.json

### Gemini gemini-flash-latest：APPROVED
PLAN-B75 successfully addresses all previous round findings (R1 & R2) and satisfies all user requirements without introducing look-ahead bias or statistical errors. The transition from wave invalidation to key turning points (K1-K3) is pre-registered with strict FDR control (BH q < 0.10) and practical distance constraints. The TX continuous contract and night-session pipeline correctly binds night sessions (15:00 T-1 to 05:00 T) to trading date T, eliminating settlement-day splits. Post-close chip factors properly account for overnight returns and use tradable next-day open prices. Low-resource 512MB streaming limits, UTC epoch timestamps with Asia/Taipei LWC formatters, and fallback mechanisms are sound.
- [low] F1 3.4: For TAIEX cash index (TWII) 5-minute bars, TAIFEX zip only covers futures (TX). If Cnyes fails to fetch TWII intraday 5m bars, the plan relies on startup backfill from Yahoo (^TWII 5m 60d), but does not explicitly schedule a Yahoo fallback if Cnyes fails at 13:50. → In the 13:50 or 16:30 schedule, if TWII bars5 for the current day are incomplete (< 54 bars) and Cnyes retry fails, allow a fallback fetch to Yahoo Finance (^TWII 5m) to ensure cash index intraday data remains uninterrupted.
- [low] F2 5: On Taiwan national holidays where Friday night has a session running until Saturday 05:00 but the following Monday is a holiday, the next trading day T is Tuesday rather than Monday. → Ensure the trading day resolver maps the Saturday 05:00 night session to the actual next open trading day as verified by FinMind's fut_daily calendar, rather than assuming Monday.
- coverage：Verified sections 1-13 with special focus on key level selection criteria (§2), futures continuous roll and ref_close (§3.2), low-memory streaming (§3.5), intraday timeframes & timezone handling (§4.1), session state detection (§5), post-close chip factor testing methodology (§6.1), composite direction aggregation (§6.2), and test suites (§11).
- limitations：Review is based on code context in service.py, levels.py, engine.py and PLAN-B75 specifications. Execution performance of TAIFEX zip parsing on Fly.io 512MB RAM will depend on network throughput and CPU throttling during concurrent web traffic.

### 處置
- R3 G-F1（low）加權分 K Yahoo 補：採納（§3.4）
- R3 G-F2（low）週五夜盤遇假日的交易日：採納（§5，用鉅亨日 K 日期＋FinMind 日期）
- 計畫有改 → 再送一次確認

## 第 4 輪（Gemini）／Groq 第 2 輪
- 原始輸出 reviews_b75/plan_r4.json、reviews_b75/plan_r4_gemini.json
- Gemini gemini-flash-latest：作業失敗（429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please ）——不算通過

### Groq openai/gpt-oss-120b：APPROVED（精簡摘錄 §2、§3.2～3.5、§6）
The plan addresses all previously raised concerns: night‑session return handling, chip timing, cache keys, session detection, look‑ahead bias, multiple‑testing correction, roll handling, timestamps, memory usage, retry logic, and UI wording. Statistical methodology and back‑testing procedures are well defined, and failure handling and resource constraints are adequately covered. Minor low‑severity suggestions are noted.
- [low] F1 3.5: Ensure the per‑file aggregation dict is cleared promptly after each zip to keep memory footprint minimal. → Explicitly delete or reassign the dict after processing each zip file.
- [low] F2 3.4: No alert channel for persistent source failures beyond UI flag. → Consider adding optional email/Slack alerts for sources that fail repeatedly (e.g., >3 consecutive days).
- Gemini 3.6-flash／3.7-flash 也 429（今天免費額度用完，約 15:00 重置）→ 第 4 輪 Gemini 作業失敗，不算通過

### 處置
- Groq R2 F1（low）逐筆檔 dict 處理完釋放：採納（實作時每檔處理完就丟）
- Groq R2 F2（low）email／Slack 告警：不採納（頁面已顯示資料來源失敗；不加額外通知）

## 計畫審查結論
- 最終計畫 PLAN-B75.md SHA256 32d396042421cb0ddef3e7b3b2907fc22b44e24e91b9012ff12ae5febc4bb61e
- Groq（gpt-oss-120b）核准最終版（精簡摘錄）；Gemini（flash-latest）核准第 3 輪版本，最終版只多了 Gemini 第 3 輪自己提出的兩個低優先項（加權分 K Yahoo 補、交易日用鉅亨／FinMind 日期），重新確認因額度用完沒做到
- 照實記：最終版 **沒有 Gemini 的完整核准**；由主持人決定照最終版實作（用戶已授權實作），Gemini 額度恢復後的最終程式檢查會涵蓋這兩點

## 實作（builder＝Claude，分支 b75，起點 31a5a16）
- 新模組：wave/futdata.py（台指期連續月、同月份夜盤基準、逐筆檔串流解析、5→30／60 分 K、盤別、鉅亨、回補）、wave/keylevel.py（K1～K3 轉折點）、
  wave/composite.py（綜合研判特徵、狀態、方向、融資增減）、wave/intraday.py（60 分 K 數浪、超短線價位、30 分 K 同 θ 轉折）
- 改：service.py（sym 分開快取／鎖、台指期日 K＋鉅亨即時、轉折點、夜盤→開盤參考、綜合研判、期現價差、panel_snapshot）、router.py（sym、status、排程 intraday_close／night_close、推播兩行、report?part=futures）、
  levels.py（build_ultra）、engine.py（INTRA 不放進 DEGREES）、data.py（新表、FinMind 金鑰改放標頭）、panel.py（facts_b75、allowed_levels 加台指期／超短線／轉折點）、server.py（13:50、05:10 排程）、
  regime-frontend（商品切換、三模式、30／60 分 K、轉折點格、綜合研判表、融資增減小圖、過熱恐慌縮小上移）
- 研究（research/futures）：R-I m＝2；R-K 三模式都選 K3（延續率都不顯著）；R-F 夜盤→開盤 R² 0.548、→當天 0.460 ✅，其他籌碼全部 △
- 偏離計畫（照實記）：
  1. 綜合研判表裡「沒通過的指標」的偏多偏空改用市場一般解讀（NATURAL），不套研究的 polarity（實測：外資選擇權 −0.6 億卻顯示偏多，會誤導）；方向只算 ✅ 不變
  2. 轉折點加 leg_start 說明（這段中間沒有反向小轉折時就是起漲／起跌點，例 10/21 加權短線轉強點 49,969 +6.0%、台指期 +6.6%）；規則不變
  3. 畫面測試單次距離判準改成「比波浪最後防線近、≤ 窗口 1.5 倍」（計畫驗收是中位數，研究已驗）
  4. FinMind 金鑰從網址參數改放 Authorization 標頭（httpx INFO log 會印出網址）；其他模組（positioning、deep_data、price_cache）還是放網址，沒動
- 驗證：pytest 353 passed（原 331＋新 22）；research/futures/verify_impl.py 夜盤 30 天、散戶小台／選擇權 30 天、轉折點 0 不一致；tests_ui/b75_ui.py 全部通過（加權／台指期 × 三模式 × 四時間框 0 JS 錯誤、過熱恐慌 58px 在摘要卡下、390 寬無橫向捲動）

### 程式檢查（後端，新的審查呼叫）Gemini gemini-3-flash-preview：APPROVED
The implementation of the B75 update is technically sound and strictly follows the approved PLAN. The complex logic for Taifex night sessions (belonging to the next trading day) and continuous contract reference prices (for night session return calculations) is correctly handled. Memory efficiency for the 512MB environment is maintained through streaming ZIP parsing. Turning points (K3) and the futures composite analysis properly incorporate backtest results while avoiding look-ahead bias.
- [low] F1 futdata.py: Database write on GET request → While approved in the plan for real-time consistency, ensure that high-frequency concurrent requests do not cause DB contention. The existing 120s snapshot cache and the threading lock in save_bars5 mitigate this.
- [low] F2 futdata.py: Potential division by zero or NaN in aggregation if data is sparse → The logic is mostly safe because it filters for math.isfinite(c), but explicitly verifying that at least one valid bar exists before creating the aggregate entry would be more robust.
- [low] F3 service.py: Potential stale data during TWII/TX synchronization → Add a flag or log warning when the basis is calculated against non-live TAIEX data during market hours so the AI Round Table can contextualize the 'basis' reading.
- coverage：High. Reviewed futdata.py (Data), keylevel.py (Turning Points), composite.py (研判), intraday.py (Short-term), and service/router.py (API). Verified Taifex ZIP streaming, session logic, and composite scoring.
- limitations：Review limited to backend Python files; Frontend LWC (wave.js) and index.html are excluded per instructions.

### 程式檢查（前端，新的審查呼叫）Gemini gemini-3-flash-preview：APPROVED
The implementation of B75 is solid, following the approved PLAN precisely. Security requirements (XSS prevention) are met using a robust `esc` function on all dynamic string outputs. Technical requirements for LightweightCharts v4 (handling axis type switching between Daily and Intraday) are correctly addressed by recreating the chart instance. Timezone handling (Asia/Taipei) is consistent across session detection and display logic. Mobile layout and null handling are well-implemented.
- [low] F1 regime-frontend/wave.js: LightweightCharts Data Type Separation → The code already implements this in `makeChart` and checks `chartKind !== kind` in `drawChart`. This is the correct approach for LWC v4 to avoid errors.
- [low] F2 regime-frontend/wave.js: Taiwan Market Session Logic → The `isSession` function correctly calculates minutes-from-midnight in TPE timezone and handles the crossover for Tuesday-Saturday early morning (TX night session end). No changes needed.
- [low] F3 regime-frontend/wave.js: Race condition during fetch → The code uses a `loadSeq` counter in the `load` function to discard stale responses, which effectively prevents this race condition.
- coverage：Reviewed complete frontend files for B75 including UI layout, charting logic, state management, and AI roundtable integration.
- limitations：Review is limited to the frontend code provided; backend API implementation of the /api/wave/snapshot endpoint is assumed to match the described shape and satisfy the data requirements.
- Gemini 2.5-pro 404（新帳號不能用）、pro-latest／3.1-pro-preview 429；gemini-3-flash-preview 可用（正式站沒在用）
- 處置：後端 F1 GET 寫資料庫（有 120 秒快取＋每商品一把鎖，不改）、F2 稀疏資料（agg_bars 已濾掉非有限值，不改）、F3 價差用非即時加權（畫面已標「加權 10/20 收盤」，不改）；前端 3 點都是確認已處理

### 程式檢查 Groq（gpt-oss-120b，去註解摘錄，一批一檔、隔 65 秒）
- futdata 前半：REVISE
  - [high] F1: NaN volume values are not sanitized in agg_bars (and parse_cnyes_hist) – using `v or 0` treats np.nan as truthy, propagating NaN into the aggregated volume field.
  - [high] F2: full_bars assumes night bar fields (`h`, `l`) are always present and numeric; if a night record exists with missing high/low (None), `float(None)` raises TypeError.
  - [medium] F3: parse_taifex_ticks divides the raw volume by 2 without explanation; if the source data already represents contract volume, the division yields incorrect totals.
- keylevel＋composite：REVISE
  - [medium] F1: The expression `pol = res.get('polarity') or 1 if res.get('pass') else NATURAL.get(key, 1)` relies on Python's operator precedence, which parses as `res.get('polarity') or (1 if res.get('pass') else NATURAL.get(key, 1))`. If `res['polarity']` is present but falsy (e.g., 0), the code will ignore it and fall back to the conditional, yielding an incorrect polarity.
- intraday＋futdata 後半（第 1 次）：作業失敗（Error code: 400 - {'error': {'message': "Failed to validate JSON. Please adjust your promp）——不算通過，重試
- intraday＋futdata 後半（重試）：REVISE
  - [high] F1: load_fut_daily constructs DataFrames using `dict(r)` on SQLite row tuples, which raises a TypeError because a tuple cannot be directly converted to a dict of column/value pairs.
  - [high] F2: load_fut_chips suffers the same `dict(r)` misuse, causing a TypeError when loading chip data.

### 處置（每條實測）
- futdata F1 NaN 量會傳下去：**成立**（實測 agg_bars 回 nan）→ 改成 0，加測試
- futdata F2 夜盤高低 None：防呆採納 → select_continuous 丟缺值列、full_bars 忽略缺值夜盤高低開
- futdata F3 逐筆檔量 ÷2：**不成立**（欄位是「成交數量(B+S)」買賣合計，程式說明有寫，摘錄去註解拿掉了）
- composite F1 運算子優先順序：**不成立**（ast 實測 `a or 1 if p else n` 解析成 `(a or 1) if p else n`；pass=False 時回 NATURAL）
- futdata_B F1／F2 dict(sqlite row) TypeError：**不成立**（D.db() 設 row_factory=sqlite3.Row；本機快照、測試都實際讀過）

### 修正後重新檢查（新的審查呼叫）Gemini gemini-3-flash-preview：APPROVED
- 檢查 futdata.py、composite.py、tests/test_b75_futures.py 完整檔：兩個修正正確、沒有退步
- pytest 354 passed（原 331＋新 23）

## 結論
- 計畫：Groq 核准最終版（摘錄）；Gemini 核准第 3 輪版（最終版只多 Gemini 自己提的兩個低優先項，重新確認因額度沒做）
- 程式：Gemini 後端／前端核准、修正後重新檢查核准；Groq 3 批共 6 點，1 點成立已修、1 點防呆採納、4 點實測不成立
- 檢查範圍沒有包含 research/futures/*.py（離線研究腳本），由 verify_impl.py（0 不一致）與 pytest 覆蓋
