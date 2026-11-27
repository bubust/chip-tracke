"""B131 研究資料（GitHub Actions 抓；雲端 session 連不到 FinMind、期交所）→ research/b131/data/
- tx_d.csv：台指期日 K 2017 起（FinMind TaiwanFuturesDaily TX，日盤＋夜盤；跟網站同一套 select_continuous → full_bars）
- tx_5m.csv：期交所最近 30 個交易日逐筆檔 → 5 分 K（網站同一支 wave.futdata.fetch_taifex_day；含前一晚夜盤）"""
import os
import sys
import time
from datetime import date

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "b94"))
from wave import futdata as FD  # noqa: E402
import fetch as B94  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    tx = B94.finmind_tx()
    tx.to_csv(os.path.join(OUT, "tx_d.csv"), index=False)
    print("tx_d", len(tx), tx.date.iloc[0], tx.date.iloc[-1])
    days = list(tx.date.astype(str))[-30:]
    rows = []
    for d in days:
        try:
            t0 = time.time()
            r = FD.fetch_taifex_day(date.fromisoformat(d))
            rows += r
            print(d, len(r), f"{time.time() - t0:.1f}s")
        except Exception as e:      # noqa: BLE001
            print(d, "失敗", e)
        time.sleep(2)
    pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"]).drop_duplicates("ts").sort_values("ts").to_csv(
        os.path.join(OUT, "tx_5m.csv"), index=False)
    print("tx_5m", len(rows))
