"""B128 暫時檢查：借券資料來源長什麼樣（用完刪）"""
import json, time, httpx
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
C = [
 ("twse_TWT93U", "GET", "https://www.twse.com.tw/rwd/zh/SBL/TWT93U", {"response": "json", "date": "20261124"}),
 ("twse_TWT93U_prev", "GET", "https://www.twse.com.tw/rwd/zh/SBL/TWT93U", {"response": "json", "date": "20261121"}),
 ("twse_TWT72U", "GET", "https://www.twse.com.tw/rwd/zh/SBL/TWT72U", {"response": "json", "date": "20261124"}),
 ("twse_TWT96U", "GET", "https://www.twse.com.tw/rwd/zh/SBL/TWT96U", {"response": "json"}),
 ("twse_open_TWT96U", "GET", "https://openapi.twse.com.tw/v1/SBL/TWT96U", {}),
 ("twse_open_TWT93U", "GET", "https://openapi.twse.com.tw/v1/exchangeReport/TWT93U", {}),
 ("twse_dash_sbl", "GET", "https://www.twse.com.tw/rwd/zh/marginTrading/BFIJ3U", {"response": "json"}),
 ("tpex_new_sbl", "POST", "https://www.tpex.org.tw/www/zh-tw/margin/sbl", {"date": "2026/11/24", "response": "json"}),
 ("tpex_old_sbl", "GET", "https://www.tpex.org.tw/web/stock/margin_trading/margin_sbl/margin_sbl_result.php", {"l": "zh-tw", "d": "115/11/24", "o": "json"}),
 ("tpex_open_sbl", "GET", "https://www.tpex.org.tw/openapi/v1/tpex_margin_sbl", {}),
]
def trim(x, d=0):
    if isinstance(x, list):
        return [trim(v, d+1) for v in x[:4]] + ([f"...共 {len(x)} 筆"] if len(x) > 4 else [])
    if isinstance(x, dict):
        return {k: trim(v, d+1) for k, v in list(x.items())[:30]}
    return x
out = {}
with httpx.Client(headers=UA, timeout=30, follow_redirects=True) as c:
    for name, m, u, p in C:
        try:
            r = c.get(u, params=p) if m == "GET" else c.post(u, data=p)
            try:
                j = r.json(); body = trim(j)
            except Exception:
                body = r.text[:800]
            out[name] = {"status": r.status_code, "url": str(r.url), "body": body}
        except Exception as e:
            out[name] = {"err": repr(e)[:300]}
        time.sleep(3)
json.dump(out, open("scratch_probe/b128_probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
