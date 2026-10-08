# PLAN-BEST 研究（找勝率最高、期望值為正的選股方式）

重跑步驟（資料不進 git，放 research/best/data/）：
1. `python fetch5y.py 2021-01-01 2026-10-08`：證交所 MI_INDEX＋櫃買 otc 官方日行情（每天一檔，可中斷續抓）
2. `python fetch_events.py`：官方除權息／減資／面額變更事件表（報酬調整用）
3. `python signals_a.py data sig_a.csv.gz`：系統現有 18 個做多策略逐日訊號（約 1 小時）— 注意 run.py 讀的是 data 上一層的 sig_a.csv.gz
4. `python run.py data all`：全部組合、選法、隨機基準、bootstrap、組合模擬 → results/
5. `python diag.py data "<組合>"`（沒有主推時的事後分析）、`python report.py` → results/REPORT.md、summary.json
6. `python verify_live.py data`：網站版 best_strategy.py 跟研究版逐日一致

結果與決策過程：results/REPORT.md、../../PLAN-BEST.md、../../PLAN-BEST-LOG.md。
