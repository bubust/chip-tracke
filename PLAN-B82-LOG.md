# PLAN-B82 審查紀錄（append-only）

- 角色：主持／計畫＝Claude Code（Opus 5.5，本 session）；計畫審查＝Gemini＋Groq（依記憶：不用 Codex/GPT CLI，claude-files/claudex-review2.py）；實作＝Claude；最終檢查＝Gemini＋Groq（全新 session）
- 範圍：PLAN-B82.md（每天 18:00 新結果、策略篩選頁版面、R1～R4 策略優化研究）
- 授權：用戶選「通過就上線」（審查＋測試通過後推 main 自動部署，避開 18:00 掃描時段）
- 輪數上限：計畫 5 輪、修正 2 輪、程式檢查 2 輪
- 工作目錄：claude-files/chip-tracker-b81（分支 b82，從 origin/main 4ca46ff）；研究資料 research/b82/data（gitignore）

## 計畫審查第 1 輪（2026-10-23 23:5x）
- Gemini gemini-3.6-flash：503 高負載（作業失敗，不算）→ gemini-3-flash-preview（完整計畫＋run825.py＋run_quality.py＋fetch_all.py）：**APPROVED**；F1 中（融資 21:30 才公布）、F2 低（重複請求）、F3 低（手機格子字）。結果 reviews_b82/plan_r1_gemini.json
- Groq gpt-oss-120b（計畫拆 A §0–2、B §0＋§3＋§5–7、C §0＋§4）：三份都 REVISE。結果 reviews_b82/plan_r1_groqA/B/C.json
- 處置（reviews_b82/disp_r1.md）：接受 融資 MARGIN_LAG＝1、明確對齊常數＋測試；成交規則（升降單位、穿價才成交、一價漲停、盤中買進日不算停利）＋成交率／加滑價敏感度；server_now、Asia/Taipei、掃描中不換結果、no-store；in-flight 去重；只認 passed＋測試。駁回：排隊／VWAP 模型、SSE、CI 部署閘、巢狀交叉驗證（樣本內挑、樣本外一次檢定＝B73 同設計）、<360px 單欄、safe-area；A-F2（BH 已在 §4，該份看不到）

## 計畫審查第 2 輪
- Gemini gemini-3-flash-preview（完整計畫＋3 個完整檔＋第 1 輪處置）：**APPROVED**，3 個低（in-flight 一定釋放、敏感度足夠、格子字省略）
- Groq：B **APPROVED**；A、C REVISE（多為重提已處理、或該份看不到的章節）
- 處置 reviews_b82/disp_r2.md：接受 v1 舊 key 清掉＋UI 測試、報告寫預期假發現與各年勝率；其餘駁回

## 計畫審查第 3 輪
- Gemini：**APPROVED**（F3 月營收遇假日延後 → 接受，改 15 日／2 月 20 日；F1 jitter 駁回）
- Groq A **APPROVED**；Groq C REVISE（跨分頁協調、<360px 駁回；自動更新測試已在 §7；aria-controls 接受）。處置 reviews_b82/disp_r3.md

## 計畫審查第 4 輪（最終版）
- Gemini gemini-3-flash-preview：**APPROVED**，綁定 PLAN-B82.md SHA256 6fbfeb3f8030554a590af03a7f7b8e91e44dce7e2f9add95f104a42d653b1c54
  低／中建議（實作時處理，不改計畫）：背景檢查失敗不清 localStorage、不重複跳錯誤提示；R3 出場沿用 run825 的「開盤跳空跌破停損＝開盤價出場」優先；手機一句結論太長要省略
- Groq 最終狀態：A、B 份核准；C 份最後一次（第 3 輪）REVISE 的點都已駁回／已涵蓋，依記憶（Groq 每輪重提已駁回點）不再送。**最終版 Groq 沒有逐份重新核准**，照實記錄
- 研究資料下載中（research/b82/fetch_all.py 背景，2021-01～2026-10-22）

## 程式檢查第 1 批（A＋B 網頁／後端，2026-10-24 00:4x）
- Gemini gemini-3-flash-preview（PLAN＋dashboard.html／server.py diff -U60＋tests）：**APPROVED**（2 低：init 背景載排行保留、_scan_data_date 效率不需改）。reviews_b82/insp1_gemini.json
- Groq gpt-oss-120b（server.py diff）：**APPROVED**。reviews_b82/insp1_groq.json
- 自己檢查加修：掃描「籌碼型整理中」時切回頁面不重接進度追蹤（_ghFollowTimer）

