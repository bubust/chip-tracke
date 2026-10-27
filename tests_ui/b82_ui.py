"""B82 版面＋每天新結果（PLAN-B82 §7；playwright，本機跑、不進 CI）
用法：python tests_ui/b82_ui.py [網址，預設 http://127.0.0.1:8782] [截圖資料夾或 -]
- 策略篩選：4 小格、每格高 ≤ 80px、桌機上半部（狀態列＋4 格）≤ 150px；點格子只開一個、✕ 收起
- localStorage 有舊的 v1／v2（finished_at 較舊）＋舊狀態列文字 → 載入後一律是伺服器的結果、狀態列有日期、舊 key 被清掉
- 頁面切回來（visibilitychange）伺服器有更新的掃描 → 自動換新、跳提示
- 狀態列用伺服器時間判斷：今天 18:00 還沒完成／今天休市
- 全市場排行：舊 localStorage → 顯示伺服器的資料日期＋「每天 18:00 自動更新」
- 結果卡：一句結論、回測細節分頁可切換
- 手機 390：兩欄格子、沒有橫向捲動；全程 0 個 JS 錯誤"""
import asyncio
import json
import sys
import urllib.request

from playwright.async_api import async_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8782").rstrip("/")
OUT = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
fails = []


def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg, flush=True)
    if not ok:
        fails.append(msg)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def ymd_label(ymd):
    import datetime
    d = datetime.date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:]))
    return f"{d.month}/{d.day}（{'一二三四五六日'[d.weekday()]}）"


FAKE_MKT = {"date": "20261022", "server_now": "2026-10-23T20:00:00", "total": 2, "price_ok": True, "markets": {"twse": 1, "tpex": 1},
            "top_buyers": [{"stock_id": "2330", "name": "台積電", "market": "twse", "total_lots": 5000, "foreign_lots": 4000, "trust_lots": 500,
                            "dealer_lots": 500, "sum5": 9000, "ratio_pct": 12.5, "close": 1000, "change_pct": 1.2}],
            "top_sellers": [], "notes": []}


def fulfill_json(obj):
    body = json.dumps(obj, ensure_ascii=False)

    async def h(route, request=None):
        await route.fulfill(status=200, content_type="application/json", body=body)
    return h


async def open_screen(pg):
    await pg.goto(BASE + "/", wait_until="domcontentloaded")
    await pg.wait_for_function("() => document.getElementById('gh-scan-last-badge') && /每天 18:00/.test(document.getElementById('gh-scan-last-badge').innerText)", timeout=90000)
    await pg.click("nav button[onclick=\"switchTab('screen')\"]")
    await pg.wait_for_function("() => [...document.querySelectorAll('.scr-tile .t1')].every(x => x.textContent && x.textContent !== '載入中…')", timeout=60000)
    await pg.wait_for_timeout(500)


