# PLAN-LEVELS 審查紀錄（append-only）

- 2026-10-05 開始。角色：主持／規劃／實作＝Claude（Claude Code, claude-opus-5-5）；計畫審查與最終程式檢查＝Gemini（gemini-3.6-flash，429/503 時用 GEMINI_REVIEW_MODEL 換）＋ Groq（openai/gpt-oss-120b）。依用戶設定不用 Codex。
- 範圍：price_levels.compute_levels 新增支撐價／停損價、目標價規則改版；dashboard 關鍵價位欄／明細／K 線線條；研究腳本進 research/levels/。另一項「K 線標題補股名」用戶說不用討論，已直接修（commit 86daa8a）。
- 授權：用戶「研究出好的模式之後更正」→ 計畫通過審查後直接實作、push 部署。
- 輪數上限：計畫審查 5 輪；修正 2 輪；檢查 2 輪。
- 研究資料與腳本：session scratchpad levels/（pd.csv.gz 為正式站 price_daily 匯出，不進 repo）。

## Round 1（plan_r1.json）— Gemini gemini-3.6-flash: REVISE；Groq gpt-oss-120b: REVISE
處置：
- Gemini F1（等幅除以零／沒有 L0）→ 接受：明寫先檢查 L0 存在、H1−L0>0。
- Gemini F2 + Groq F1（ATR 為 0／NaN、短歷史）→ 接受：ATR 下限 現價×0.5%＋NaN 防護；compute_levels 既有 ≥30 根門檻已保證 ATR 可算（Groq 說 <14 根會 NaN：既有門檻已擋，降為已處理）。
- Gemini F3（60 日低不足 60 根）→ 接受：不足就用全部。
- Gemini F4 + Groq F4（前端舊快取缺新欄位）→ 接受：所有新欄位防護、_levelsPrimaryStop 退回舊 stops。
- Groq F2（停損會高於支撐）→ 部分接受：保留設計（證據：改用較近支撐 edge 3.4→2.4 且仍 17% 高於支撐），但加 stop.basis=cap、前端標「上限」、明細寫原因、加測試。
- Groq F3（±1.5pp 一致性太嚴、CI 不穩）→ 接受說明：那是一次性驗證腳本不是 CI；容許 ±2pp（抽樣誤差）。
- Groq F5（沒有波段點畫面空白）→ 接受：顯示「—」＋明細說明，stop.basis='atr' 標示。

## Round 2（plan_r2.json）— Gemini：503 UNAVAILABLE（gemini-3.6-flash、gemini-2.5-flash 都忙線，未算一輪）；Groq gpt-oss-120b：APPROVED（只送第 1、4、6 節＋第 1 輪處置，因為全文超過 8000 TPM）
處置：
- Groq F1（盤中未完成 K 棒）→ 部分接受：即時價位本來就該用最新 K；在 4.1 寫明盤中影響範圍，不改算法。
- Groq F2（60 日低 0.995 門檻在平盤時沒有支撐）→ 不改：沿用研究設定，文件寫明會顯示「—」。
- Groq F3（OpenAPI schema）→ 駁回：回傳是 JSONResponse dict，沒有外部使用者也沒有 schema。
- Groq F4（低價股 ATR 下限）→ 駁回：台股最低價約 1 元、0.5% 下限 0.005 已 > 0；價格四捨五入到 2 位不會變 0（計算時不四捨五入）。

## Round 2（Gemini 補跑，plan_r2_gemini.json）— Gemini gemini-2.5-flash：APPROVED（無 findings）
- gemini-3.6-flash／3.7-flash 連續 503，背景重試後 gemini-2.5-flash 成功（19:06:39，早於 price_levels.py 開始修改的 19:06:59，審的是原始版本）。
- Gemini APPROVED 的是目前這份 PLAN-LEVELS.md；Groq 的 APPROVED 是在加入「盤中未完成 K 棒」說明（回應 Groq F1、純文件一行）之前的版本，之後沒有再送 Groq。目前版本（sha256 前 16 碼 fd1b02a3dc77fac8）。進入實作；pre-build commit 86daa8a。

## 實作中發現（2026-10-05，一致性驗證）
- verify_impl.py 第一次（3,000 樣本）：支撐、停損與研究一致；**等幅目標到頂 edge 對不上**（−3 vs 研究 +7.3，前後段都反向）。查出研究腳本兩個基準錯誤：(1) 子集合用全部樣本距離洗牌（多頭距離較遠→灌水）；(2) 約 10% 等幅目標在現價下方，負距離洗進基準壓低到頂率。修正 research.py 後全部重跑：壓力仍無 edge；支撐全部樣本結論不變；停損直接模擬報酬不變，但「多頭少被洗 13～15 點」撤回（實為 ≈0，改善來自留空間）；目標價各算法都 ≈ 隨機（等幅 +7、多頭前高 +12.6 都撤回）。
- 設計調整：目標價優先序不變但理由改成「照用戶規則」；新增 rr（報酬風險比）與 downside_pct；移除前端／程式中「等幅最準」「多頭前高常被碰到」等說法；120／240 日線提示改為純參考。
- 同時發現既有 bug：detect_thunder retrace=None 時格式化 TypeError（10,000 樣本舊版 4 次）→ 修正＋回歸測試。
- 第二次驗證（10,000 樣本）與更正版研究一致（見 PLAN 第 6 節第 3 點）。
- 計畫已變更 → 送第 3 輪計畫審查。

