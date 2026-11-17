"""暫時檢查：抓兩個選股網站的公開網頁和它載入的 JS／JSON（看選股邏輯）"""
import json, os, re
from urllib.parse import urljoin, urlparse
import httpx
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
SITES = ["https://precipitation.fengyuan55961585.workers.dev/", "https://ksar-trade.vicky741114.workers.dev/"]
os.makedirs("scratch_probe/sites", exist_ok=True)
log = {}
for s in SITES:
    host = urlparse(s).netloc.split(".")[0]
    d = f"scratch_probe/sites/{host}"
    os.makedirs(d, exist_ok=True)
    seen, todo, items = set(), [s], []
    while todo and len(seen) < 25:
        u = todo.pop(0)
        if u in seen:
            continue
        seen.add(u)
        try:
            r = httpx.get(u, headers=UA, timeout=40, follow_redirects=True)
        except Exception as e:  # noqa: BLE001
            items.append({"url": u, "err": repr(e)[:200]}); continue
        ct = r.headers.get("content-type", "")
        name = re.sub(r"[^A-Za-z0-9._-]", "_", urlparse(u).path.strip("/") or "index") [:80]
        if "html" in ct and not name.endswith(".html"):
            name += ".html"
        txt = r.text if ("text" in ct or "json" in ct or "javascript" in ct) else ""
        if txt:
            open(f"{d}/{name}", "w", encoding="utf-8").write(txt[:1500000])
        items.append({"url": u, "status": r.status_code, "ct": ct, "len": len(r.content), "file": name if txt else None})
        if txt and ("html" in ct or "javascript" in ct):
            for m in re.findall(r'(?:src|href)=["\']([^"\']+)["\']', txt) + re.findall(r'["\'`](/[A-Za-z0-9_\-/]+(?:\.js|\.json|api[A-Za-z0-9_\-/?=&.]*))["\'`]', txt):
                full = urljoin(u, m)
                if urlparse(full).netloc == urlparse(s).netloc and full not in seen and not re.search(r"\.(png|jpg|svg|ico|woff2?|css)(\?|$)", full):
                    todo.append(full)
    log[s] = items
json.dump(log, open("scratch_probe/b117.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(log, ensure_ascii=False)[:3000])
