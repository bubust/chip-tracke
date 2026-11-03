# PLAN-B91 審查紀錄（/claudex-loop，append-only）

- 主機：Claude Code（Opus 5.5）＝需求、計畫、協調、實作（builder=claude）
- 計畫審查／最終程式檢查：依用戶設定（記憶 feedback_claudex_loop_reviewers）**不用 Codex**，改 Gemini＋Groq（claude-files/claudex-review2.py）；模型：Gemini gemini-3-flash-preview（或當天可用的 flash）、Groq openai/gpt-oss-120b
- 範圍：PLAN-B91.md（13:15 清單、日線多頭結構、大盤盤面、盤勢研究）
- 授權：用戶選「測試＋審查通過就上線」→ 可以實作、通過後推 main
- 輪數上限：計畫 5 輪、修正 2 輪、程式檢查 2 輪
- 工作目錄：worktree claude-files/chip-tracker-b89（分支 b89-tail，from origin/main 6435783）

## 第 1 輪（plan_r1.json；Gemini gemini-3-flash-preview REVISE、Groq gpt-oss-120b REVISE）
處置：
- G-F1（高）結構用全天低點 vs 13:15：**部分接受** — 全天低點 ≤ 13:15 低點 → 研究比盤中嚴格（方向寫進 REPORT）；用正式站 98 筆量化 13:10 清單 vs 收盤版 S_FBD 成立率
- G-F2 收盤 vs 13:15 進場價：**接受** — 98 筆 13:10 價 vs 收盤差的分布＋不利方向敏感度重算 Q2
- G-F3 M8 暖身：**接受** — 研究跟網站都用 idx_daily（2000 年起）；資料不足＝None 不碰規則
- G-F4 ALTER 先同步做：**接受**
- Q-F1／Q-F3 收盤代替 13:15（look-ahead）：**部分接受** — 大盤特徵本來就用真的 13:15 指數；個股 13:15 歷史拿不到、不能「排除沒有盤中資料的日子」（全部都沒有）→ 用上面的量化＋敏感度處理，網站註明近似
- Q-F2 隨機對照用當天量：**接受** — 流動性只用前一天以前、固定種子
- Q-F4 重試／告警：**部分接受** — MIS 重試 1 次→鉅亨→都失敗照發＋log；不做額外告警（個人網站，Telegram 本身就寫「抓不到」）
- Q-F5 補算併發：**接受** — 模組鎖 non-blocking

## 第 2 輪（plan_r2.json；Gemini gemini-3-flash-preview **APPROVED**（3 個 low）、Groq REVISE）
處置：
- Q-F1（高）「盤中用全天低點」：**駁回（誤讀）** — 計畫寫的是盤中用即時開高低收；已把 1.1 改寫得更明確（struct_check 只吃呼叫端給的 K 棒，網站盤中給到現在的低點、研究給全天）
- Q-F2 挑格 post-hoc：**駁回** — 挑格只在樣本內、樣本外只驗一次＋18 個一起 BH，跟 B82 同一套；另外每族每格的樣本內外統計全部列出（已補）
- Q-F3 補算要並行／指數退避：**駁回** — 缺的天數很少（一天一筆），證交所一個請求本身要 ~10 秒、並行有被擋風險；已補逾時 40 秒、失敗計次、同一天最多 5 次
- Q-F4 ALTER TABLE 改成換表遷移：**駁回** — SQLite ADD COLUMN 只改 schema、原子操作，不需要換表
- Q-F5 13:15 抓大盤重試：已有（MIS 重試 1 次→鉅亨→抓不到照發、之後補算）
- Q-F6 種子：**接受** — SEED＝20261103 寫在程式與 REPORT
- Q-F7 手機大表：**接受** — 不計入表先顯示最近 30 筆＋「顯示全部」
- G-low F1 結構不明占比：**接受**（研究另列）；G-low F2 補算優先缺大盤的日子：**接受**（已寫）；G-low F3 S_FBD 13:10 vs 收盤變動率：已在 ①

## 第 3 輪（plan_r3.json；Gemini **APPROVED**（3 low）、Groq REVISE）
⚠ 這一輪的修改腳本有一個錨點沒對上（sox 那句），整份修改沒寫入 → plan_r4.json 審的是第 3 輪原文，**第 4 輪作廢**（不算核准、不算輪數以外的理由：照實記錄），修改確實寫入後重送第 4b 輪
處置：
- Q-F1（高）13:15 之後低點會變：**接受（補寫）** — 13:15 算的 struct／大盤存進資料庫就固定，只補 NULL、改進場日才重算
- Q-F2 指數退避：**駁回** — 已有 MIS 重試→鉅亨→照發＋之後補算；13:15 那一次多等幾秒沒有好處
- Q-F3（高）補算會卡開機：**駁回（誤讀）** — 補算在背景執行緒，不擋開機也不擋 list
- Q-F4 BH 0.10 太寬：**部分接受** — 維持 0.10（跟 B73／B82 同標準，可比較），JSON 同時存原始 p、校正 p
- Q-F5 分頁：已有（30 筆＋顯示全部），駁回
- Q-F6 兩來源都掛的測試：**接受**（fbd_live、補算各加）
- Q-F7 亂數：**接受** — 一律 np.random.default_rng(SEED)
- G-low F1 費半同一來源：**接受**；F2 大盤資料缺要跟「一般」分開：**接受**；F3 M8 滾動 250 天：**接受**（寫清楚）

