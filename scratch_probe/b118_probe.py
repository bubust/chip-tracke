"""暫時檢查：「四大金剛」主網站（fourkingkong.vicky741114.workers.dev）首頁和連到的項目"""
import json, os, re
from urllib.parse import urljoin, urlparse
import httpx
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
os.makedirs("scratch_probe/sites/fourkingkong", exist_ok=True)
out = {}
for u in ("https://fourkingkong.vicky741114.workers.dev/", "https://vicky741114.workers.dev/", "https://fengyuan55961585.workers.dev/"):
    try:
        r = httpx.get(u, headers=UA, timeout=40, follow_redirects=True)
        t = r.text
        name = re.sub(r"[^A-Za-z0-9]", "_", urlparse(u).netloc)
        open(f"scratch_probe/sites/fourkingkong/{name}.html", "w", encoding="utf-8").write(t[:1500000])
        out[u] = {"status": r.status_code, "len": len(t), "title": re.findall(r"<title>(.*?)</title>", t, re.S)[:1],
                  "links": sorted(set(re.findall(r'https?://[A-Za-z0-9.\-]+\.workers\.dev[^\s"\'<>)]*', t)))[:60],
                  "hrefs": sorted(set(re.findall(r'href=["\']([^"\'#]+)', t)))[:60]}
    except Exception as e:  # noqa: BLE001
        out[u] = repr(e)[:200]
json.dump(out, open("scratch_probe/b118.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:3000])
