# PLAN-B81 審查紀錄（append-only）

- 2026-10-23 開始。協調／實作：Claude Code（Opus 5.5）。計畫審查＋程式檢查：Gemini（GEMINI_REVIEW_MODEL 預設 gemini-3.6-flash，503 時換 3.7-flash／3-flash-preview）＋Groq openai/gpt-oss-120b（用戶規定不用 Codex/GPT）。
- 範圍：用戶選 4 項全做＋試單地圖＋她的進出場拆解；授權：審查和測試通過直接推 main 上線；做完關機。
- 回合上限：計畫審查 5 輪、修正 2 輪、程式檢查 2 輪。
- 工作目錄：worktree claude-files/chip-tracker-b81（分支 b81，起點 cc4fc6f）。

## 計畫審查第 1 輪（plan sha 修改前）
- Groq openai/gpt-oss-120b：REVISE（reviews_b81/plan_r1.json）。Gemini 3.6-flash 503 → 換 3.7-flash 503、3.6-flash 當天免費額度用完（429）→ gemini-3-flash-preview：APPROVED（reviews_b81/plan_r1_gemini.json）。
- 處置：
  - Groq F1（隨機漫步沒漂移，加權長期往上）→ **採納**：改用有漂移的布朗運動先碰機率（μ、σ 取 t 以前 250 根），並要求同時贏隨機價位。
  - Groq F2（台指期換月）→ **採納**：結算日前後 2 天不取事件、不進相對量基準；價格結果用加權現貨。
  - Groq F3（bootstrap 區塊長度）→ **採納**：20 天與 60 天都跑，取保守的。
  - Groq F4（BH 家族要寫清楚）→ **採納**：試單家族 18 個，報告列全部 q。
  - Groq F5（加 axe-core 無障礙檢測）→ **不採納**：超出這次範圍、要多裝套件；手機版已有寬度與高度檢查。
  - Gemini F1（分 K 樣本短）→ **採納**：畫面註明「60 分 3 年資料」。
  - Gemini F2（同一根兩邊都碰算輸）→ **採納**：維持保守算法，報告列筆數。
  - Gemini F3（加權不能放空的標示）→ **採納**：加權頁寫「⚠ 減碼區」不同顏色標題。

## 計畫審查第 2 輪
- Groq：REVISE（reviews_b81/plan_r2.json）；Gemini 3-flash-preview 回的 JSON 後面多了文字（Extra data）→ 解析失敗，不算核准，下一輪重送。
- 處置（新增 §5b 共同規則）：
  - Groq F1（ATR 要只用過去）→ **採納**：寫明 14 根 Wilder ATR 只用 ≤ 當根。
  - Groq F2（R-A 的隨機漫步 μ／σ）→ **部分不採納**：R-A 不用隨機漫步（比的是同平均部位的固定持股）；μ／σ 規則寫在 §5b 給 R-C 用。
  - Groq F3（bootstrap 全部統一成平穩區塊 20／60 天）→ **部分不採納**：R-B／R-C 是不規則、會群聚的事件，用整年重抽的區塊 bootstrap＋年內置換檢定較合適；R-A 才用平穩區塊。寫清楚。
  - Groq F4（暖機期）→ **採納**：前 250 根、ATR NaN、相對量缺的不取事件；網站資料不夠不出試單。

## 計畫審查第 3 輪
- Gemini gemini-3-flash-preview：**APPROVED**（reviews_b81/plan_r3.json；兩個 low 建議計畫裡已有：分 K 用 60 分資料要註明、同一根兩邊都碰的筆數要列）。
- Groq：第一次 413（計畫＋回饋超過 8K token/分）→ 送省略 §0 偵察背景的版本（其餘全文相同）＋精簡回饋 → REVISE（reviews_b81/plan_r3_groq.json）。
- 處置：
  - Groq F1（隨機漫步模擬次數、種子、時限）→ **部分採納**：隨機漫步是公式不是模擬（不需要次數／種子）；但公式假設最後一定碰到 → 主要比較改只用 H 根內有結果的筆數、到期另列；隨機價位對照固定種子 20261023。
  - Groq F2（R-B 虛無假設）→ **採納**：寫明 H0、效果大小、95% 區間。
  - Groq F3（資料不夠的畫面標示）→ **採納**：「資料不夠，這個週期先不給試單」。
  - Groq F4（週 K 去重會誤刪）→ **採納並釐清**：只在母尺兩端價位都一樣時才拿掉週 K 的母尺價位；加兩種情境的測試。

