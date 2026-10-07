# PLAN-DEEP2 review log（2026-10-07）
- Roles: host/planner/builder = Claude Code (Opus 5.5); plan reviewer + final inspector = Gemini (GEMINI_REVIEW_MODEL) + Groq openai/gpt-oss-120b via claudex-review2 (user preference: no Codex). Groq gets condensed English plan (TPM limit).
- Scope: 同步買訊號修正＋深度分析改版（PLAN-DEEP2.md）。Authorization: user asked for the fix + redesign; build + deploy authorized per project practice (each batch deployed).
- Limits: plan rounds 5, inspection rounds 2.

## Round 1（r1.json in session scratchpad）
- Gemini gemini-2.5-flash: APPROVED（4 low：回測免責、composite_score 消費者、籌碼日後回測、1% 單筆風險註記）
- Groq gpt-oss-120b: REVISE（high：未回測項影響建議；medium：資料源脆弱／Yahoo 備援、期間短／成本／存活偏差、成本與波動部位、ETF／新上市、測試；low：composite_score 相容、TTL）
- 處置見 PLAN-DEEP2.md §9；另補前後兩段＋逐月穩定度研究（強勢 +2.39%／+2.63%，弱勢 −0.63%／−2.03%，14/18 個月強勢贏）

## Round 2（r2.json）
- Gemini gemini-2.5-flash: APPROVED（low：產業排名定義、sector.db 來源）
- Groq gpt-oss-120b: APPROVED（medium：信心區間、流動性；low：成本進部位、假日負快取、新上市、棄用欄位、預熱、E2E）
- 小幅修改計畫（§5 產業定義、流動性、成本進部位；§10 處置）→ 送第 3 輪確認最終文字

## Round 3（r3.json）
- Gemini: APPROVED
- Groq: REVISE（high：產業過期、部位除以零；medium：低量股、欄位變動、SQLite 併發；low：籌碼分開、移動停損、大盤）
- 補跑低量股回測（30～300 張：技術分類沒優勢）＋低量股機率表；處置見 §11

## Round 4（r4.json）
- Gemini: APPROVED（low：千張大戶來源）
- Groq: REVISE（high：法人晚一天〔事實錯誤〕、部位上限；medium：樣本少、新鮮度、成本；low：除權息、介面、失敗測試）→ 處置 §12

## Round 5（r5.json）
- Groq: REVISE（high：缺分項重算分母會灌水、未回測籌碼影響建議〔第 1 輪已處置〕；medium：盤中法人資料、整體部位風險；low：除權息〔非目標〕）→ 都是第 1～4 輪處置過的點、沒新證據，維持原處置
- Gemini: 2.5-flash／3.6-flash／flash-latest 連續 503（高負載、逾時）→ 本輪沒有 Gemini 結果（作業失敗，不算通過）
- 結論：Gemini 第 1～4 輪 APPROVED（第 4 輪後只改了單檔上限 25%、n<30 不顯示、千張大戶來源註記、失敗測試）；Groq 5 輪都 REVISE（每輪提新點、重提已處置點）。已達 5 輪上限，依用戶授權進入實作；最終程式檢查再送兩方
- 實作中發現：price_daily 有少數列量是 NaN（20 日均量變 NaN）→ vol20 改 min_periods=15；另有 10 列量是「股」不是「張」（2024-11～2025-03，7 檔），影響極小

## 實作（Claude 實作，pre-build commit 83bae9d）
- 測試：原有 120＋新增 40（test_signal_sync 7、test_deep_verdict 22、test_deep_data 11）＝160 全過
- 本機（獨立 venv、Supabase 關、真的跑 chip_course.refresh() 回補 22 個交易日／71 秒）：4583／2449／6488／0050／1102 deep-analysis 都 200、約 1～2 秒；playwright 桌機＋手機各 tab 截圖、沒有 JS 錯誤、🔄 會重新載入
- 實作中的偏離（已寫進 PLAN-DEEP2 §13）：D1 做多只給強勢（或中性且 ≥70）、D2 平均每筆結果＋「等突破或拉回」、D3 量的單位（股→張）、D4 vol20 容忍缺值、D5 FinMind 英文法人名稱、D6 產業至少 10 個、D7 台股配色

## 最終程式檢查
- Gemini gemini-2.5-flash（i1g.json，完整新檔＋diff＋標明的節錄＋測試）：APPROVED，無 finding；限制：FinMind 快取沒鎖，同時請求可能重複呼叫（無害）
- Groq gpt-oss-120b（拆 4 批、去註解版，TPM 限制）：
  - 批 1 deep_verdict.py：兩次 json_validate_failed（空輸出）→ 這個檔只有 Gemini 檢查過
  - 批 2 deep_data＋cb：REVISE 3 點全部不成立（f-string 語法〔模組可 import、測試過〕、num 未 import〔cb/parser.py:12 有定義〕、EPS 除以零〔已有 `and q[ds[-5]]` 防護〕）
  - 批 3 chip_course＋chip_tracker_v2：第一次輸出太長失敗；重試 REVISE 4 點：T86 欄名拼錯（不成立，實際回應就是這個欄名）、classify_signal 重複參數 TypeError（不成立，實測可呼叫）、have_s 判斷（不是 bug，只會多抓）、連線例外時沒關（接受，改 contextlib.closing）
  - 批 4 server 節錄：REVISE 2 點：短歷史 KeyError（不成立，實測 12／50／129 根都有欄位、評價正確拒絕）、伺服器要 HTML 跳脫（拒絕：回 JSON，前端全部經 _esc，Gemini 已確認）
- 檢查後修改（closing）→ 新的 Gemini session 重檢 chip_course.py（i2g.json）：closing 正確；唯一 finding「空資料也寫 fetch_log」不成立（_log 內有 `if n > 0`，測試也驗證假日不記）
