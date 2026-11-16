"""暫時檢查：證交所台股儀表板（信用交易）頁面 → 找資料 API"""
import json, re
import httpx
UA = {"User-Agent": "Mozilla/5.0"}
B = "https://www.twse.com.tw"
out = {}
for u in ("/dashboard/zh/credit/margin.html", "/dashboard/zh/index.html"):
    try:
        r = httpx.get(B + u, headers=UA, timeout=40, follow_redirects=True)
        out[u] = {"status": r.status_code, "len": len(r.text), "scripts": re.findall(r'src="([^"]+\.js[^"]*)"', r.text), "head": r.text[:3000]}
    except Exception as e:  # noqa: BLE001
        out[u] = repr(e)
js = {}
for u in (out.get("/dashboard/zh/credit/margin.html") or {}).get("scripts", [])[:12]:
    full = u if u.startswith("http") else (B + u if u.startswith("/") else B + "/dashboard/zh/credit/" + u)
    try:
        t = httpx.get(full, headers=UA, timeout=40).text
        js[full] = {"len": len(t), "urls": sorted(set(re.findall(r'["\'`](/[A-Za-z0-9_/\-\.]*(?:rwd|api|dashboard|exchangeReport|json)[A-Za-z0-9_/\-\.?=&]*)["\'`]', t)))[:80],
                    "hits": [t[max(0, m.start() - 200):m.start() + 300] for m in re.finditer(r'維持率|maintenance|margin', t)][:6]}
    except Exception as e:  # noqa: BLE001
        js[full] = repr(e)
out["js"] = js
json.dump(out, open("scratch_probe/b115.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:4000])
