"""暫時檢查 2：證交所 BFIJ3U（全市場擔保維持率、追繳處分）的格式、能查哪幾天"""
import json, time
import httpx
UA = {"User-Agent": "Mozilla/5.0"}
B = "https://www.twse.com.tw/rwd/zh/marginTrading/"
out = {}
for name, params in (("BFIJ3U", {}), ("BFIJ3U_d1113", {"date": "20261113"}), ("BFIJ3U_d1105", {"date": "20261105"}), ("BFIJ3U_d0701", {"date": "20260701"}),
                     ("BFIJ3U_TREND", {}), ("BFIJ3U_TREND_d60", {"days": 60}), ("MI_MARGN_TREND", {})):
    ep = name.split("_d")[0] if name.startswith("BFIJ3U_d") else name.replace("_d60", "")
    try:
        r = httpx.get(B + ep, params={"response": "json", **params}, headers=UA, timeout=40)
        out[name] = {"status": r.status_code, "body": r.text[:4000]}
    except Exception as e:  # noqa: BLE001
        out[name] = repr(e)
    time.sleep(3)
json.dump(out, open("scratch_probe/b115b.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:3000])
