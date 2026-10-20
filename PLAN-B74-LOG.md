# PLAN-B74 審查紀錄（append-only）

## 設定（2026-10-20）
- 主機：Claude Code（Opus 5.5）＝需求、計畫、實作（builder=claude）
- 計畫審查：Gemini（GEMINI_REVIEW_MODEL，預設 gemini-3.6-flash）＋Groq openai/gpt-oss-120b —— 用戶既定（記憶 feedback_claudex_loop_reviewers：Codex 401、不用 GPT/Codex），腳本 `claude-files/claudex-review2.py`
- 程式檢查：同上兩家，新的呼叫（無共用 session）
- 輪數：計畫 ≤ 5 輪；修正 ≤ 2 輪；檢查 ≤ 2 輪
- 授權：用戶下 /claudex-loop 帶需求＝規劃＋實作；部署照前幾批（push main → GH Actions）；GROQ_API_KEY 要用戶自己設 Fly secret
- 範圍：見 PLAN-B74.md §0
- Groq 每分鐘 8000 tokens → 計畫拆兩份送（planA＝§0、2、3、4、10；planB＝§5～9、11、12），兩次間隔 65 秒；Gemini 送完整計畫

## 第 1 輪（2026-10-20）
- Gemini gemini-3.6-flash（完整計畫）：REVISE — F1 重疊報酬要 block bootstrap、相似狀態選因子不能看樣本外；F2 修正浪少了平台型；F3 日期正規化要在寫入口；F4 Groq 429/413 處理（結果檔 research/b74_plan_r1.json）
- Groq gpt-oss-120b（planA）：REVISE — F1 盤中資料確認轉折＝偷看；F2 多重檢定；F3 硬規則太嚴；F4 歷史資料只靠 Yahoo；F5 AI 成本／幻覺；F6 版面回歸測試；F7 相似樣本 30 太少（research/b74_plan_r1.json）
- Groq gpt-oss-120b（planB）：REVISE — F1 轉折確認日；F2 BH 要全部一起＋分時期；F3 硬規則給分制；F4 自動切換；F5 價位驗證；F6 效能 CI；F7 免責聲明（research/b74_plan_r1b.json）
- 處置（全文見 scratchpad disp_r1.md，摘要）：
  - 接受：block bootstrap、因子只用樣本內選＋R6 逐步往前校準、平台型修正浪、upsert_series 正規化日期、per-provider 例外、只用收完的日 K 確認、轉折確認日、全部 BH＋4 時期穩健性、相似樣本 40＋Wilson 區間、加權歷史自動改抓證交所、playwright 腳本、免責一行
  - 駁回：硬規則放寬／給分（放寬就不是艾略特；軟指引已是給分；數不出就照實標）；價位驗證（§6 已有）；花費儀表板、效能進 CI（免費額度有上限；CI 只部署）

## 第 2 輪
- Gemini gemini-3.7-flash（完整計畫＋處置；3.6-flash 503）：**APPROVED**；3 個 low 全接受（08:20 日韓丟今天未收 K 棒、空頭推動浪對稱、同根 K 棒碰到又跌破＝跌破）（research/b74_plan_r2g.json）
- Groq planA：**APPROVED**；low 接受 5（Yahoo 只叫缺的測試、非 ISO 日期夜間檢查、資料過期標籤、相似樣本退到全部歷史要標示、1920 寬）（research/b74_plan_r2qa.json）
- Groq planB：REVISE — F1 Playwright 進 CI（第 2 次，駁回：無新證據、CI 只部署）；F2 樣本數（§5 已有）；F3 接受 每模型每日 token 上限＋單次不重試；F4 接受 /api/wave/status 來源健康（research/b74_plan_r2qb.json）

## 第 3 輪
- Gemini gemini-3.7-flash（完整）：**APPROVED**；low 2 個接受（盤中快照 2 分鐘、搜尋解析失敗當沒新聞）（research/b74_plan_r3g.json）
- Groq planB：REVISE 8 點 — 接受 F6（AI 全失敗顯示上一次成功的圓桌）；F1／F2／F3／F8 計畫已有；駁回 F4 Redis、F5 Slack、F7 CI 瀏覽器測試（第 3 次）（research/b74_plan_r3qb.json）

