# PLAN-B80 審查紀錄（/claudex-loop）
- 角色：主持／計畫＝Claude Code（Opus 5.5）；計畫審查＝Gemini＋Groq（用戶設定：不用 Codex／GPT，claude-files/claudex-review2.py）；
  實作＝Claude；最後程式檢查＝Gemini＋Groq 全新一輪（不帶計畫審查的對話）
- 範圍：大盤解析改版（結論卡＋頁內分頁）、15 分 K、成交量（資料＋副圖＋判讀＋回測）、她的 4 項邏輯；用戶授權實作（「重新討論更新一下版面…一併做改進」），部署照以往批次（推 main → GitHub Actions）
- 上限：計畫審查 5 輪、修正 2 輪、程式檢查 2 輪
- 工作資料夾：claude-files/chip-tracker-b80（worktree，分支 b80，從 origin/main b9d1a6c）；本機資料庫是主資料夾 chip_data 的複本

## 第 1 輪（計畫）
Round 1 dispositions (coordinator):
Gemini F1 (opening auction dropped) ACCEPTED as clarification: day baseline cumulative = 0; the 09:00:00 row is 0 in real data and the opening auction appears at 09:00:05, so the first bar keeps it. Added to §5.1.
Gemini F2 (multi-instance locks) PARTIAL: production runs exactly one Fly machine (--ha=false, volume attaches to one machine), so cross-container concurrency cannot happen; wave.db already uses WAL + timeout 30. Added single worker thread + module lock + running flag; users never trigger backfill.
Gemini F3 (hidden tab chart width) ACCEPTED: explicit applyOptions({width}) + redraw on switching to the chart tab; UI test added.
Gemini F4 (rvol fallback) PARTIAL: daily/weekly use >=5 prior bars; intraday does NOT fall back to a plain average (U-shaped intraday volume would make opening bars always look like a surge); shows "same-slot data insufficient (backfilling)".
Groq-A F1/F2 (conversion, auction, timezone) ACCEPTED as clarification in §5.1 (epoch + FD.session_of Asia/Taipei; Taiwan closes 13:30, there is no 14:30 auction; 13:30 closing call merged into the last bar).
Groq-A F3 (look-ahead) ACCEPTED as clarification in §7 (bar-close evaluation, pivots confirmed <= t via engine.state_at, rvol prior-only, outcomes from t+1).
Groq-A F4 (multiple testing) PARTIAL: thresholds are fixed a priori (no tuning, so no in-sample selection), BH across all V tests + sub-period sign consistency; ladder/decision tree/version tree are display rules, labeled △, not claimed predictive.
Groq-A F5 (DOM ids) ACCEPTED: audited, no other page references these ids; all ids used by the macro script are kept.
Groq-A F6 (edge cases) ACCEPTED: zero/missing volume = no data (not "shrinking"), volume card says no data, old snapshot UI test added.
Groq-A F7 (mobile clutter) ACCEPTED: conclusion card max 6 lines; 360 px test added.
Groq-A F8 (memory) REJECTED: 15-min bars come from the same 40-day bars5 already loaded for 30/60-min (TX ~3,000 rows); negligible.
Groq-A F9 (tests) REJECTED: §10 already lists unit + UI tests (playwright is the project's tool, not Cypress).
Groq-B F1 (rvol uses today's partial) ACCEPTED as clarification: only prior completed trading days, excluding today and the bar itself.
Groq-B F2 (rate limit) ACCEPTED: single worker, 3.2 s gap, one retry after 30 s then stop until next schedule; no per-user triggers.
Groq-B F3 (clutter) REJECTED: volume card, ladder, decision tree are in separate tabs already (chart vs scenario tab); conclusion card stays short.
Groq-B F4 (holidays) ACCEPTED: backfill only days that have TWII bars in bars5; stat != OK skipped.
Groq-B F5 (rounding) ACCEPTED: raw units for all computation; rounding only in the display field.

結果：Gemini gemini-3.6-flash REVISE（4 點）、Groq gpt-oss-120b 前半 REVISE（9 點）、後半 REVISE（5 點）；原始回覆 reviews_b80/plan_r1_*.json

## 第 2 輪（計畫）
Round 2 dispositions (coordinator):
Gemini F1 (partial-bar rvol floor 0.2 deflates early estimates) ACCEPTED (modified): the in-progress bar is NOT judged until 20% of its time has elapsed (shows "just started"); after that the actual elapsed fraction is used with no floor. Rationale for not extrapolating from 5%: intra-bar volume is front-loaded at the open, so very early extrapolation is noisy.
Gemini F2 (volume profile single-bin spikes) ACCEPTED: each bar's volume is spread evenly over all 0.25-ATR bins between its low and high.
Groq part A S1 (TF_KEYS uniqueness) ACCEPTED: unit test asserts the 5 TF keys and their waves/levels keys are unique.
Groq part B F1 (empty volume card) ACCEPTED: placeholder text "這段沒有量的資料" (already in §5.3), card keeps its layout.

結果：Gemini REVISE（1 中 1 低）、Groq 前半 APPROVED、後半 APPROVED（各 1 個低優先建議）；原始回覆 reviews_b80/plan_r2_*.json

## 第 3 輪（計畫）
Round 3 dispositions (coordinator):
Gemini F1 (last 60-min TWII bar 13:00-13:30 is only 30 min) ACCEPTED: elapsed fraction denominator = actual bar length = min(start + tf, session close) - start (same for 30/15-min last bars); the same-slot reference average already refers to that short bar, so no other adjustment.
Gemini F2 (High == Low bars in the volume profile) ACCEPTED: such bars go entirely into the single bin containing the price; the bin index math never divides by (high - low). Unit test added.
Groq S1 (backlog > 5 days) ACCEPTED: later runs keep catching up; log how many days remain. (Startup also checks the full 45-day window.)
Groq S2 (invalid stored wv_tab) ACCEPTED: invalid value -> chart tab.
Groq S3 (verify volume pane) ACCEPTED (modified): instead of measuring canvas pixels, wave.js exposes a read-only window.__wvState with candle and volume bar counts; the UI test asserts volume bars == candles that have volume.

結果：Gemini REVISE（1 中 1 低）、Groq 後半 APPROVED（3 個低優先建議）；前半文字自第 2 輪 Groq 核准後沒有改；原始回覆 reviews_b80/plan_r3_*.json

## 第 4 輪（計畫）
結果：**Gemini gemini-3.6-flash APPROVED**（最終版 PLAN-B80.md sha256 86d2b45cfcbbc5d0…）；低優先 2 點實作時處理：F1 分格寬度設下限（ATR 0 不出錯）、F2 強勢突破直接到 T1 沒回測時「回測不破」那步自動算過。
Groq gpt-oss-120b：前半第 2 輪核准（之後沒改）、後半第 3 輪核准；第 4 輪的修改是採納它自己的 3 個低優先建議＋Gemini 2 點，沒有再送 Groq（照實記：最終版只有 Gemini 完整核准）。
計畫審查用了 4 輪（上限 5）。

## 實作
- 實作偏離計畫（照實記）：
  1. 證交所量的抓取放在新模組 wave/voldata.py（計畫寫 futdata／data；表一樣建在 data.SCHEMA）
  2. 每日成交金額（FMTQIK，含零股等）比盤中統計（MI_5MINS）多約 5%（10/21：8,747 vs 8,332 億）→ 盤中今天的日量用「近 20 天 FMTQIK÷MI5 中位數」換算到同一基準
  3. 日 K 盤中「預估全天量」只做加權（台指期日 K＝夜盤＋日盤，盤中只顯示鉅亨累計，不預估）
  4. 回測加「隨機漫步對照」：每筆事件依離兩邊的距離算隨機走勢的理論機率，比「實際−理論」（比計畫嚴格；試跑時「站不住→回吐 50%」76% vs 36% 看起來很準，扣掉距離後跟隨機一樣）
  5. 快照端點 /api/wave/snapshot 加 gzip（只壓這個端點；快照 198KB→約 300KB，壓縮後約 55KB）
  6. 本機測試伺服器用 uvicorn --lifespan off（不跑排程與回補，避免跟研究抓資料同時打證交所）

## 程式檢查第 1 輪（全新一輪；建置前 commit b9d1a6c、建置者 Claude；wip 58b2043）
- Gemini gemini-3.6-flash 兩批都 503 → 改 gemini-3.7-flash：
  - 後端（voldata、volume、levelmap、service、intraday、router、nest、panel 完整檔＋engine／data／advice diff）：REVISE
    F1 中：下方只有一個價位而且就是轉折點時，結論卡停損那格變空白 → **接受，已修**（後面沒有價位就照舊顯示轉折點）＋測試
    F2 低：同一版本兩條換數法併在一列時版本名重複 → **接受，已修**＋測試
    F3 低：FMTQIK 年份萬一改成西元 → **接受，已修**＋測試
  - 前端（wave.js、index.html 完整檔）：**APPROVED**
- Groq gpt-oss-120b（ast.unparse 去註解版，一檔一批、隔 65 秒）：
  - volume.py REVISE：F1 f-string 引號語法錯誤 → **駁回**（ast.unparse 假象；原始檔 3.12+ 合法，458 個測試都載入）；F2 describe 用 e['t'] 會 KeyError → **駁回**（快照裡的 breaks 由 service._vol_block 加了 t，實際呼叫都帶）
  - levelmap.py REVISE：F1～F6 引號 → **駁回**（同上）；F7 it['tlabel'] 可能不存在 → **駁回**（只有有 t 的才讀，tlabel 跟 t 一起設定）；F8 自己說不用改
  - voldata.py：json_validate_failed（空輸出）→ 重送
  - voldata.py 重送一次還是 json_validate_failed（中文多的檔 Groq 常這樣）→ **Groq 沒有完成 voldata**，這個檔由 Gemini 後端批次完整檢查
- 第 1 輪後追加修改（建置者 Claude，要第 2 輪檢查）：盤中 MI_5MINS 逾時 8 秒（在快照鎖裡）；週 K 突破回看改 30 根日 K；切商品後資料還沒回來不畫（原本會拿上一個商品的資料標成新的，tests_ui 抓到）；
  週 K 量改用週別對應（原本最後一根對不上變空白）；成交密集區每區最寬 1.5 ATR、不重疊（原本日 K 一區 2,500 點、兩區重疊）；V5 照新定義重跑；研究說明加量能結論；沒有回測支持的說法拿掉

## 最終回測（research/b80/REPORT.md；加權日 K 2000-01～2026-10、60 分 K 2023-10～2026-10，量全部是證交所資料）
- V1～V5、V2b 在 D1、D2 **全部 △**（扣掉隨機漫步後沒有一條差距 ≥8 個百分點且 BH <0.05）；
  例：帶量突破 74% vs 63%（隨機 64% vs 51%）、站不住→回吐 76% vs 36%（隨機 81% vs 46%）、成交密集區 45% vs 47%（隨機 54% vs 49%）
- 台指期 60 分 K 只有 45 天（D3）只報告，樣本 4～30 筆
- 15 分 K 級數 m＝2（前 40 天平均每段 0.47 天、後 20 天 0.50 天）

## 程式檢查第 2 輪（全新一輪，gemini-3.7-flash／3.6-flash；3.7、3-flash-preview 第一次都 503）
- 回測＋測試批（run_vol、merge、r15、fetch、REPORT、test_b80、b80_ui、volume）：REVISE（低／中）——確認沒有偷看、隨機漫步公式、年內置換、BH、報告結論都正確
  F1 中 describe() 用 e['t']，原始 breakouts() 沒有 t → **接受（防呆，已修）**；實際呼叫都是快照裡有 t 的
  F2 低 `fetch.py mi5` 時 r60 沒初始化 → **駁回**（只要有 mi5 就會先抓 60 分 K，第 104 行）
  F3 低 ev_v4 在 vr 是 None 時就把這段標記用過 → **駁回**（事先定義是「修正段第一次空間 ≥0.236 的那根」，改成找之後有量的那根等於依資料可得性挑時點）
  F4 低 describe 的突破分支沒測 → **接受，已加測試**
- 後端批（第 1 輪後全部修改的 diff＋volume、levelmap、voldata、service 完整檔）：**APPROVED**
- 程式檢查用了 2 輪（上限 2）；Groq 這輪沒送（第 1 輪三批的意見都是 ast.unparse 假象或不成立，額度留給正式站）
