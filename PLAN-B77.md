# PLAN-B77：全系統總檢查——穩定（記憶體）、速度、內容

## 0. 用戶原話與起因（2026-10-21 20:10）
- 截圖：全系統更新 6/12，「權證合約更新」中斷：「更新沒有跑完：在權證合約更新途中伺服器重新啟動」
- 「這怎麼了？你們對全系統做優化從速度跟內容，做一次總檢查」
- 20:45 追加：「系統要全面檢查優化，不是只有這個部，我今天的 TOKEN 都要拿來做優化」→ 範圍＝全部分頁、API、排程
- 20:55 追加（K 線截圖）：「月斜率拿掉，K 線副圖上面三項就好」→ K 線只留成交量、小 MACD、大 MACD；同一張截圖主圖價格軸 −100～500、K 棒被壓扁
- 沿用：免費優先（不加月費，付費選項只當備註）、白話、先看結論細節收起來、紅漲綠跌、不質疑用戶回報

## 1. 總檢查結果（實測，證據）
| # | 問題 | 證據 |
|---|---|---|
| P1 | **正式站記憶體不足被砍（OOM）** | Fly 事件：20:05:04 `exit_code=137, oom_killed=true`；18:00:15 也重啟一次。機器 512MB（可用 470MB），閒置 RSS 234MB |
| P2 | 權證合約更新一次吃 +206MB | 證交所權證合約 JSON 45MB（44,717 檔）＋櫃買 17MB，一次 `r.json()` 整包載入；本機實測 RSS 178→尖峰 384MB |
| P3 | 產業輪動同步 +173MB | `sync_from_price_cache` 每次把 200 天 × 2,100 檔（約 28 萬列）全讀進 list、整段刪掉重寫；本機 174→347MB |
| P4 | 18:00 自動掃描＋全系統更新今天沒跑完 | 正式站掃描結果停在 10-20 23:50；18:00:15 重啟後 APScheduler 不會補跑；20:05 重啟後要用戶自己再按 |
| P5 | scipy 只為 norm.cdf／brentq 就載入 | import scipy.stats＋optimize 本機 +54MB 常駐 |
| P6 | 18:00～19:05 多個重工作同時跑 | 18:00 掃描→全系統更新（內含庫藏股／併購／可轉債）與 18:40 庫藏股、18:50 併購、19:05 可轉債各自排程重疊；各自獨立 BackgroundScheduler 互不知道 |
| P7 | 前端無效輪詢 | `checkCacheStatus` 找不到 `cache-ready-msg` 元素 → TypeError 被吞 → **每 8 秒永遠打** /api/price-cache/status；指數列每 10 秒（下班、分頁在背景也打）；總經 iframe 每 60 秒打 20 個 series（日資料）；產業 iframe 每 30 秒；Fly 健康檢查每 30 秒 GET / 回 534KB 首頁 |
| P8 | /api/indices 每次 1.0～1.7 秒 | 沒有伺服器快取，每次依序打 MIS 暖機＋MIS＋期交所（日盤／夜盤），每個開著的分頁都各打一次 |
| P9 | 處置股 /api/disposal/today 冷快取 13.9 秒 | 30 分鐘快取過期後第一個人要等；重啟後也要等 |
| P10 | 可轉債 /api/cb/list 每次 0.6～1.2 秒 | 快取 5 分鐘過期後第一個人重算 0.57s（本機）；回應 103KB 走 FastAPI jsonable_encoder |
| P11 | 籌碼型 5 策略正式站全是 0 | 10-20 掃描：投信連買、融券大增／退潮、大戶增散戶減、投信倒貨全 0；正式站 course.db 有資料到 10-20；同程式本機今天跑：6／10／10／428／8 → 正式站那次 `chip_course.run_all` 失敗被吞（只 print，Fly log 已輪替看不到原因） |
| P12 | 重啟後權證掃描結果、上次合約更新紀錄變空 | /warrant/api/scanner `results:[] scanned_at:null`、ingest/log `ran_at:null`（都只存在記憶體） |
| P13 | **K 線主圖被壓扁**（用戶截圖 3441：價格軸 −100～500，K 棒只占 1/3） | Playwright 重現：主圖 245px、92 個標記（假跌破／假突破箭頭、前高前低圓點）。拿掉標記 → 價格範圍 29～359；只拿掉文字仍 −136～558 → 圖表套件為了放標記在上下各留大量像素邊界 |
| P14 | 首頁一打開就約 150 個請求 | Playwright：權證／總經／產業 3 個 iframe 在 HTML 寫死 src → 沒點分頁就載入（總經頁 171KB 快照＋21 個 series）；觀察清單千張大戶趨勢每檔 1 個請求、而且整串跑 2 次（31 檔 × 2 = 62 個依序請求，約 2.5 秒）；best/near ×3、best/retest ×3、course/research ×2、best2/fixed825（91KB）×2、best/watch ×2、screen/status ×2（`if (x === null) x = await api()` 同時呼叫會各打一次） |
| P15 | 隱藏分頁還在輪詢 | 停在觀察清單 60 秒：indices 6、price-cache/status 8、總經 iframe 21、產業 2 個請求 |
| P16 | 連動 /api/link/movers 冷快取 2.9 秒、大盤解析台指期冷快取 4.9 秒、深度分析冷 1.5 秒 | 實測；重啟或快取過期後第一個人要等 |
| 正常 | 手機 390 寬 14 個分頁都沒有整頁橫向捲動、0 個 JS 錯誤（Playwright 巡檢）；總經、大盤解析、產業、市場關聯、可轉債、併購、庫藏股資料都是今天；多數 API 0.15～0.4 秒 | 實測 |

