"""B80 暫時檢查：線上 bars5 最後一根、快照時間"""
import json

import httpx

j = httpx.get("https://qiangni-tactics.fly.dev/api/wave/status", timeout=60).json()
print(json.dumps({k: v for k, v in j.items() if k != "sources"}, ensure_ascii=False)[:4000])
s = httpx.get("https://qiangni-tactics.fly.dev/api/wave/snapshot", params={"sym": "TX"}, timeout=120).json()
print(s.get("generated"), s.get("price"), s.get("asof"), (s.get("chart") or {}).get("i15", [{}])[-1])
