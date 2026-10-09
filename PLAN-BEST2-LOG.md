# PLAN-BEST2-LOG（/claudex-loop 方式，2026-10-09）
- 主持／計畫／實作：Claude Code（Opus 5.5）；計畫審查與最終程式檢查：Gemini＋Groq（用戶設定，不用 Codex）
- 用戶：「你們討論一下」（固定 % 停損、沒跌破放著）＋改良現有策略＋大跌買大盤／權值股＋放寬標準；之前已授權中間不用問、做到上線
- 計畫：PLAN-BEST2.md；審查上限 5 輪；最終檢查 2 輪

## 第 1 輪（10-09）C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/best2/review/r1.json — Gemini 503 沒回；Groq REVISE（F1～F6）
Round 1 dispositions (Gemini returned 503 and is re-requested now; Groq REVISE):
- Groq F1 (crash triggers use full-sample 60-day high/MA): REJECTED as stated, clarified. All windows are rolling and end at day t (computed after t's close); entry is t+1 open. Plan text now states this explicitly.
- Groq F2 (relaxed tier defined after round 1): ACCEPTED in disclosure form. No unused data period exists (data ends 2026-10-08), so a third holdout is impossible; the relaxed tier is labeled "exploratory, not independent validation" everywhere (report + website); the strict tier remains the formal conclusion. Thresholds are frozen now, before any round-2 run.
- Groq F3 (unbounded hold): ACCEPTED. E7 capped at 250 trading days everywhere; report share capped and share still open at data end (marked to last close).
- Groq F4 (multiple testing per strategy): ACCEPTED. "Improved" additionally requires the month-block bootstrap 95% CI of (OOS mean improved - OOS mean baseline) to have a lower bound > 0 (fixed seed). Combo counts reported.
- Groq F5 (0050 corporate actions): ACCEPTED. Verify 0050 dividends and the 2025-06 1:4 split are in the return series; 5-year total return cross-checked against TAIEX + ~3%/yr dividends.
- Groq F6 (seeds): ACCEPTED. Fixed seeds for all sampling.

## 第 2 輪（10-09）C:/Users/牆泥袋溥/AppData/Local/Temp/claude/C--Users------Desktop/63f6090b-1913-4610-a964-29bd921ba75c/scratchpad/best2/review/r2.json — Gemini APPROVED（4 個 low 建議）；Groq APPROVED（F1～F4 low）
- Groq F1（停損價公式寫清楚）：ACCEPTED，停損價＝買進價 ×（1 − %），進場後不重算。
- Groq F2（用樣本內勝率挑會有贏家詛咒）：REJECTED（保留用戶要的「勝率高」當目標），已有樣本外＋「改良−原本」bootstrap 下限 > 0 兩道關卡控制。
- Groq F3（大跌門檻也是看過才定）：已標探索性；每個門檻都列結果（不只挑一個）＝敏感度分析。
- Groq F4（網站結果要對得上報告）：ACCEPTED，summary.json SHA256 寫進報告與 API。
- Gemini（停損出場 vs 沒停損的平均賺賠）：ACCEPTED，加進 E7 報告。其他 low（多頭偏誤、放寬層要醒目）已在計畫內。
- **計畫核准**：SHA256 b2b8845188f435d81484db98e757e3bf3aab090637d8d8a09e65a7b52e616043

## 實作與結果（10-09，Claude 實作）
- research/best2/：engine2.py（E0＝直接呼叫 backtest_engine.simulate；E6 固定 %；E7c／E7i 沒跌破一直抱，最多 250 天）、run2.py（strat／e7／grid）、crash.py、report2.py。驗證：E6／E7 手算 200 筆 0 錯；E0 抽一檔跟 backtest_engine 進出場日一致；0050 含息 5 年 3.96 倍（一拆四＋12 次配息都算到，跟台積電權重高相符）。
- 現有 18 策略（原本＝網站預設出場，樣本外勝率 27～40%）：照「樣本內勝率最高」挑的改良版多是小停利大停損 → 樣本外多數虧；**只有 KDJ 低檔金叉改良成功**（不加濾網、固定抱 40 天：樣本外 39%／+0.70% → 52%／+4.93%），但帳戶 5 年年化仍 −3.7%（網站寫明）。
- 固定 % 停損、沒跌破一直抱：勝率 15～50%、平均每筆 +6%～+29%，但隨機進場也有 +5～12%（大多頭）；停損 5% 有 6～8 成 60 天內被洗出場；收盤判斷比盤中觸價平均多約 1 個百分點；帳戶年化在不同停損間跳很大、回撤 −32%～−52%。
- 大跌買 0050／權值股：深跌（加權比 60 日高 −15%／低於季線 10%／負乖離 ≥ 100 檔）5 年 5 波；已滿期 4 波中 3 波抱 60～120 天賺（+10%～+66%），2022-06 那波 60 天 −6%；中度回檔（−8%～−10%）跟隨機差不多。事件少不做顯著性宣稱。
- 全部組合 35,358 個：**嚴格層仍沒有主推**（同兩個候選回撤 −36.0%／−33.4%）；**放寬層（探索性）主推 C1_S_BIAS+S_BREAKBOTTOM|none|E3_t1_s3_40d**（樣本外 88%／+6.27%，隨機 70%／+1.48%，bootstrap [+1.1%, +7.2%]，20 檔×5% 年化 +8.0%、回撤 −26.9%）。網站 S_BEST 仍用嚴格層最接近的（E3_t1_s2_20d），放寬結果寫在報告與說明。
- 網站：策略篩選每個策略「📊 5 年回測：原本 vs 改良」、最上面「📉 大跌買點」卡片（今天數值＋過去 5 波結果）＋深跌第一天 Telegram（14 天內只推一次）。
