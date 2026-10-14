# PLAN-B72 審查紀錄（append-only）

- 2026-10-14 開始。Host＝Claude Code（Opus 5.5），規劃＋實作＝Claude。
- 審查者：依用戶設定不用 Codex，計畫審查與最後程式檢查都用 Gemini＋Groq（Desktop/claude-files/claudex-review2.py；Gemini 模型看 GEMINI_REVIEW_MODEL、Groq openai/gpt-oss-120b）。
- 計畫：PLAN-B72.md；最多 5 輪計畫審查、2 輪修正、2 輪程式檢查。
- 授權：用戶要求「請改進」＋要 Telegram 實際推播 → 實作＋commit＋push（GH Actions 部署）沿用前幾批做法。
- 用戶決定（AskUserQuestion）：回測 8%/25% 不限天數；假跌破（不是假突破）、全市場 S_FBD；13:10 發收盤前清單；研究候選＝快觸發名單＋放寬股票池重測＋8%/25% 重測（沒選「最近訊號＋後來漲跌」）。

## 計畫審查
- 第 1 輪：Gemini 2.5-flash APPROVED（medium：512MB 全市場每 5 分鐘資源；low：重試）；Groq gpt-oss-120b REVISE（F1 存活者／前視、F2 盤中部分量＋重試、F3 假日曆、F4 資源、F5 錯誤路徑測試、F6 採用規則稽核）。原始回應 research/b72/plan_r1.json
- 處置：
  Round 1 dispositions (coordinator):
  - Gemini F1 / Groq F4 (512MB resources): ACCEPTED as clarification — history loaded once per day with one SQL, only prefilter candidates kept (~1,000 stocks x 130 bars numpy, <20MB), quotes fetched sequentially in batches of 40 (~25 requests), max_instances=1 skip-if-running, per-tick timing logged. REJECTED: async concurrency / memory-watchdog fallback (not needed at this size).
  - Gemini F2 / Groq F2 (retry): ACCEPTED one retry per failed batch / Yahoo / TAIFEX call. REJECTED exponential backoff (5-minute cadence already spaces calls).
  - Groq F2 (partial volume): ACCEPTED differently — today's volume passed to screen_sfbd = max(cumulative volume so far, prior-20-day average excluding today), so both the min_vol_lots check and the in-function break-day volume comparison are not depressed by a half-day volume.
  - Groq F1 (survivorship/look-ahead): REJECTED as stated — including delisted stocks is what AVOIDS survivorship bias; delisted-while-holding exits at last traded close (existing engine 'gone' handling). Stop/target prices are fixed at entry; intraday touch uses that day's low/high and fills at the stop/target price (gap -> open), no post-trigger information. Clarified in plan.
  - Groq F3 (holiday calendars): PARTIALLY ACCEPTED — every market group is labelled with its data date (e.g. US 10/14 close) and change is computed vs the last close before the latest bar, so holidays degrade naturally; TW holiday detection already = live quote date != today. REJECTED adding pandas_market_calendars dependency.
  - Groq F5 (error-path tests): ACCEPTED — tests for quote fetch total failure (no push, no exception), Telegram failure (ok=0 retried next tick), Yahoo all-fail (day-trade list still sent). REJECTED memory-pressure tests.
  - Groq F6 (adoption criteria audit): already pre-registered in this plan (versioned in git); REPORT-825.md will restate the criteria and the measured numbers.
  
  Round 2 (Groq APPROVED; Gemini call failed: server disconnected — not counted):
  - Groq F1 (traceback on first 3 swallowed errors): ACCEPTED (traceback printed).
  - Groq F2 (log skipped runs): ACCEPTED — APScheduler already logs "maximum number of running instances reached"; per-tick timing logged.
  - Groq F3 (stale data): ACCEPTED — items whose latest bar is older than 7 days are omitted and logged.
- 第 2 輪：Groq APPROVED（3 個 low 已接受）；Gemini 作業失敗（Server disconnected，不算通過）。research/b72/plan_r2.json
- 第 3 輪（只送 Gemini，修改後計畫）：APPROVED；low：F1 前 3 次 log 範圍＝每次掃描重算（接受）、F2 fetch5y 就是官方 MI_INDEX＋櫃買 otc（已是）、F3 10.5%＝超過台股漲跌停 10%，一定是除權息／減資（沿用 best_strategy.gap_guard）。research/b72/plan_r3g.json
- 核准版本：PLAN-B72.md sha256 前 16 碼 48bec39e9d7bd0d5（Groq 核准的是加「超過 7 天略過」這一行之前的版本；那行就是 Groq 自己的建議）