## 第 4 輪（plan_r4.json）— 作廢：審的是沒寫入修改的舊版（腳本錨點錯）。Gemini REVISE、Groq REVISE；其中仍有效的新意見一併處置：
- G-F1（高）13:15 固定 vs 研究用全天：**部分接受** — 13:15 的決定維持固定（那是進場當下），另外收盤後算 struct_eod 只做對照（標「收盤後跌破前低」、統計 13:15 合格但收盤不合格的比例）
- G-F2 BH 只校正挑出來的 18 個：**駁回** — 挑格只用樣本內，樣本外對挑出來的格只驗一次；樣本外資料沒參與挑選，18 個樣本外檢定 BH 是有效的（look-elsewhere 已由切樣本處理）；所有格的描述統計全部列出
- G-F3 波段確認落後 3 天：**接受（寫明限制）**，不加條件 — 現在的狀態由 S_FBD（站回 MA10、收紅）＋ H1 之後最低 > L1 把關
- Q-F1 兩來源都掛就暫停清單：**駁回** — 用戶要清單，大盤只是標示
- Q-F2 補算並行：**駁回（重提）**
- Q-F3 swing_seq 效能：**駁回** — 盤中只對成立的幾十檔×130 根算；研究一次 1,900 檔，秒級
- Q-F4 bootstrap 運算量：**駁回** — 18×2000 次 numpy 抽樣，秒級
- Q-F5 0.5% 容差：**駁回** — 只是一致性檢查門檻，比對結果會列在 REPORT
- Q-F6 沒規則通過的訊息：已有（「研究沒找到明顯比較好或比較差的盤勢」＋各盤勢歷史數字）
- Q-F7 Telegram 長度：**接受** — 計入沿用 40 行上限、不計入一行最多 30 檔

## 第 4b 輪（plan_r4b.json；審確實寫入修改的版本）— Gemini **APPROVED**（1 medium、1 low）、Groq REVISE
處置：
- G-F1 統計 13:15 合格但收盤後不合格的比例：已在計畫（struct_eod），REPORT 列出
- G-F2 M8 point-in-time：**接受** — 寫明只用訊號日以前
- Q-F1 補算退避：**駁回（重提第 3 次）**
- Q-F2 收盤後對照：已做（就是 struct_eod）
- Q-F3 BH 相依：**接受（寫明）** — BH 在正相依（PRDS）下有效，REPORT 寫前提
- Q-F4 費半時區：**駁回** — 用日期比較「美國日期 < 台灣今天」的最後一筆就是前一晚收盤，不受夏令時間影響；**加測試**（週一→週五、美國假日）
- Q-F5 資料缺 vs 一般：已分開（駁回）
- 依記憶（Groq 每輪都提新點、重提已駁回點）：Groq 不再送第 5 輪；第 5 輪只送 Gemini 確認最終版

## 第 5 輪（plan_r5.json；只送 Gemini）— **APPROVED**（最終計畫 SHA256 2814a01b…，之後計畫沒再改）

## 實作（builder＝Claude，主機自己寫）
- 用戶中途追加兩項（同一批做）：總經頁過熱恐慌放最上面、融資維持率正確率驗算＋融資使用率
- 證交所 MI_5MINS_INDEX 4 段同時抓被擋 → 停掉、解封後 2 段間隔 6 秒

## 程式檢查
- Groq gpt-oss-120b（tail_market.py 去註解版＋course2 摘錄；insp_q_market.json）REVISE：F1／F2 f-string 引號 SyntaxError → **駁回**（ast.unparse 引號假象，原檔外層雙引號、48 項測試都有載入）；
  F3 昨收不是數字、F4 日 K 有 0／NaN → **接受**（加防呆＋測試）
- Gemini gemini-3-flash-preview 後端（tail_market、tail_track、fbd_live、margin_maint、cb/parser、cb/fetcher、regime/router 完整檔＋course2 摘錄＋diff；insp_g_backend.json）**APPROVED**，0 個 finding（之前 503 好幾次，第 3 輪重試成功）
- Gemini 前端（tail.js 完整＋dashboard／regime diff；insp_g_front.json）**APPROVED**，2 low：編輯進場價空白會送 0 → **接受**；盤勢標籤對不上 → **駁回**（label 是後端固定 key，前端有 nodata 預設）
- 研究程式（research/b91/run.py、report.py、margin_check.py）結果出來後另外送
- Gemini gemini-3-flash-preview 研究程式（run.py、b91_report.py、verify_impl.py、tail_market.py、REPORT.md＋engine／course2 摘錄；insp_g_research.json）**APPROVED**，2 low：
  struct_series 重算最低的效率（日 K 量級沒問題，不改）、S_FBD 量含今天（跟掃描同一套、一致 99.98%；盤中版今天量＝max(累計, 前 20 日均量)，不改）

## 研究結果（research/b91/REPORT.md）
- S_FBD 向量化 vs B82 逐日呼叫 13,734／13,737；網站最近 131／261 根 vs 研究整段 結構 500 抽樣 0 不一致；13:15 快照 3 天網站補算＝研究分 K 檔
- 18 個檢定沒有通過 → tail_research.json rules 全部 pass=false → 網站不標 ✅／⚠，改用大盤日線多頭／盤整／空頭分組描述
- 結構：樣本外 26.1%／−0.32% → 26.7%／−0.18%；事後觀察：盤整 5／6 年負（2023 例外），寫明沒檢定
- 研究期間被證交所擋一次（見上），補抓完 1,234 天