## 2. 驗收條件
1. 本機實測（scratchpad mem_peak.py，同一份資料）：權證合約更新尖峰增量 ≤ 60MB（原 206）、產業同步尖峰增量 ≤ 40MB（原 173）、import server 常駐 ≤ 原本 −40MB（拿掉 scipy）；權證合約寫進 DB 的結果與舊版完全相同（筆數＋逐欄比對）
2. 正式站部署後：閒置 RSS < 200MB；跑一次完整掃描＋全系統更新（12 步全部完成）期間沒有 OOM；🩺 頁面看得到每個重工作的尖峰記憶體
3. 伺服器在全系統更新途中重啟 → 不用再按：約 2 分鐘後自動從中斷那步接著跑（已完成的不重跑）；同一步連續中斷 2 次 → 標「略過（記憶體不足）」繼續後面的
4. 18:00 掃描被重啟打斷 → 重啟後自動補跑（平日 18:00～隔天 08:00 之間，每個交易日最多補 2 次）
5. 指數列伺服器快取：多人同時看只打一次外部；/api/indices 快取命中 < 0.3 秒；前端分頁在背景不打、非交易時段 60 秒一次（台指夜盤時段照 10 秒）
6. 前端：price-cache 輪詢在 ready 後停止；總經 iframe 5 分鐘、只在看得到時才重抓，20 個 series 合併成 1 個請求；產業 iframe 只在看得到時輪詢
7. 處置股：過期時先回舊資料（< 0.5 秒）背景更新；存檔，重啟後馬上有；18:00 後預先算好
8. 可轉債清單：直接回 JSON（不走 jsonable_encoder）、更新完預先建好快取、過期先回舊資料背景重建
9. 籌碼型策略失敗不再默默 0：掃描狀態記錄每個策略的錯誤，策略結果頁顯示「⚠ 籌碼型策略計算失敗：原因」；整體失敗自動重試 1 次（不重抓資料）
10. 權證掃描結果、上次合約更新紀錄存檔，重啟後還在
11. 設定頁「🩺 系統健康」：最上面一句結論（✅ 全部正常／⚠ N 項要注意），下面每項白話：記憶體（現在／上限／swap）、最近重開（時間＋當時在跑什麼）、各資料最新日期（股價、掃描、總經、產業、權證合約、集保、法人、可轉債、併購、庫藏股）、背景工作紀錄（收起來）
12. K 線：沒有月線斜率副圖（只剩成交量、小 MACD、大 MACD，主圖分到多出來的高度）；3441（92 個標記、1532×687 視窗）主圖價格範圍 ≤ K 棒高低範圍的 1.8 倍（原 3.2 倍）；標記仍看得到
13. 首頁：沒點的分頁不載入 iframe；初次載入請求數 ≤ 60（原約 150）、同一個 API 不重複打；千張大戶趨勢 1 個請求
14. 重啟後 60 秒內預先暖好：指數、處置股、可轉債清單、連動、大盤解析（加權＋台指期）
15. pytest 全過（原 365＋新增）；tests_ui/b77_ui.py：設定頁健康卡、全系統更新框（中斷→自動續跑文字）、30 秒內 price-cache/status 只打 ≤ 1 次、0 JS 錯誤