## 程式檢查第 2 批（研究程式 research/b82）
- Gemini（完整 common／sim_entry／run_opt／merge／fetch_all＋測試＋舊引擎）：**APPROVED**（2 低：盤中進場日保守、_pick 用 9 不需改）。reviews_b82/insp2_gemini.json
- Groq sim_entry（去註解）：REVISE 3 點**全部不成立**——收盤價不適用融資延後（MARGIN_LAG 只管融資）、E1 t 來自 sig[:-1] 所以 t+1 在範圍內／E4 先過濾 e<T、回檔掛單價 ≤ 收盤×0.99 在一價漲停日不可能成交
- Groq common（第 1 次 json_validate_failed，重試）：REVISE 5 點，採納 1（shift_rows 一律轉浮點數）；「for … if … else [] 語法錯」實測可執行（pytest＋試跑），缺量＝不符合是設計、營收年增下限 −100% 不會被 −1e9 遮蔽、15／20 日不會超過月底 → 駁回
- 試跑（10 個月真資料，IS 2021-10～2022-03、OOS 2022-04～08、bootstrap 200）：整條流程 51 秒、E0＝trades825 斷言通過、法人／融資 0 天缺漏

## 部署 1（A＋B）＋正式站驗證
- 2026-10-24 00:41 推 22a2716（pytest 499＋1 失敗：研究資料夾 b81／b82 都有 common.py，一起跑會互相蓋掉，不影響網站）→ 00:42 afa5b31 改名 b82common.py 後 500 passed 再推；GH Actions 部署成功
- tests_ui/b82_ui.py 對正式站 **27/27 全過**（舊 localStorage 換成伺服器結果、切回頁面自動更新、休市／還沒完成文字、手機 2 欄、0 JS 錯誤）
- ⚠ afa5b31 誤把 research/b82/fetch.log 提交（公開資料下載進度，無害）→ 下一個提交移除＋gitignore

## §8 全分頁版面（用戶 00:4x 追加）計畫審查
- 健檢：scratchpad audit.py（正式站 14 分頁 × 1440／390 截圖＋量測）：0 個整頁橫捲；小字 10.2～10.9px、手機小按鈕、說明預設展開、寬表格
- Gemini：**APPROVED**（低：隱藏欄用 display:none、電腦版不受 media query 影響、收合狀態避免閃爍）
- Groq：REVISE 3 點 → F1（CSS 卡片會壞即時更新）駁回：grep 確認沒有程式用欄位位置（.cells[]、nth-child）更新，全部用 id；F2（44px）部分採納：篩選鈕 36px、表格內小鈕 32px（44px 會讓卡片太高）；F3（分頁列放不下）已涵蓋：nav 本來就 overflow-x:auto，測試量高度

## 程式檢查第 3 批（§8 全分頁版面）
- Gemini gemini-3-flash-preview（PLAN＋diff -U25）：**APPROVED**（2 低：共用函式位置、nth-child 維護風險 → 有 UI 測試守著，不改）。reviews_b82/insp3_gemini.json
- Groq：純樣式／前端，依記憶規則（前端交給 Gemini）不送
- 驗證：pytest 500；tests_ui/b82_all_ui.py（14 分頁 × 1440／390）本機 ALL PASS；tests_ui/b82_ui.py ALL PASS

## §8 第 2 輪（彈窗＋表格卡片）
- 健檢彈窗（scratchpad modal.py）：K 線、🔬 深度分析、詳細資料在手機／電腦都沒有超出畫面；深度分析標題列按鈕太小（✕ 16×26）、K 線圖例箭頭 9.4px → 修
- 研究候選說明改預設收起（手機原本佔滿整屏才看到股票）、批量回測按鈕縮小
- 策略篩選結果表、尾盤追蹤兩張表手機改卡片（_mcLabel 把表頭放到每格 data-l 當小標）
- Gemini：**APPROVED**（reviews_b82/insp4_gemini.json）；tests_ui/b82_all_ui.py 本機 ALL PASS
- §8 第 3 輪：可轉債／收購併購／庫藏股表格手機卡片（mc-gen 通用樣式）；Gemini **APPROVED**（reviews_b82/insp5_gemini.json）；b82_all_ui 本機 ALL PASS
- §8 第 4 輪：電腦版觀察清單（代號＋名稱固定在左、表頭可換行、🔬 只留圖示、來源限寬、<1700 藏最新日期、≤1499 加入日期併到加入後漲跌下面）；表格寬 2094→約 1480px（1440 螢幕只差一點、左兩欄固定）；Gemini **APPROVED**
- 研究下載：背景工作 2 小時上限被停（證交所到 2025-02），依系統規定不重開背景；改前景每段 9 分鐘續抓
