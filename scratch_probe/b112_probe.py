"""暫時檢查：等 B112 部署完，看正式站台指期的日盤／夜盤漲跌有沒有分開"""
import json
import time
import httpx

B = "https://qiangni-tactics.fly.dev"
ok = False
for k in range(40):
    try:
        if "B112" in httpx.get(B + "/regime/static/wave.js", timeout=30).text:
            ok = True
            break
    except Exception as e:  # noqa: BLE001
        print("等部署", k, e)
    time.sleep(20)
print("新版上線", ok, k)
j = None
for force in (1, 1, 0):
    try:
        j = httpx.get(B + "/api/wave/snapshot", params={"sym": "TX", "force": force}, timeout=300).json()
        break
    except Exception as e:  # noqa: BLE001
        print("失敗", force, e)
        time.sleep(20)
out = {k: j.get(k) for k in ("generated", "price", "prev_close", "chg", "chg_pct", "sess", "asof")}
t = ((j.get("nest") or {}).get("60m") or {}).get("tiers") or {}
c = t.get("card") or {}
out["tiers"] = {"tag": t.get("tag"), "status": t.get("status"), "pos": c.get("pos"), "shape": c.get("shape"), "tiles": c.get("tiles"),
                "plays": c.get("plays"), "steps_now": (c.get("steps") or {}).get("now"), "flip": c.get("flip")}
out["bars_last"] = (j.get("chart") or {}).get("bars", [])[-3:]
try:
    out["quote"] = httpx.get(B + "/api/wave/quote", params={"sym": "TX"}, timeout=30).json()
except Exception as e:  # noqa: BLE001
    out["quote"] = str(e)
with open("scratch_probe/b112.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:1500])