## Round 3（plan_r3.json）— Gemini gemini-2.5-flash：APPROVED（無 findings）；Groq gpt-oss-120b：APPROVED（3 個 low）
- Groq F1（ATR 下限對低價股）→ 駁回：price>0 時 0.5%×price>0，不會是 0；台股不會有 0 元。
- Groq F2（3ATR 目標過高）→ 駁回：台股 10% 漲跌停，ATR14 實務上 < 10%，3ATR < 30%。
- Groq F3（手機三行溢出）→ 已是三行堆疊＋nowrap；部署後用手機寬度截圖確認。
- 計畫定稿。進入程式檢查（fresh Gemini + Groq）。

## 程式檢查（fresh sessions）
- Gemini gemini-2.5-flash（price_levels.py、tests 全檔＋dashboard 關鍵價位／openChart 片段＋py diff）：APPROVED，無 findings。
- Groq gpt-oss-120b（分兩份：py diff、dashboard 片段；TPM 限制）：
  - py diff 第一次 JSON 驗證失敗（空輸出），重試：REVISE F1「支撐價應 ×0.99」→ 駁回：測試資料 make() 的 low＝close×0.99，測試預期的就是原始低點；PLAN 定義支撐＝波段低點本身；82 個測試通過。
  - dashboard 片段：REVISE F1（批次 ids 沒 encodeURIComponent）→ 接受（原有程式，一行強化）；F2（thunder 欄位沒 escape）→ 駁回：都是數字，唯一字串 stage 有 _esc；F3（stop.price null 顯示）→ 駁回：_levelsPrimaryStop 只在 price != null 時回傳 lv.stop。
  - 修正後 fresh 再檢查：REVISE F1（th.retrace 為 null 時顯示「回檔 0%」）→ 接受（後端修 thunder bug 後才會出現的狀態）：加 th.retrace != null 判斷。
- 檢查輪數已用 2（初檢＋修正後複檢）；最後一個一行修正（retrace 判斷）未再送檢，如實記錄。

## 第二階段（2026-10-05 用戶回饋：移動停損＋停損高於支撐很怪）
- 研究：trailing.py（9＋10 種出場方式）、sup_trend.py（強勢／拉回延伸的支撐）。用戶 5／10 日線規則在強勢延伸 +1.12%（40 天 11 次進出），推薦的 20 日線−1ATR +3.98%、舊上限 +4.75%。子集合支撐 edge 單次洗牌雜訊 ±2～3（10 日線 +4.2 → 20 組平均 +1.9），已改用 20 組平均。
- AskUserQuestion：用戶選「照我的 5／10 日線規則」「撐用前低、損放前低下方（不設上限）」。依用戶決定設計，PLAN 第 7 節。送第 4 輪計畫審查。

## Round 4（plan_r4.json）— Gemini gemini-2.5-flash：APPROVED（1 low）；Groq gpt-oss-120b：REVISE（只送第 7 節）
- Gemini F1 + Groq F1（MA NaN）→ 接受：明確 NaN 檢查，NaN 走一般規則（≥30 根門檻下實際不會發生）。
- Groq F2（移除 basis=cap 破壞下游）→ 駁回：唯一使用者 dashboard，前端對未知 basis 無依賴。
- Groq F3（價格跳動讓 MA5≤MA10 時 stop≥support）→ 駁回：無狀態、每次用當下 MA 重算，trail 進入條件即 MA5>MA10；floor 分支也必然 stop<support。改在 7.5 寫明不變式並用隨機走勢測試驗證。
- Groq F4（測試只有正常路徑）→ 接受：60 組隨機走勢（含 30 根短歷史）驗證不變式與 basis 集合。

## Round 5（Groq only，plan_r5_groq.json）— REVISE；已達計畫審查上限 5 輪，停止並記錄主持人立場
- Groq F5（floor 會讓 stop > support）→ 駁回：floor 是「取較低者」stop＝min(support−0.5ATR, p−1.5ATR)，只在 support > p−ATR 時生效，此時 stop＝p−1.5ATR < p−ATR < support。Groq 例子（support＝p−2.5ATR）不會觸發 floor。仍依 F7 加一個固定案例測試。
- Groq F6（cap 移除影響下游服務）→ 駁回：全 repo grep `basis`，stop.basis 只有 dashboard.html:1776 與 tests 使用（warrant/futures 的 basis 是期貨基差，無關）。
- Groq F7（固定案例測 floor）→ 接受。
- Gemini 第 4 輪已 APPROVED 第 7 節（含 NaN 檢查建議，已採納）。依用戶授權進入實作。

## 第 7 節程式檢查（fresh）
- Gemini gemini-2.5-flash（price_levels.py、tests 全檔＋dashboard 關鍵價位片段＋diff）：APPROVED，無 findings。
- Groq gpt-oss-120b（diff；第一次 503 over capacity，重試成功）：REVISE F1「拿掉 _r(m5) > _r(m10)」→ 駁回：這是刻意的，兩線四捨五入相同時畫面上支撐＝停損會破壞「停損 < 支撐」，此時走一般規則；已在程式加註解說明（不改邏輯）。
- 測試 85 passed。