## 3. 做法

### A. 記憶體（P1～P3、P5、P6）
- **A1 權證合約串流**（warrant/ingester.py）：下載改串流寫到暫存檔（chip_data/tmp/，用完刪）；用 `ijson`（C 後端 yajl2_c）逐筆讀：
  - 頂層是陣列 → `items(f, "item")`；頂層是物件（rwd 備援格式 fields＋data）→ 先 `items(f,"fields.item")` 再 `items(f,"data.item")` zip
  - 暫存檔放 chip_data/tmp/（volume，不放 rootfs）；開機時清掉該資料夾所有舊檔（OOM 被砍時 finally 不會跑，審查 Gemini F4）
  - 兩趟：第 1 趟只建 權證代號→標的名稱 對照（小）；第 2 趟逐筆 `_parse_warrant_row`＋upsert（同一個交易，跟舊版一樣）
  - ijson 解析失敗 → **不**退回整包讀法（審查 Groq F2：會再 OOM）；這次合約更新記失敗、DB 保留舊合約；暫存檔在 finally 一定刪掉；下載大小上限 200MB（超過中止）
  - 永豐 basic.js 對照表用完就清掉（全域變數原本常駐約 20～30MB；flow.py 15:30 需要時自己重新下載，1 天多 1 次 5MB）
  - requirements 加 `ijson`
- **A2 產業同步增量**（sector/prices.sync_from_price_cache）：預設只同步 sector_stock_daily 最新日期往前 10 天之後的日子；sector_stock_daily 不到 60 天或參數 full=True 才全量；逐日讀寫（每天 ≤ 2,200 列）不再一次全載；整天替換規則不變（該天 ≥1000 檔才刪舊列）
- **A3 拿掉 scipy**（warrant/calculator.py）：norm.cdf／pdf 改 `math.erf`／`math.exp` 公式；brentq 改純 Python Brent 法（同 xtol 1e-8、maxiter 300、同區間與找不到根的處理）；requirements 的 scipy 保留（研究程式用），正式站執行路徑不 import
- **A4 重工作排隊**（新 jobs.py）：`heavy(name)` context manager＝一把 RLock（同一個執行緒可重入），同時只跑一個重工作，其他排隊（等待秒數記到紀錄）；套用：18:00 掃描、全系統更新、權證合約 08:00、產業重算（排程與 API）、庫藏股 18:40／併購 18:50／可轉債 19:05／市場關聯 17:00／籌碼定位 16:45 的排程；手動按分頁更新鈕不套（少用，避免按了看起來卡住）
  - 排程版的庫藏股／併購／可轉債／市場關聯：90 分鐘內全系統更新剛做過同一項且成功 → 跳過（不重複抓）
  - 結束時 `gc.collect()`＋Linux `malloc_trim(0)`（把釋放的記憶體還給系統；非 Linux 略過）
  - 執行中每 0.5 秒取樣 RSS，記尖峰
  - 規則（審查 Groq F1）：heavy() 只包「工作的最外層入口」，不包在 worker 執行緒裡跑的函式；等待上限 60 分鐘，逾時就不跑並記錄「排隊逾時略過」（不無限等）
  - 不能在 event loop 上等鎖（審查 Gemini F2）：heavy() 偵測到目前執行緒有正在跑的 asyncio loop 就直接丟 RuntimeError（測試涵蓋）；API 觸發的重工作（例如產業「計算」按鈕）一律開背景執行緒再進 heavy()
