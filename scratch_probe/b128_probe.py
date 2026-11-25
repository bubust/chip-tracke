"""B128 暫時檢查：借券資料來源長什麼樣（用完刪）"""
import json, time, httpx
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
C = [
 ("twse_mt_TWT93U", "GET", "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U", {"response": "json", "date": "20261124"}),
 ("twse_mt_TWT93U_d2", "GET", "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U", {"response": "json", "date": "20261121"}),
 ("twse_open_SBL_TWT93U", "GET", "https://openapi.twse.com.tw/v1/SBL/TWT93U", {}),
 ("twse_mt_TWT72U", "GET", "https://www.twse.com.tw/rwd/zh/marginTrading/TWT72U", {"response": "json", "date": "20261124"}),
 ("tpex_new_full", "POST", "https://www.tpex.org.tw/www/zh-tw/margin/sbl", {"date": "2026/11/21", "response": "json"}),
]
def trim(x, d=0):
    if isinstance(x, list):
        return [trim(v, d+1) for v in x[:4]] if d else [trim(v, d+1) for v in x[:4]] + ([f"...共 {len(x)} 筆"] if len(x) > 4 else [])
    if isinstance(x, dict):
        return {k: trim(v, d+1) for k, v in list(x.items())[:30]}
    return x
out = {}
RAW = {}
with httpx.Client(headers=UA, timeout=30, follow_redirects=True) as c:
    for name, m, u, p in C:
        try:
            r = c.get(u, params=p) if m == "GET" else c.post(u, data=p)
            try:
                j = r.json(); body = trim(j); RAW[name] = j
            except Exception:
                body = r.text[:800]
            out[name] = {"status": r.status_code, "url": str(r.url), "body": body}
        except Exception as e:
            out[name] = {"err": repr(e)[:300]}
        time.sleep(3)
try:
    sw = httpx.get("https://openapi.twse.com.tw/v1/swagger.json", headers=UA, timeout=30).json()
    out["swagger"] = {k: (v.get("get") or {}).get("summary") for k, v in sw.get("paths", {}).items() if any(t in k + json.dumps(v, ensure_ascii=False) for t in ("SBL", "借券", "TWT93", "融券"))}
except Exception as e:
    out["swagger"] = repr(e)[:200]
for k in ("twse_mt_TWT93U", "tpex_new_full"):
    b = RAW.get(k)
    if isinstance(b, dict):
        t = (b.get("tables") or [b])[0]
        out[k + "_fields"] = {"fields": t.get("fields"), "row0": (t.get("data") or [None])[0] if isinstance(t.get("data"), list) else None}
json.dump(out, open("scratch_probe/b128_probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
