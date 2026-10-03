"""臨時診斷：用實際的 mna.fetcher 抓近 8 個交易日，印出結果（GitHub Actions 上跑）"""
import json, sys
sys.path.insert(0, ".")
from mna.fetcher import fetch_range
res = fetch_range(days=8, progress=lambda d, t: print(f"進度 {d}/{t}", flush=True))
print("errors:", res["errors"])
print("找到", len(res["records"]), "筆")
for r in res["records"]:
    print(json.dumps({k: (v[:200] if isinstance(v, str) else v) for k, v in r.items()}, ensure_ascii=False))
