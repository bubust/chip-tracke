"""暫時檢查：B115 部署後，正式站快照的 margin.credit"""
import json, time
import httpx
B = "https://qiangni-tactics.fly.dev"
for k in range(40):
    try:
        if "creditBox" in httpx.get(B + "/regime/static/wave.js", timeout=30).text:
            break
    except Exception:  # noqa: BLE001
        pass
    time.sleep(20)
out = {}
for force in (1, 0):
    try:
        j = httpx.get(B + "/api/wave/snapshot", params={"sym": "TWII", "force": force}, timeout=300).json()
        cr = (j.get("margin") or {}).get("credit") or {}
        out = {"generated": j.get("generated"), "credit": {k: v for k, v in cr.items() if k != "series"}, "n": len(cr.get("series") or []),
               "first": (cr.get("series") or [None])[0]}
        break
    except Exception as e:  # noqa: BLE001
        out = {"err": repr(e)}
json.dump(out, open("scratch_probe/b115c.json", "w"), ensure_ascii=False, indent=1)
print(out)