## 實作偏離
- 偏離 1（§2）：試單的 S／R 原本「結構價位優先」；用 10-20 加權日 K 實測，上方第一個結構價位是轉強點 49,969（+7.9%），試空變成離現價 8% 才進場、賠率 15 倍，不合理。
  改成「上下最近的價位」（價位梯本來就只放窗口內 ≤4 個），跟她「彈到壓力」「回測支撐」一致；試空跟站上回測追多會用同一個價位（＝三條路的兩邊），這是刻意的。回測用同一個函式，所以定義仍一致。

## 計畫審查第 4 輪（最終）
- 計畫 sha256：2aa7db4280527b4bfd05e04555b5d44145965c2a09ac9810d6411d4574a40e7d
- Groq：**APPROVED**（reviews_b81/plan_r4_groq.json；看的是省略 §0 偵察背景、其餘相同的版本，因 8K token 限制）。兩個 low：ATR／μσ 只用到當根（§5b 已寫）。
- Gemini gemini-3-flash-preview（3.8-flash、3.5-flash 先試；3.6-flash 當天額度用完）：**APPROVED**（reviews_b81/plan_r4_gemini.json）。兩個 low：報告寫到期比例（已在計畫）、週 K 拿掉母尺時日 K 仍清楚標母尺（照做）。
- 偏離 1（實作時發現，見上）在核准之後，屬於定義調整，程式檢查時一起送審。
- 偏離 2（§5 補充）：主要比較照計畫用「t 以前 250 根」的 μ；另外加算「全部歷史平均 μ」的版本（edge_x）當敏感度，只報告、不影響 ✅ 判斷。
- 偏離 3（§2 補充）：回測比隨機差（區間上限 <0 且各時期都負、≥50 筆）的試單 → 不能當主要那筆、加「回測比隨機差，這個週期不建議」；加權的減碼區不加賠率／逆勢提醒（不是交易）；
  停損格備援不用加權的減碼區（改用賠率 ≥1 的多單）。現價已在進場區 → 標「現在就在這區」。手機把風險、AI 兩行收進「更多」（籌碼／AI 分頁有完整的）。

## 研究結果（research/b81/REPORT.md）
- 防偷看：400 個比對 0 不一致。
- R-C 試單：18 組全部 △；日 K／週 K「反彈壓力試空（順勢）」比隨機差（−9.1、−8.2 點，四個時期都負）→ 網站標「比隨機差」。
- R-A 建議持股：S0 Sharpe 差 +0.09（−0.14～+0.32）△；S1～S3 也 △ → 規則不變，標「紀律參考」。
- R-B 量能：15 個全部 △（A 組筆數多半很少）。

## 程式檢查
- 第 1 輪（全新 session）：
  - Gemini gemini-3-flash-preview 後端＋研究：**APPROVED**（reviews_b81/insp1_backend_gemini.json）；F1 μ 用穩健估計 → 不採納（事先定好、另有敏感度）；F2 風險下限 → 不採納（_rr 風險 ≤0 回 None）。
  - Gemini 前端：REVISE（insp1_frontend_gemini.json）：F1 rateS、F2 vpass 未定義 → **不成立**（wave.js 第 15、57 行就有，diff 沒帶到；本機 0 個 JS 錯誤）；F3 價格沒 esc → 不採納（fmt／pctS 只輸出數字）；F4 S.ladder 防呆 → 採納。
  - Groq levelmap：F1 現價 0／None → **採納**（回 ok False，加測試）；F2 Optional 沒 import → 不成立；F3 減碼區不檢查賠率 → 不採納（刻意，不是交易）。
  - Groq service：F1 top3 沒寫回 → **採納**（一定寫回 lm[tf]['top3']）；F2 後端 JSON 要 esc → 不採納（前端 esc）；F3 advice range 防呆 → 採納；F4 same_ruler(None) → 不成立（有處理）。
- 協調者另外改：停損格備援不用加權減碼區。
- 第 2 輪（全新 session，給完整 wave.js）：Gemini gemini-3.8-flash **APPROVED**（insp2_gemini.json）。
- Groq 前端（分 3 段，8K token 限制）：part2 F1 setups.list 防呆 → **採納**；F2 分隔符改「｜」→ 不採納（刻意改白話）；F3 zone 缺 → 不採納（同一版後端一定有）。
  part3 F1／F3 setupLine／setupBlock 沒 esc → 不成立（函式內每個字串都 esc；Gemini 第 2 輪確認）；F2 setupLine 未定義 → 不成立（part2 就有）。
  part3 之後的修改只有 setups.list 防呆一行，已跑 pytest 與 UI 腳本。
- 最終：pytest（專案 .venv）472 passed；tests_ui/b81_ui.py 本機 44 項＋B80 舊檢查全過；390 寬結論卡 729 → 508px。
