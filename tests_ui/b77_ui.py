"""B77 全系統總檢查 UI 腳本（PLAN-B77 §2；playwright，本機跑、不進 CI）
用法：python tests_ui/b77_ui.py [網址，預設 http://127.0.0.1:8097] [截圖資料夾]
- 首頁：權證／總經／產業 iframe 沒點不載入、請求數 ≤ 60、千張大戶趨勢 1 個請求、研究 API 不重複打
- 停 30 秒：price-cache/status ≤ 1 次（以前每 8 秒）
- K 線：沒有月線斜率副圖、主圖價格範圍 ≤ K 棒範圍 1.8 倍
- 設定頁 🩺 系統健康有結論＋10 項以上；全系統更新框遇到伺服器重開顯示「不用再按」
- 0 個 JS 錯誤；390 寬設定頁不出現整頁橫向捲動"""
import asyncio
import json
import re
import sys
import time
from collections import Counter

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8097"
OUT = sys.argv[2] if len(sys.argv) > 2 else None
fails = []


def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


async def quiet(reqs, secs=2.0, limit=40):
    t0 = time.time()
    last = time.time()
    n0 = len(reqs)
    while time.time() - t0 < limit:
        await asyncio.sleep(0.25)
        if len(reqs) != n0:
            n0, last = len(reqs), time.time()
        if time.time() - last > secs:
            return


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1532, "height": 687})
        pg = await ctx.new_page()
        errs, reqs = [], []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("request", lambda r: reqs.append((time.time(), r.url.replace(BASE, ""), r.resource_type)))
        await pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
        await quiet(reqs, 3.0)
        mine = [u for _, u, t in reqs if not u.startswith("http")]
        api = [re.sub(r"\?.*", "", u) for _, u, t in reqs if t in ("fetch", "xhr") and not u.startswith("http")]
        docs = [u for _, u, t in reqs if t == "document"]
        check(not any(d.startswith(("/regime/", "/sector/", "/warrant/")) for d in docs), f"首頁沒有先載入 iframe（document：{docs}）")
        check(len(mine) <= 60, f"首頁請求數 {len(mine)} ≤ 60")
        check(not any("/tdcc" in u and u.startswith("/api/stock/") for u in api), "沒有每檔一個的 /api/stock/{id}/tdcc")
        check(api.count("/api/tdcc/trends") <= 1, f"千張大戶趨勢 1 個請求（{api.count('/api/tdcc/trends')}）")
        dup = {k: v for k, v in Counter(api).items() if v > 1 and k.startswith(("/api/best", "/api/course/research", "/api/quality"))}
        check(not dup, f"研究 API 不重複打（{dup}）")
        # 停 30 秒：輪詢
        n0 = len(reqs)
        await pg.wait_for_timeout(30000)
        idle = Counter(re.sub(r"\?.*", "", u) for _, u, t in reqs[n0:] if t in ("fetch", "xhr"))
        check(idle.get("/api/price-cache/status", 0) <= 1, f"30 秒內 price-cache/status {idle.get('/api/price-cache/status', 0)} 次 ≤ 1")
        check(not any(k.startswith("/regime/") or k.startswith("/sector/") for k in idle), f"沒點過的總經／產業不輪詢（{dict(idle)}）")
        # K 線
        sid = await pg.evaluate("() => (_wlData && _wlData[0] && _wlData[0].stock_id) || '2330'")
        await pg.evaluate(f"() => openChart('{sid}')")
        await pg.wait_for_function("() => document.querySelector('#lwc-candle canvas') && typeof _maSeriesRefs !== 'undefined' && _maSeriesRefs.ma5", timeout=30000)
        await pg.wait_for_timeout(1500)
        info = await pg.evaluate("""() => {
            const h = document.getElementById('lwc-candle').offsetHeight;
            const s = _maSeriesRefs.ma5;
            const top = s.coordinateToPrice(0), bot = s.coordinateToPrice(h - 30);
            const lr = _lwcCharts[0].timeScale().getVisibleLogicalRange();
            const bars = _drawSeries.data().filter((b, i) => i >= Math.floor(lr.from) && i <= Math.ceil(lr.to));
            const hi = Math.max(...bars.map(b => b.high)), lo = Math.min(...bars.map(b => b.low));
            return { ms: !!document.getElementById('lwc-ms'), panes: _lwcCharts.length, top, bot, hi, lo, h,
                     markers: _drawSeries.markers().length };
        }""")
        ratio = (info["top"] - info["bot"]) / max(1e-9, info["hi"] - info["lo"])
        check(not info["ms"] and info["panes"] == 4, f"K 線沒有月線斜率副圖、4 張圖（{info['panes']}）")
        check(ratio <= 1.8, f"主圖價格範圍是 K 棒範圍的 {ratio:.2f} 倍 ≤ 1.8（標記 {info['markers']} 個、主圖 {info['h']}px）")
        if OUT:
            await pg.screenshot(path=f"{OUT}/b77_kline.png")
        await pg.evaluate("() => { try { closeChart(); } catch (e) { document.getElementById('chart-modal') && (document.getElementById('chart-modal').style.display = 'none'); } }")
        # 總經分頁點了才載入
        await pg.evaluate("() => switchTab('regime')")
        await pg.wait_for_timeout(2500)
        src = await pg.evaluate("() => document.getElementById('regime-iframe').getAttribute('src')")
        check(src == "/regime/", f"點總經分頁才載入（src={src}）")
        n1 = len(reqs)
        await pg.wait_for_timeout(4000)
        multi = [u for _, u, t in reqs[n1 - 60:] if "series_multi" in u] + [u for _, u, t in reqs if "series_multi" in u]
        check(bool(multi), "總經頁用 series_multi 一次拿")
        # 設定頁 🩺
        await pg.evaluate("() => _openSettingsWithAuth()")
        await pg.wait_for_function("() => { const e = document.getElementById('health-summary'); return e && !/檢查中/.test(e.textContent); }", timeout=30000)
        hs = await pg.evaluate("() => ({ s: document.getElementById('health-summary').textContent, n: document.querySelectorAll('#health-items .hl-item').length, mem: document.getElementById('health-mem').textContent })")
        check(bool(hs["s"]) and hs["n"] >= 10, f"🩺 系統健康：{hs['s']}（{hs['n']} 項；{hs['mem']}）")
        if OUT:
            await pg.screenshot(path=f"{OUT}/b77_health.png", full_page=False)
        # 全系統更新框：伺服器剛重開、等著接著跑
        st = await (await pg.request.get(BASE + "/api/refresh_all/status")).json()
        st["running"] = False
        st["interrupted"] = True
        from datetime import datetime, timedelta
        st["resume_at"] = (datetime.now() + timedelta(seconds=90)).isoformat(timespec="seconds")
        k = list(st["steps"])
        for i, key in enumerate(k):
            st["steps"][key]["status"] = "done" if i < 6 else ("interrupted" if i == 6 else "pending")
        await pg.route("**/api/refresh_all/status", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(st, ensure_ascii=False)))
        await pg.evaluate("() => { _rfOpen(); _rfStartPolling(); }")
        await pg.wait_for_timeout(2000)
        msg = await pg.evaluate("() => document.getElementById('refresh-all-done-msg').innerText")
        btn = await pg.evaluate("() => document.getElementById('btn-global-refresh').textContent")
        check("不用再按" in msg and "秒後接著跑" in btn, f"重開後自動接著跑的提示（{msg[:40]}…／按鈕「{btn}」）")
        if OUT:
            await pg.screenshot(path=f"{OUT}/b77_resume.png")
        await pg.unroute("**/api/refresh_all/status")
        check(not errs, f"0 個 JS 錯誤（{errs[:3]}）")
        # 手機寬
        m = await b.new_context(viewport={"width": 390, "height": 844})
        mp = await m.new_page()
        merrs = []
        mp.on("pageerror", lambda e: merrs.append(str(e)))
        await mp.goto(BASE + "/", wait_until="domcontentloaded")
        await mp.wait_for_timeout(2500)
        await mp.evaluate("() => _openSettingsWithAuth()")
        await mp.wait_for_function("() => { const e = document.getElementById('health-summary'); return e && !/檢查中/.test(e.textContent); }", timeout=30000)
        ovf = await mp.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        check(ovf <= 0, f"390 寬設定頁沒有整頁橫向捲動（{ovf}px）")
        check(not merrs, f"手機 0 個 JS 錯誤（{merrs[:3]}）")
        if OUT:
            await mp.screenshot(path=f"{OUT}/b77_health_390.png", full_page=False)
        await b.close()
    print("\n" + ("全部通過" if not fails else f"{len(fails)} 項失敗"))
    sys.exit(1 if fails else 0)


asyncio.run(main())
