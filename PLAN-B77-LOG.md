# PLAN-B77-LOG（/claudex-loop）

- 角色：Claude Code 主持＋實作；計畫審查與程式檢查＝Gemini＋Groq（依記憶：不用 Codex/GPT）
- 範圍：全系統總檢查（用戶 20:10 截圖＋20:45「全面檢查優化，今天的 TOKEN 都要拿來做優化」＋20:55「月斜率拿掉，K 線副圖上面三項就好」）
- 授權：用戶要求直接做優化（沿用 chip-tracker 慣例：做完 push main → GH Actions 部署）
- 工作區：worktree claude-files/chip-b77（分支 b77，起點 origin/main 76ae1f0）；本機測試資料＝複製 chip_data/*.db

## 計畫審查
| 輪 | 審查者 | 結果 | 檔案 |
|---|---|---|---|
| 1 | Gemini 3.6-flash | 作業失敗（503），不算 | reviews_b77/plan_r1.json |
| 1 | Groq gpt-oss-120b（精簡版） | REVISE 8 點 | reviews_b77/plan_r1.json |
| 2 | Gemini 3.6-flash | 作業失敗（429 當天額度） | reviews_b77/plan_r2.json |
| 2 | Groq（精簡版，含 E 段） | **APPROVED**（3 個 low） | reviews_b77/plan_r2.json |
| 2 | Gemini 3.7-flash（完整計畫＋6 個現行檔案） | REVISE 4 點 | reviews_b77/plan_r2_gemini.json |
| 3 | Gemini 3.7-flash | **APPROVED**（2 個 low：第 2 趟前 seek(0)、catchup.json 壞檔容錯＋原子寫入 → 都採納） | reviews_b77/plan_r3_gemini.json |

- Groq 核准的是第 2 版；第 3 版只加了 Gemini F1／F2／F4（啟動補跑合併成一個執行緒、heavy() 不准在 event loop 上等、暫存檔開機清除）與 F3 實測駁回，沒有再送 Groq（照實記錄）
- 處置全文：reviews_b77/disp_r1.md、disp_r2.md
- Gemini F3（LWC 邊界是比例）實測駁回：正式站頁面原本回 `{"above":39,"below":39}`，設 18 → 價格範圍 418～−23，設 0.08 → 360～26（等於沒邊界）→ 單位是像素

## 實作（Claude；worktree chip-b77）
- 新模組：jobs.py（重工作排隊＋工作紀錄＋開機紀錄）、swr.py（過期先回舊資料）、health.py（🩺 系統健康）
- 計畫外的小加碼（同一目標，照實記）：fly.toml `MALLOC_ARENA_MAX=2`（多執行緒 glibc 記憶體區）；收購併購清單 60 秒快取＋資料庫沒變不重算（本機每次 0.6 秒）；
  觀察清單 Yahoo 備援（ETF 等）過期先用舊的背景重抓（正式站實測一次 3.4 秒）
- 跟計畫不一樣的地方：D1 籌碼策略錯誤放在 `chip_course.last_errors`（模組變數），不放進 run_all 回傳（放進去會被當成多一個策略）；
  指數列 C1 的 TTL 夜盤時段 15:00～隔天 05:00 照計畫；E5 預熱的指數用自己的 event loop 直接寫快取（不碰 asyncio.Lock，避免綁到別的 loop）

## 驗證（本機）
| 項目 | 之前 | 之後 |
|---|---|---|
| import server 常駐 | 174～178MB | 121～122MB（拿掉 scipy） |
| 權證合約更新尖峰（真的下載 45＋17MB） | +206MB | +48MB；寫入結果與舊版逐欄相同（64,000 筆、907 標的） |
| 產業同步尖峰 | +173MB | +14MB（增量，一天一天讀寫） |
| 產業引擎計算尖峰 | +99MB | +28MB；sector_daily 602 列、sector_events 51 筆跟舊版相同 |
| IV／常態分配 vs scipy | — | 5 萬組 0 不一致、最大差 0 |
| 首頁請求數 | 約 150 | 28 |
| 停 60 秒的背景請求 | indices 6、price-cache 8、總經 21、產業 2 | indices 3（交易時段 10 秒；分頁在背景不打）、其他 0 |
| 處置股冷快取 | 13.9 秒（正式站） | 本機首次 3.1 秒、之後 0 秒、過期 0 秒先回舊的 |
- 本機完整全系統更新 12 步全部成功（watchlist 0.9s、regime 86.8s、wave 22.8s、tdcc 1.6s、positioning 53.7s、sector 13.0s、warrant 37.7s、relationship 1.6s、link 5.8s、treasury 22.3s、mna 141.3s、cb 762.1s〔本機資料舊兩週在回補〕）
- pytest 404 passed（365＋新 39）；tests_ui/b77_ui.py 全過；tests_ui/b76_ui.py 全過（回歸）

## 程式檢查（不是同一個寫程式的模型檢查）
| 批 | 審查者 | 範圍 | 結果 |
|---|---|---|---|
| A | Gemini 3.7-flash | server.py＋jobs／swr／health（完整檔） | **APPROVED**；low F1 市場關聯排程加 skip_if_recent → 採納；low F2 改用帶時區的 now → 駁回（Dockerfile `TZ=Asia/Taipei`，全系統用本地時間，掃描完成時間也是不帶時區） |
| B | Gemini 3.7-flash | 權證／產業／處置股／連動／可轉債／併購／籌碼／總經 router／yahoo_price（完整檔） | REVISE：F1 S_BIGHOLD 某週集保不完整 → min() 碰到 None TypeError（**實測成立**：holder_ratios 回 (None, None)；可能就是正式站籌碼策略 0 檔的原因之一）→ 修＋測試；F2 權證紀錄檔是 null 會讓啟動失敗 → 修；F3 暫存檔中途出錯沒登記 → 修；F4 處置股欄位不夠的列 → 修 |
| B2 | Gemini 3.7-flash（新的一輪） | 修過的 4 檔＋jobs | **APPROVED**；low F1 處置股日期格式 → 駁回（price_daily 本來就是 YYYYMMDD，跟傳入一致）；low F2 _errors 放回傳 → 駁回（刻意，見上）；low F3 連線 try/finally → 採納 |
| C | Gemini 3.7-flash | 前端 diff（dashboard 540KB 只能送 diff，前後 25 行） | **APPROVED** |
| G | Groq gpt-oss-120b | jobs.py | REVISE：recent() 整檔讀 → 部分採納（deque 只留 n 行；開機本來就裁到 300 行，「OOM」說法誇大） |
| G | Groq | swr.py、health.py | **APPROVED** |
| G | Groq | warrant/calculator.py | REVISE 3 點 → 全駁回：bs_greeks 只在隱波算得出來時呼叫（S、K 必 > 0），delta 是 None 會先 return；Brent 初值跟 scipy brentq.c 一樣（5 萬組 0 差異） |
| final | Gemini 3.7-flash（新的一輪） | 檢查後的最後小改（jobs.recent、chip_course finally、relationship skip） | **APPROVED** |

## 部署後驗證（正式站 v290，2026-10-21 21:54 起）
- 1 台機器、swap 512MB 生效（/proc/meminfo SwapTotal 512）、開機 RSS 153MB（原 234MB）
- 重開補跑照設計：21:57:31 補今天 18:00 掃描（catchup.json 第 1 次）→ 22:12 掃描完成（1,946 檔、命中 566、失敗 2）→ 全系統更新**從權證合約接著跑**（前 6 步不重跑）→ 22:20 12 步全部完成
  權證 79.6s、市場關聯 1.7s、連動 24.1s、庫藏股 20.8s、併購 131.8s、可轉債 22.6s；整段 1,374 秒、記憶體尖峰 226MB（機器 459MB）、swap 用 1MB、0 次 OOM
- 籌碼型策略恢復：投信連買 1、融券大增 11、融券退潮 18、大戶增散戶減 326、投信倒貨 8（10-20 那次全 0；當時真正原因 log 已輪替看不到，S_BIGHOLD 的 None 例外已修）
- 🩺 系統健康：✅ 全部正常
- 慢端點：處置股重開後第一次 8.3s（第一次建存檔）→ 0.16～0.22s；可轉債 2.3s → 0.26s；連動 0.2s；/healthz 0.14s
- 追加修正 B77b：補跑掃描那 15 分鐘按鈕顯示「⏳ 0 秒後接著跑」→ 新欄位 catchup＝scan_1800，顯示「先補今天的掃描」；Gemini 3.7-flash 檢查 APPROVED