- **A5 Fly swap**：fly.toml 加 `swap_size_mb = 512`（免費，用機器本身磁碟；當安全網，慢但不會被砍）。付費備註：升 1GB 約每月多 US$2.5，這次不做
- **A6 健康檢查**改打新的 `/healthz`（只回 "ok"，不讀 DB、不回 534KB 首頁；詳細的在 /api/system/health，審查 Groq F5）

### B. 自動補跑（P4）
- **B1 全系統更新續跑**：狀態檔加 `crash`（每步被中斷次數）、`resume_at`；啟動讀檔發現中斷：該步 crash+1；若 started_at 在 6 小時內 → `resume_at`＝現在+120 秒，背景執行緒到點後用 resume 模式跑：狀態 done／busy 的步驟跳過，crash ≥ 2 的步驟標 `skipped`（略過：連續 2 次跑到一半伺服器重開，多半是記憶體不夠）其餘照跑。用戶這時按按鈕＝同樣 resume（6 小時內有中斷）；超過 6 小時或上次完整跑完＝全部重跑
- **B2 18:00 掃描補跑**：啟動 180 秒後判斷（純函式 `need_scan_catchup(now, finished_at, attempts)`）：應有掃描日＝平日 ≥18:00 取今天；隔天 < 08:00 取前一個平日；其他時間不補。掃描 finished_at 早於「應有掃描日 17:30」→ 補跑 18:00 那套（掃描＋研究候選／連動／大跌／講義推播＋全系統更新；全系統更新若 6 小時內中斷就 resume）。chip_data/catchup.json 記每個掃描日的嘗試次數，最多 2 次（防重啟迴圈）；第 2 次延後到重啟 10 分鐘後才跑（審查 Groq F4）。推播同一天只推一次的既有保護不變
- 18:00 函式拆成 `_scan_step1()`（掃描＋推播）與 step2（全系統更新），排程與補跑共用
- **B1／B2 同一個啟動補跑執行緒**（審查 Gemini F1）：開機後先判斷 `need_scan_catchup`；要補掃描 → 180 秒後跑 step1，接著跑全系統更新（6 小時內中斷就 resume，否則全跑），**不另外**排 120 秒的續跑；不用補掃描、只有全系統更新中斷 → 120 秒後 resume。整段在 heavy() 裡

### C. 速度（P7～P10）
- **C1 指數列**：模組快取＋asyncio.Lock 單飛（同時多個請求只打一次外部）；TTL：交易時段（08:45～13:45、15:00～隔天 05:00 期貨夜盤）8 秒，其他 60 秒；MIS 與期交所兩段改 `asyncio.gather` 並行；失敗時回上一份並標 stale
- **C2 前端輪詢**：
  - dashboard：`checkCacheStatus` 元素 null 防護（ready 一定停止輪詢）；指數列 `document.hidden` 時不打、切回來立刻打一次，非交易時段 60 秒
  - regime-frontend：`load()` 改 5 分鐘、只在 iframe 看得到（`window.frameElement.offsetParent !== null`）且頁面可見時跑；新端點 `/regime/api/regime/series_multi?names=a,b,…&days=N` 一次回多個 series（舊端點保留）
  - sector-frontend：狀態輪詢只在看得到時跑、改 60 秒
- **C3 處置股**：disposal.today 改「過期先回舊資料＋背景更新（單飛）」；結果存 chip_data/disposal_cache.json，啟動讀回；18:00 流程後預先算一次
- **C4 可轉債清單**：回 `JSONResponse`；cb 更新完立刻重建快取；過期先回舊資料背景重建