## 第 4 輪（最終）
- Gemini（3.7-flash、3.6-flash 都 503 → gemini-flash-latest）完整計畫＋處置：**APPROVED**，綁定 PLAN-B74.md SHA256 `23c978708cdf869dcf1c0f0fb89db84883f507e17312976dbde2caa4e8e387cf`（research/b74_plan_r4g.json）
  - low F1：支撐壓力不足 3 個（例如創新高沒有上方壓力）時推播／畫面不能出錯 → 實作時處理（用費波那契延伸／整千點補，沒有就寫「上方無歷史壓力」），不改計畫
  - low F2：連買／連賣天數用交易日列計算 → 實作時處理
- Groq：planA 第 2 輪 APPROVED；planB 第 3 輪 REVISE，未解決的都是主機駁回或計畫已涵蓋（CI 瀏覽器測試×3、Redis、Slack、再次提偷看／樣本數）→ 停止送 Groq 計畫審查（第 4 輪），立場見第 3 輪處置
- 結論：計畫以 Gemini 核准版開工；Groq 後半未全核准，上列駁回理由照實回報給用戶

## 實作（builder=Claude，開工前 commit f00d521，分支 b74）
- 研究：research/wave/{fetch,calibrate,run,report,verify_impl}.py；結果 research/wave/REPORT.md、results/stats_full.json、wave/stats.json
  - 級數校準（只用 2000–2015、看平均波段長度）：小級 m=2.0（10.1 天）、中級 4.0（37.9 天）、大級 11.5（166.5 天）
  - 91 個假設整體 BH：R1 費波那契（分布、守住率 37.6% vs 對照 37.3%）△；R2 所有價位類型 △（≥2 來源重疊 +3.0 點 [0.6, 5.4]、4 時期都正，但沒到 +5 點、q=0.13）；R3 浪別 △；R4 籌碼 △；R5 只有「前一晚費半 → 加權隔天」樣本外 R² 0.21 ✅（5／20 天沒有）；R6 相似狀態 Brier 比全部歷史差（20 天 −0.016）△
  - verify_impl：50 天 × 3 級數，截斷資料重算 vs 研究狀態 0 不一致
- **跟計畫不同**：R6 沒過 → 預測區間（圖上錐形、劇本文字）改用全部歷史分布，相似狀態只當參考（計畫 §4.7 原本畫相似狀態的區間）；另外加 GET /api/wave/report（研究報告純文字）
- 網站：wave/{engine,levels,features,forecast,data,service,panel,router}.py；regime-frontend/wave.js＋index.html 改版；server.py（路由、啟動、排程 08:20／13:45／16:30／21:40、全系統更新「大盤解析」步驟、/api/global-brief?wave=1）；course_live.push_premarket 加大盤段
- 總經修正：regime/db.iso_date＋normalize_dates（upsert_series 統一 ISO；一次性 breadth_v2 刪舊廣度重抓）、fetcher._parse_mi_index_ad（「上漲(漲停)」括號、只算股票欄）、略過邏輯改看「已有淨廣度」、factor 廣度不再 (v−50)×2、竭盡／集中度／背離門檻換算；router 更新後掃非 ISO 日期
  - 正式站原因確認：ISO 廣度停在 9/24（33.5 → 舊公式 −33）；MI_INDEX 標籤改版