## 實作（Claude 寫程式）
- A 掃描漏策略：STRATEGY_KEYS 改由 PRICE_STRATEGY_FNS 產生、收結果 setdefault、錯誤印 traceback（tests/test_scan_keys.py；舊程式跑這個測試會失敗，已確認）
- B 回測預設：K 線／批量／指數回測＋後端端點預設＝停損 8%、停利 25%、移動停損不設、不限天數（playwright 讀到 bt-stop=pct 8、tp 25、trail none、days 0；批量 query stop=pct&stop_pct=8&take_profit=25&trail=none&max_hold=0）
- C 研究：research/b72/run825.py；研究版 8/25 出場 vs backtest_engine.simulate 抽 25 筆 0 不一致
- D fbd_live.py＋排程＋/api/fbd-live/status＋S_FBD 頁面區塊；離線用官方 10/13 以前歷史＋10/14 那根當即時價跑 13:10：12 檔＝同資料收盤版 12 檔＝正式站 18:00 掃描 12 檔（候選 523 檔、1 秒）
- E1 快觸發（best_strategy.near_of／near_save、/api/best/near）：官方 10/14 資料 → 6720 久昌 量太小（20 日均量 38 張）、8084 巨虹／2236 百達-KY 等破底翻
- E2／E3（research/b72/best_retest.json）：原本重現 樣本外 634 筆 83.9%／+6.06%、帳戶 +6.24%／−33.36%（原公布 627 筆 83.7%／+6.05%、+6.19%／−33.36%）
  - E2 均量 300：新增那批樣本外 144 筆 82.6%／+4.68%、PF 3.21；合併 774 筆 83.6%（−0.3pp）→ 照規則採用，best_strategy.MIN_VOL20＝300、說明頁註明上面統計是 500 張版本
  - E3 8%/25%：樣本外 608 筆 56.1%／+9.76%，但帳戶年化 +5.62% < 原本 +6.24% → 照規則不採用，並列顯示
- F global_brief.py＋push_premarket（國際盤放最前面、當沖沒資料照發、國際盤失敗當沖照發）＋/api/global-brief；本機實抓 2.2 秒、含台指期夜盤
- pytest 284 passed（新增 24）

## 程式檢查（最後檢查，審查者沒寫程式）
- Gemini 2.5-flash：後端（PLAN＋py.diff＋fbd_live.py＋global_brief.py）APPROVED；前端（front.diff）APPROVED。research/b72/insp_g1.json、insp_g2.json
- Groq gpt-oss-120b（一次一個檔、去 docstring、隔 65 秒）：6 批都 REVISE，逐條實測：
  - fbd_live／global_brief「f-string 巢狀引號語法錯誤」→ 駁回：那是送審用的 ast.unparse（Python 3.12，PEP 701 合法）產生的；原始檔是一般寫法，compile 成功、測試有 import 執行；正式站也是 python:3.12
  - fbd_live「asyncio.run 在已有事件迴圈會錯」→ 駁回：排程在 BackgroundScheduler 執行緒（沒有事件迴圈），跟 course_live._send 同一寫法、正式站已在用
  - global_brief XSS／_arrow 門檻 → 駁回：名稱都 escape，其餘是固定字與數字
  - yahoo_price「拿掉 S_BEST」→ 駁回：S_BEST 在 PRICE_STRATEGY_FNS，test_strategy_keys_cover_all_price_strategies 有檢查；「錯誤吞掉」→ 接受，掃描結束印總次數
  - best_strategy「沒 import json」→ 駁回（檔案第 9 行就有）；near_load 失敗回傳沒 pool → 接受，補上
  - course_live「國際盤文字要 escape」→ 駁回：那段是我們自己組的 HTML（<b> 是刻意的），名稱已在 global_brief 裡 escape；「streak KeyError」→ 駁回：舊程式沒動、資料是 calc_limit 產生
  - server「exit_ma=0 會除以零」→ 駁回：api_backtest_index 是 if exit_ma > 0 才算（舊版選「不設條件」本來就送 0）；「max_hold=0」→ 駁回：ExitConfig 0＝不限，有測試；「排程 09:00 開始」→ 駁回：時間判斷在 tick（註解有寫）
  - 原始回應：research/b72/insp_q_*.json
