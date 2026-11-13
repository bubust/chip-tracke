"""暫時檢查（B108 上線後）：即時報價端點回得出價格嗎、快照裡有沒有結論卡"""
import json
import time
import httpx
B = "https://qiangni-tactics.fly.dev"
out = {}
for k in range(3):
    t = time.time()
    try:
        r = httpx.get(f"{B}/api/wave/quote", params={"sym": "TX"}, timeout=60)
        out[f"quote{k}"] = {"status": r.status_code, "sec": round(time.time() - t, 2), "body": r.json() if r.status_code == 200 else r.text[:200]}
    except Exception as e:  # noqa: BLE001
        out[f"quote{k}"] = {"error": repr(e)[:200]}
    time.sleep(12)
try:
    r = httpx.get(f"{B}/api/wave/quote", params={"sym": "TWII"}, timeout=60)
    out["quote_twii"] = r.json() if r.status_code == 200 else {"status": r.status_code}
except Exception as e:  # noqa: BLE001
    out["quote_twii"] = {"error": repr(e)[:200]}
j = httpx.get(f"{B}/api/wave/snapshot", params={"sym": "TX", "force": 1}, timeout=300).json()
t = ((j.get("nest") or {}).get("60m") or {}).get("tiers") or {}
out["snap"] = {"generated": j.get("generated"), "price": j.get("price"), "asof": j.get("asof"), "ladder_text": j.get("ladder_text"),
               "tag": t.get("tag"), "card": t.get("card"), "advice": (j.get("advice") or {}).get("headline")}
html = httpx.get(f"{B}/regime/", timeout=60).text
out["wave_js_v"] = html[html.find("wave.js?v="):html.find("wave.js?v=") + 30]
with open("scratch_probe/check.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:1500])