### E. 前端載入與 K 線（P13～P16）
- **E1 K 線**：拿掉月線斜率副圖（`lwc-ms` 與相關同步程式；觀察清單的月線斜率欄、深度分析的月線斜率文字保留）；蠟燭 series 加 `autoscaleInfoProvider`：保留原本價格範圍，標記邊界（單位＝像素，實測套件原本回 `{above:39, below:39}`；審查 Gemini F3 說是比例，實測 0.08＝沒有邊界 → 駁回）上下各最多 max(16px, 主圖高 × 8%)；主圖 scaleMargins 改 top 0.12／bottom 0.08（原預設 0.2／0.1）；截圖確認箭頭與文字沒被切掉
- **E2 iframe 延遲載入**：權證／總經／產業 iframe 改 `data-src`，第一次點分頁才設 src（市場關聯已經是這樣）；`_rfReloadTabs` 只重載已載入的
- **E3 千張大戶趨勢批次**：新端點 `GET /api/tdcc/trends?ids=…`（一次回每檔最近 8 週 kpct）；`enrichTdccTrends` 改一次請求，並防重入（同時只跑一個，資料沒變不重跑）
- **E4 前端去重**：`apiOnce(key, url)`＝存 Promise（不是存結果），同時呼叫共用同一個請求；套到 best2/strategies、course/research、quality/research、best2/fixed825、best/summary、best/near、best/retest、best/watch；init 的 screen/status 只打一次
- **E5 預熱**：jobs.prewarm()＝重啟 60 秒後、18:00 那套跑完後，依序呼叫（不並行）：指數、處置股、可轉債清單、連動、大盤解析加權＋台指期快照；每項失敗只記 log
- **E6 連動 movers**：過期先回舊資料背景更新（同 C3 做法）

### D. 內容（P11、P12）
- **D1 籌碼型策略**：chip_course.run_all 回傳每個策略的錯誤（`_errors`），掃描狀態加 `chip_errors`；整體丟例外 → 不重抓資料再試 1 次，仍失敗記錯；結果頁該 5 個策略按鈕／表格顯示「⚠ 計算失敗：原因」而不是 0 檔；print 改 logging（Fly log 看得到）
- **D2 權證**：掃描結果（results、scanned_at、mode 等）每次完成寫 chip_data/warrant_scan.json、import 時讀回；`_last_ingest_log` 同樣存檔
- **D3 🩺 系統健康**：jobs.py 寫 chip_data/job_log.jsonl（start／end／秒數／成功失敗／尖峰 RSS／等待秒數；開機時保留最後 300 行）；開機記一筆 boot，若上一筆有 start 沒 end → 記「重開時正在跑：X」；`GET /api/system/health` 回記憶體（/proc/self/status、/proc/meminfo 含 swap）、最近 10 次開機、最近 30 筆工作、各資料最新日期與 ✅/⚠（規則：平日 18:30 後應有今天，否則前一個平日；集保 8 天內；外部模組讀各自 status 函式）；設定頁卡片照 §2-11

## 4. 不做／風險
- 不改任何選股條件（S_BIGHOLD 本機 428 檔偏多→只記錄，要改需回測另議）；不重構 534KB dashboard
- 重工作排隊會讓 18:40 等排程延後（等 18:00 那套跑完）——可接受，反正內容相同
- swap 讓尖峰時變慢但不會被砍；若之後仍常用到 swap，再考慮付費升級
- malloc_trim 只在 glibc（Fly 的 python:3.12-slim 是 Debian glibc）有效

## 5. 驗證
- `python -m pytest tests -q`（全過）；新增 tests/test_b77.py：ijson 兩種格式＝舊解析（同 fixture）；erf／Brent vs scipy（格點誤差 < 1e-9、IV < 1e-6）；增量同步＝全量同步最後 N 天結果；續跑 crash 計數／skipped／跳過 done；`need_scan_catchup` 時間表；指數快取單飛（monkeypatch 外部、併發 5 個只打 1 次）；處置股過期回舊資料；健康頁新鮮度規則
- 記憶體：scratchpad mem_peak.py 前後對照（權證、產業、掃描、import）
- 前端：tests_ui/b77_ui.py（Playwright，全域 python）
- 部署後：fly machine status 無 OOM、/api/system/health、各慢端點重測、補跑掃描結果日期＝今天、籌碼型策略數量 > 0（或顯示真正的錯誤原因）