async def main():
    res = get("/api/screen/results")
    srv_fin, srv_date = res.get("finished_at"), res.get("data_date")
    srv_counts = {k: len(v or []) for k, v in (res.get("results") or {}).items()}
    print("server finished_at", srv_fin, "data_date", srv_date)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        errs = []

        async def new_page(vw, init_js=None, mock_mkt=False):
            ctx = await b.new_context(viewport=vw)
            if init_js:
                await ctx.add_init_script(init_js)
            pg = await ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            if mock_mkt:
                async def mk(route):
                    await route.fulfill(status=200, content_type="application/json", body=json.dumps(FAKE_MKT, ensure_ascii=False))
                await pg.route("**/api/market/scan**", mk)
            return ctx, pg

        local = "127.0.0.1" in BASE or "localhost" in BASE

        # ── 1. 桌機：4 小格、高度、展開區 ──
        ctx, pg = await new_page({"width": 1440, "height": 900}, mock_mkt=local)
        await open_screen(pg)
        m = await pg.evaluate("""() => ({ top: document.querySelector('.scr-top').getBoundingClientRect().height,
            tiles: [...document.querySelectorAll('.scr-tile')].map(x => x.getBoundingClientRect().height),
            badge: document.getElementById('gh-scan-last-badge').innerText })""")
        check(len(m["tiles"]) == 4, f"4 小格（{len(m['tiles'])}）")
        check(all(h <= 80.5 for h in m["tiles"]), f"每格高 ≤ 80px（{[round(h) for h in m['tiles']]}）")
        check(m["top"] <= 150.5, f"桌機上半部 ≤ 150px（{round(m['top'])}）")
        if srv_date:
            check(ymd_label(srv_date) in m["badge"], f"狀態列有伺服器收盤日 {ymd_label(srv_date)}：{m['badge'][:80]}")
        check("每天 18:00 自動更新" in m["badge"], "狀態列寫每天 18:00 自動更新")
        await pg.click('.scr-tile[data-k="course"]')
        await pg.wait_for_timeout(400)
        st = await pg.evaluate("""() => ({ vis: getComputedStyle(document.getElementById('screen-info-panel')).display !== 'none',
            k: document.getElementById('screen-info-panel').dataset.k,
            exp: [...document.querySelectorAll('.scr-tile')].filter(x => x.getAttribute('aria-expanded') === 'true').map(x => x.dataset.k) })""")
        check(st["vis"] and st["k"] == "course" and st["exp"] == ["course"], f"點講義訊號只開它：{st}")
        await pg.click('.scr-tile[data-k="f825"]')
        await pg.wait_for_timeout(400)
        st = await pg.evaluate("() => ({ k: document.getElementById('screen-info-panel').dataset.k, rows: document.querySelectorAll('#screen-info-panel tbody tr').length })")
        check(st["k"] == "f825" and st["rows"] >= 5, f"換成回測總表（{st}）")
        if OUT:
            await pg.screenshot(path=f"{OUT}/b82_desk_panel.png")
        await pg.click('#screen-info-panel .scr-panel-h button')
        await pg.wait_for_timeout(300)
        hid = await pg.evaluate("() => getComputedStyle(document.getElementById('screen-info-panel')).display === 'none'")
        check(hid, "✕ 收起展開區")
        # 結果卡：一句結論、回測細節分頁
        first = next((k for k in ("S2", "S10", "S_BIAS", "S1") if srv_counts.get(k)), None)
        if first:
            await pg.click(f'.screen-strat-btn[data-s="{first}"]')
            await pg.wait_for_function("() => document.getElementById('strat-verdict').innerText.length > 5", timeout=30000)
            v = await pg.evaluate("() => document.getElementById('strat-verdict').innerText")
            check("5 年回測" in v, f"{first} 一句結論：{v[:60]}")
            await pg.click("#strat-research details.scr-detail > summary")
            await pg.wait_for_timeout(300)
            tabs = await pg.evaluate("() => [...document.querySelectorAll('.scr-dtab')].map(x => x.innerText)")
            check(len(tabs) >= 2, f"回測細節分頁 {tabs}")
            if len(tabs) >= 2:
                await pg.click(".scr-dtab:nth-child(2)")
                await pg.wait_for_timeout(400)
                act = await pg.evaluate("() => document.querySelector('.scr-dtab.active').innerText")
                check(act == tabs[1], f"切到第 2 個分頁（{act}）")
        # 全市場排行
        await pg.click("nav button[onclick=\"switchTab('market')\"]")
        await pg.wait_for_function("() => /資料日期/.test(document.getElementById('scan-meta').innerText) && !/更新中/.test(document.getElementById('scan-meta').innerText)", timeout=60000)
        meta = await pg.evaluate("() => document.getElementById('scan-meta').innerText")
        check("每天 18:00 自動更新" in meta, f"全市場排行說明每天 18:00：{meta[:70]}")
        await ctx.close()

        # ── 2. 舊 localStorage（v1＋舊狀態列文字＋舊排行）→ 一律用伺服器 ──
        stale_v1 = {"S1": [{"stock_id": "9999", "name": "舊資料", "close": 1, "last_date": "20260901", "strategy": "S1"}]}
        stale_mkt = {"date": "20261001", "buyers": [{"stock_id": "1101", "name": "舊排行", "total_lots": 1}], "sellers": []}
        init = (f"try {{ if (!sessionStorage.getItem('b82_seeded')) {{ localStorage.setItem('chip_tracker_screen_v1', {json.dumps(json.dumps(stale_v1))});"
                f" localStorage.setItem('chip_scan_badge', JSON.stringify({{text:'下午09:47 ✅ 舊的', isOk:true}}));"
                f" localStorage.setItem('chip_tracker_mkt_v1', {json.dumps(json.dumps(stale_mkt))}); sessionStorage.setItem('b82_seeded','1'); }} }} catch (e) {{}}")
        ctx, pg = await new_page({"width": 1440, "height": 900}, init, mock_mkt=local)
        await open_screen(pg)
        r = await pg.evaluate("""() => ({ badge: document.getElementById('gh-scan-last-badge').innerText,
            s1: (_screenAllResults.S1 || []).length, has9999: (_screenAllResults.S1 || []).some(x => x.stock_id === '9999'),
            v1: localStorage.getItem('chip_tracker_screen_v1'), oldBadge: localStorage.getItem('chip_scan_badge'),
            v2: JSON.parse(localStorage.getItem('chip_tracker_screen_v2') || '{}').finished_at })""")
        check("下午09:47" not in r["badge"], f"舊狀態列文字不再出現：{r['badge'][:60]}")
        check(not r["has9999"] and r["s1"] == srv_counts.get("S1", 0), f"S1 用伺服器的結果（{r['s1']} vs {srv_counts.get('S1', 0)}）")
        check(r["v1"] is None and r["oldBadge"] is None, "舊 key 清掉（v1、chip_scan_badge）")
        check(r["v2"] == srv_fin, f"v2 存伺服器 finished_at（{r['v2']}）")
        await pg.click("nav button[onclick=\"switchTab('market')\"]")
        await pg.wait_for_function("() => /每天 18:00/.test(document.getElementById('scan-meta').innerText)", timeout=60000)
        mk = await pg.evaluate("() => ({ meta: document.getElementById('scan-meta').innerText, old: document.getElementById('mkt-tbody').innerText.includes('舊排行') })")
        check(not mk["old"] and "10/1（四）" not in mk["meta"], f"全市場排行換成伺服器的：{mk['meta'][:60]}")

        # ── 3. 頁面切回來：伺服器有新的掃描 → 自動換新＋提示 ──
        newer = "2099-01-01T18:05:00"
        fake_res = dict(res)
        fake_res.update(finished_at=newer, data_date="20981231", server_now="2099-01-01T19:00:00")
        st0 = get("/api/screen/status")
        fake_st = dict(st0)
        fake_st.update(finished_at=newer, running=False, data_date="20981231", server_now="2099-01-01T19:00:00")

        async def r_st(route):
            await route.fulfill(status=200, content_type="application/json", body=json.dumps(fake_st, ensure_ascii=False))

        async def r_res(route):
            await route.fulfill(status=200, content_type="application/json", body=json.dumps(fake_res, ensure_ascii=False))
        await pg.route("**/api/screen/status", r_st)
        await pg.route("**/api/screen/results", r_res)
        await pg.evaluate("() => { _sfLast = 0; document.dispatchEvent(new Event('visibilitychange')); }")
        await pg.wait_for_function("() => /12\\/31/.test(document.getElementById('gh-scan-last-badge').innerText)", timeout=20000)
        t = await pg.evaluate("() => ({ badge: document.getElementById('gh-scan-last-badge').innerText, toast: (document.getElementById('toast') || {}).innerText || '' })")
        check("12/31" in t["badge"], f"切回來自動換新：{t['badge'][:60]}")
        check("已更新到" in t["toast"], f"跳提示：{t['toast'][:40]}")
        await ctx.close()

        # ── 4. 狀態列規則（伺服器時間）──
        for name, fin, dd, now, expect in (
                ("還沒完成", "2026-10-22T18:10:00", "20261022", "2026-10-23T19:00:00", "還沒完成"),
                ("休市", "2026-10-23T18:05:00", "20261022", "2026-10-23T19:00:00", "今天休市"),
                ("正常", "2026-10-23T18:05:00", "20261023", "2026-10-23T19:00:00", None)):
            fs = dict(st0)
            fs.update(finished_at=fin, running=False, data_date=dd, server_now=now)
            fr = dict(res)
            fr.update(finished_at=fin, data_date=dd, server_now=now)
            ctx, pg = await new_page({"width": 1440, "height": 900}, mock_mkt=True)

            await pg.route("**/api/screen/status", fulfill_json(fs))
            await pg.route("**/api/screen/results", fulfill_json(fr))
            await open_screen(pg)
            bd = await pg.evaluate("() => document.getElementById('gh-scan-last-badge').innerText")
            if expect:
                check(expect in bd, f"狀態列「{name}」：{bd[:90]}")
            else:
                check("還沒完成" not in bd and "休市" not in bd, f"狀態列「{name}」沒有警告：{bd[:70]}")
            await ctx.close()

        # ── 5. 手機 390 ──
        ctx, pg = await new_page({"width": 390, "height": 844}, mock_mkt=local)
        await open_screen(pg)
        mm = await pg.evaluate("""() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
            lefts: [...new Set([...document.querySelectorAll('.scr-tile')].map(x => Math.round(x.getBoundingClientRect().left)))].length,
            tiles: [...document.querySelectorAll('.scr-tile')].map(x => x.getBoundingClientRect().height) })""")
        check(mm["sw"] <= mm["cw"], f"手機沒有橫向捲動（{mm['sw']}／{mm['cw']}）")
        check(mm["lefts"] == 2, f"手機 2 欄（{mm['lefts']}）")
        check(all(h <= 80.5 for h in mm["tiles"]), f"手機每格高 ≤ 80px（{[round(h) for h in mm['tiles']]}）")
        await pg.click('.scr-tile[data-k="opt"]')
        await pg.wait_for_timeout(500)
        mm2 = await pg.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        check(mm2, "手機展開優化研究後仍沒有橫向捲動")
        if OUT:
            await pg.screenshot(path=f"{OUT}/b82_mob_opt.png", full_page=False)
        await ctx.close()
        await b.close()
        check(not errs, f"0 個 JS 錯誤（{errs[:3]}）")
    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAIL'}")
    sys.exit(1 if fails else 0)


asyncio.run(main())
