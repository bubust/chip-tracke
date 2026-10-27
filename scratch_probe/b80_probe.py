"""B80 暫時檢查：鉅亨台指期 5 分 K 夜盤有沒有 21:00 以後的資料、線上 bars5 狀態"""
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from wave import futdata as FD  # noqa: E402

rows = FD.fetch_cnyes("TX", "5", days=3)
print("cnyes TX 5m", len(rows))
for r in rows[-40:]:
    print(FD.tw_dt(r[0]).strftime("%m/%d %H:%M"), r[1:5])
print(json.dumps(httpx.get("https://qiangni-tactics.fly.dev/api/wave/status", timeout=60).json(), ensure_ascii=False)[:3000])
