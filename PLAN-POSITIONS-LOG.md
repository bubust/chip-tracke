# PLAN-POSITIONS 審查紀錄（append-only）
- 2026-10-05 開始。主持／規劃／實作＝Claude（claude-opus-5-5）；審查＝Gemini（gemini-2.5-flash，3.6 常 503）＋ Groq（openai/gpt-oss-120b）。輪數上限：計畫 5、修正 2、檢查 2。授權：用戶要求加入兩種模式＋盯盤 → 通過審查後實作、push 部署。
- 用戶決定（AskUserQuestion）：只有持有股發 Telegram；盤中每小時＋收盤後檢查。

## Round 1（pos_r1.json）— Gemini：APPROVED（2 low）；Groq：REVISE
- Gemini F1（40 天期間短）→ 記為限制（研究就是 40 天持有期、約 4 萬樣本），不改設計。F2（compute_levels 新增 high 要記錄）→ 接受，PLAN-LEVELS 第 9 節。
- Groq F1（跨 phase 去重）→ 部分接受：target 去重鍵改為不含 phase；停損「盤中預警」與「收盤確認」刻意是兩種通知（各自每日一次），寫明理由；新增 stop_clear（盤中預警後收盤站回 → 解除通知）。
- Groq F2（floor ≥ 目標價矛盾）→ 駁回：目標價 > 現價，floor ≥ 目標必然 floor > 現價＝breached，已處理；計畫寫明。
- Groq F3（成本合理性）→ 部分接受：有收盤價時須在 0.2～5 倍；cost_at 用台灣時間 ISO（與 added_at 一致，不改 UTC）。
- Groq F4（跨 phase 去重測試）→ 接受。

## Round 2（pos_r2.json）— Gemini：APPROVED；Groq：APPROVED（4 low）
- Groq F1（不改原 dict）→ 接受：deepcopy。F2（stop_clear 狀態）→ 已是 push_log（SQLite、持久）查當日 stop_warn ok=1。F3（成本驗證用最新價）→ 接受：用 _levels_for 的現價（盤中含即時價）。F4（UI 區分）→ entry10 已有專屬標籤，維持。
- 計畫定稿，進入實作；pre-build commit b2f2c54。

## 實作中發現（計畫錯誤）
- 價位是無狀態、用當下價格重算：股價下跌時支撐／停損跟著往下移 → 「現價 < 現在的停損」永遠不成立，盯盤永遠不會發通知。改成跟「前一根 K 棒為止算出的停損／目標」（prev）比。PLAN 4.2、4.4、5 已改；送第 3 輪計畫審查。

## Round 3（pos_r3.json）— Gemini：REVISE；Groq：REVISE
- Gemini F1（price_levels.py 還沒有 prev）→ 不是計畫缺陷：送審時明說附檔是改動前版本，實作在後；程式檢查時再驗。
- Groq F1（prev 停損 None 時 max 會錯）→ 接受：取有值者最大、兩者都沒有 → None。F2（prev 預設值）→ 接受：prev=None。F3（單股快取失效）→ 接受：_levels_for(sid, fresh=True) 先 pop 快取。F4（測試涵蓋訊息與去重）→ 接受。

## Round 4（pos_r4.json）— Gemini：APPROVED；Groq：APPROVED（5 low，皆不改）
- F1 成本範圍 0.2～5 倍已寬鬆；F2 去重日期用明確的台灣日期；F3 函式回新 dict、呼叫端用回傳值；F4 同日碰目標又跌破停損是兩件事，兩則都發；F5 失敗（ok=0）下一個排程時段自動重試（去重只看 ok=1）。

## 程式檢查（fresh）
- Gemini gemini-2.5-flash（price_levels.py、test_positions 全檔＋server／dashboard 片段）：REVISE F1（強勢延伸停損 min(...) 跟計畫字面不同）→ 駁回：PLAN-LEVELS 8.2 就是 min(20 日線−1ATR, 10 日線−0.5ATR, 價−1.5ATR)；F2（載入失敗不重試）→ 小優化，不改。
- Groq（拆 py／server／js diff）：
  - py F1（h 未定義）、F2（prev.stop 是 dict）→ 駁回：h 在 compute_levels 內定義；prev 由 server 存成數字；測試通過。F3（價格 0 除以零）→ 接受：price ≤ 0 直接回傳。
  - server F1（日期格式 YYYY-MM-DD vs YYYYMMDD）→ 查證：_parse_yahoo_json 與 price_daily 都是 %Y%m%d，不會不符；仍加 replace("-","") 防呆。F2（Telegram 沒 escape）→ 駁回：sid／名稱／label 已 html.escape，其餘是數字。F3（cost 是字串）→ 駁回：寫入一律 float。F4（成本驗證用快取價）→ 駁回：10 分鐘快取對 0.2～5 倍範圍足夠。F5（emoji）→ 駁回：常數。
  - js F1（數字沒 _esc）→ 駁回：API 數字欄位。F2（輸入框 id 重複）→ 接受：id 加代號。F3（_levelsCell 參數）、F4（flag 沒空格，實為 <br> 開頭）、F5 → 駁回：誤讀。
- 檢查輪數用 1（初檢）；修正都是一兩行防呆，未再送檢，如實記錄。
