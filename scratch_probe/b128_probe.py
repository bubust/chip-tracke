"""暫時檢查：B128 上線後的借券資料（用完刪）"""
import json, time
import httpx
U = "https://qiangni-tactics.fly.dev/api/wave/snapshot"
out = {}
for k, wait in (("first", 0), ("after5m", 300)):
    time.sleep(wait)
    j = httpx.get(U, timeout=240).json()
    sb = j.get("sbl") or {}
    out[k] = {"generated": j.get("generated"), "asof": j.get("asof"), "sbl": {**sb, "series": (sb.get("series") or [])[-8:],
              "n_series": len(sb.get("series") or [])}}
json.dump(out, open("scratch_probe/b128_live.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