- 體驗：/api/watchlist/summary 改本機 price_daily（local_prices_for_stocks），Yahoo 只叫本機不足 60 根的；分段計時 log [wl-summary]；dashboard 觀察清單快照 chip_wl_summary_v1、指數列與觀察清單並行、screen/status 只問一次、nav 桌機換行／手機漸層＋scrollIntoView
- AI 圓桌本機實測（gemini-3.6-flash＋gpt-oss-120b＋qwen3.8-27b）：124 秒、新聞 7 則、Gemini 第二輪與主持 503 → GPT-OSS 主持；價位檢查 0 個非系統價位；tokens：2.5-flash 5.4k、3.6-flash 4.9k、gpt-oss 10.7k、qwen 6.3k
- 驗證：pytest 330 passed（新增 tests/test_b74_wave.py 26 個、test_global_brief 2 個）；tests_ui/b74_ui.py 11/11（1366／1512／1920 分頁 15/15、390 可滑、快照第二次 0.17 秒、總經頁 0 JS 錯誤）

## 程式檢查（全新呼叫）
- Gemini 3.7-flash 後端新檔（wave/*.py＋research/wave/run.py）：REVISE 3 點全接受已修 — last_good 沒過濾 kind（會拿到新聞 JSON）、save_idx 量被 NULL 蓋掉（COALESCE）、單一 AI 推播寫成圓桌（research/wave/insp_g_backend.json）；沒有發現偷看
- Gemini 3.7-flash 既有檔 diff＋前端：APPROVED；2 點接受已修 — futureDays 時區少一天（改 UTC，node 驗證 10/23→10/26）、沒有 K 棒時防呆（research/wave/insp_g_frontend.json）
- Groq gpt-oss-120b（引擎核心規則摘錄 research/wave/insp_q_engine.json；完整檔 413 超過每分鐘 8,000 tokens、兩次 json_validate_failed 空輸出 → 第 3 次送去掉輔助函式的摘錄才成功；AI 圓桌檔太大沒送 Groq，由 Gemini 審過）：REVISE 3 點
  - F1 第 1 浪長度 0 會除以零：實際 ZigZag 轉折至少差 θ 不會發生，但加防呆（完成的浪長度 0 → 不算推動浪）＋測試 test_zero_length_wave_rejected_not_crash —— 這行防呆**沒有再送外部檢查**
  - F2 修正浪 lenA=0：駁回，程式已有 `if lenA > 0 else 99`（engine.py 兩處）
  - F3 WAVE_SYM 未定義：駁回，摘錄沒放、完整檔有定義
- Gemini 3.7-flash 第 2 次（全新呼叫，5 個修正的完整函式摘錄）：**APPROVED**（research/wave/insp_g_round2.json）
- 最終：pytest 331 passed；verify_impl 0 不一致；檢查輪數 2/2 用完
- 備註：第一次送 Groq 時去註解檔因編碼錯誤是空的，引擎與 AI 圓桌各送出一次空檔（回「看不到內容」，不算檢查，結果檔已刪）

## 部署後（a1aa1cc 部署 success）
- 正式站：wave.db 回補成功（TWII 6,570、SOX 6,739…）、FinMind 三個籌碼資料集正常、/api/wave/snapshot ok
- 觀察清單 summary 1.78／3.87／3.19 秒（原本 10 秒）；log [wl-summary]：local 0.14 秒，慢在 1 檔本機日 K 不足 60 根每次打 Yahoo 2.5～2.9 秒 → 加 10 分鐘 Yahoo 快取（_WL_YAHOO_CACHE）＋測試；Gemini 3.7-flash 全新檢查 APPROVED（research/wave/insp_g_round3.json）
- 22765f7 部署 success：summary 4.33（重開機後第一次要打 Yahoo）／0.58／0.59／0.63 秒；log local 0.14 秒、yahoo 0（快取）、total 0.33～0.37 秒
- 正式站廣度恢復每天更新（10/20 淨廣度 −40.22，跟證交所 269 漲／701 跌一致）；factor 廣度 −60.2（以前一個月卡 −33）
- tests_ui/b74_ui.py 對正式站 11/11 通過（分頁 15/15、手機可滑、快照第二次 0.32 秒、總經頁 0 JS 錯誤）
- 待用戶：`! bash claude-files/set_groq_secret.sh` 設 GROQ_API_KEY；第一次 AI 圓桌＝下個交易日 16:30 自動或手動按