- 研究程式 run825.py：Gemini 2.5-flash、3.6-flash 都 503（作業失敗，不算）；gemini-flash-latest APPROVED（出場規則、帳戶模擬、E2／E3 採用邏輯）。research/b72/insp_g3.json
- Gemini 檢查後我又改了兩個小地方（Groq 建議）：掃描結束印收結果失敗總數、near_load 失敗回傳補 pool → 這兩個改動沒有再送外部檢查（只有測試）

## 正式研究（新訊號 sig_all：網站現在 20 個做多策略的 screen 函式，2021-10～2026-10-14，31 萬筆）
- 研究版 8/25 出場 vs 網站引擎再抽 25 筆：0 不一致
- 新訊號只比 10-09 舊 sig_a 多（S_BIAS 多 559、S_BREAKBOTTOM 多 19，沒有少）：舊的那次少算了一些股票，新程式沒問題
- E2／E3 用新訊號重跑，結論不變：原本 637 筆 83.7%／+6.00%、帳戶 +6.23%／−32.45%；E2 新增 144 筆 82.6%／+4.68%、合併 777 筆 83.4% → 採用；E3 612 筆 55.9%／+9.69%、帳戶 +5.98% < +6.23% → 不採用
- 8/25 全策略（research/best2/results/fixed825.json，樣本外 2024-07～2026-10-13）：樣本外平均每筆為正且勝過隨機：負乖離 +5.18%（43%）、強勢股 +3.03%（102 筆）、破底翻 +2.77%、漲停 +1.61%、KDJ 低檔 +1.26%、RSI6 超賣 +0.42%、黃金切割 +0.28%、RSI6 鈍化 +0.19%、S2 +0.11%；S1 比隨機好但 −0.09%；其餘 10 個（含假跌破 −0.84%、仙人指路 −1.23%、平地一聲雷 −1.31%）沒勝過隨機。帳戶（10 檔）年化最高 平地一聲雷 +13.6%、強勢股 +12.0%、RSI6 超賣 +11.9%，都低於同期加權 +24.0%
- 之後的小改（沒再送外部檢查，只有測試＋截圖）：勝過隨機分三種標示（✅／△ 比隨機好但虧／✗）、拿掉每列都是 −8.7% 的中位數欄

## 追加（10-14 用戶）：回測進場加「成交量 ≥ 前一天 2 倍」
- 用戶：「如果回測的部分 加上成交量呢?? 進場設定要比前一天成交量兩倍以上才進場??」
- 定義：看**訊號當天**的量 ≥ 前一天 × 2（訊號收盤出、隔天開盤買；進場那天的量開盤時不知道，用了＝偷看）
- 研究（run825.py stage_v，結果併進 fixed825.json 的 vol2；隨機基準也只從「量 ≥ 前一天 2 倍」的股票日抽）：樣本外平均每筆
  - 變好：負乖離 +5.18% → +7.06%（1,472 筆，加量隨機 +3.16%）、KDJ 低檔 +1.26% → +2.57%（739 筆）、RSI6 超賣 +0.42% → +1.16%（263 筆）、強勢股 +3.03% → +8.59%（只剩 29 筆）、黃金切割 +0.28% → +0.30%（93 筆）、N 字 −0.40% → −0.06%
  - 變差：漲停 +1.61% → −0.44%、破底翻 +2.77% → −2.73%（80 筆）、S2、S1、布林、週 MACD、假跌破、天量缺口、仙人指路、平地一聲雷、量滾量、RSI6 鈍化
  - 一樣：S5、漲停打開（本來就要爆量）
- 網站：K 線回測、批量回測加「量 ≥ 前一天 N 倍才進場」（vol_mult，**預設 0＝不看量**，因為多數策略加了變差；用戶要的話填 2）；總表加「加量 2 倍：樣本外」與「跟不加比」兩欄、每個策略區塊加一列
- 測試 287 passed（tests/test_bt_volume.py）；Gemini 2.5-flash APPROVED（flash-latest 503）。research/b72/insp_vol.json
