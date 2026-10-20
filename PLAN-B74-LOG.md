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
