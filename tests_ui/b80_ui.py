"""B80 版面腳本（PLAN-B80 §10；playwright，本機跑、不進 CI）
用法：python tests_ui/b80_ui.py [網址，預設 http://127.0.0.1:8097] [截圖資料夾]
- 加權／台指期 × 5 個週期：0 個 JS 錯誤、K 線有畫、量的柱子數＝有量的 K 棒數、結論卡 3 格、價位梯有「現在」那列且上下各 ≤4
- 5 個分頁都能切、重新整理記住分頁、存了不對的分頁 → 圖表
- 劇本分頁：分 K 有兩棵版本樹（或劇本）、如果…就…、三條路
- 總經分頁：history-chart 有寬度；先在別的分頁重新整理再切回圖表 → K 線寬度 >0（審查 R1 Gemini F3）
- 360／390 寬沒有整頁橫向捲動
- 舊快照（沒有 volume／levelmap／i15）：0 個 JS 錯誤、量能卡顯示沒有資料"""
import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8097"
OUT = sys.argv[2] if len(sys.argv) > 2 else None
TFS = ["15m", "30m", "60m", "1d", "1wk"]
fails = []


def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


async def ready(pg, sym, tf):
    await pg.wait_for_function(f"""() => {{ const s = window.__wvState; const b = document.querySelector('[data-wv-sym="{sym}"]');
        return b && b.classList.contains('on') && s && s.sym === '{sym}' && s.tf === '{tf}'; }}""", timeout=60000)
    await pg.wait_for_timeout(500)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1512, "height": 950})
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE + "/regime/", wait_until="domcontentloaded", timeout=60000)
        await pg.evaluate("() => { localStorage.setItem('wv_tab','nope'); localStorage.setItem('wv_sym','TWII'); localStorage.setItem('wv_tf','60m'); }")
        await pg.reload(wait_until="domcontentloaded")
        await ready(pg, "TWII", "60m")
        on = await pg.evaluate("() => document.querySelector('[data-wv-tab].on').dataset.wvTab")
        check(on == "chart", f"存了不對的分頁 → 圖表（{on}）")
        for sym in ("TWII", "TX"):
            await pg.click(f'[data-wv-sym="{sym}"]')
            for tf in TFS:
                await pg.click(f'[data-wv-tf="{tf}"]')
                await ready(pg, sym, tf)
                st = await pg.evaluate("() => window.__wvState")
                info = await pg.evaluate("""() => ({
                    tiles: document.querySelectorAll('#wv-sum .wv-tile').length,
                    head: (document.querySelector('#wv-sum .wv-head') || {}).textContent || '',
                    now: document.querySelectorAll('#wv-lmap .wv-now').length,
                    rows: [...document.querySelectorAll('#wv-lmap tr')].map(r => r.classList.contains('wv-now') ? 'NOW' : 'x'),
                    canvas: !!document.querySelector('#wv-chart canvas'),
                    arrows: document.querySelectorAll('#wv-tfbar .ar').length,
                    vol: (document.getElementById('wv-vol') || {}).textContent || '' })""")
                nowi = info["rows"].index("NOW") if "NOW" in info["rows"] else -1
                above, below = nowi, len(info["rows"]) - nowi - 1
                check(st["candles"] > 0 and info["canvas"], f"{sym} {tf}：K 線 {st['candles']} 根")
                check(st["vols"] == st.get("volsExpected"), f"{sym} {tf}：量柱 {st['vols']}＝有量的 K 棒 {st.get('volsExpected')}")
                check(info["tiles"] == 3 and info["now"] == 1 and above <= 4 and below <= 4,
                      f"{sym} {tf}：結論卡 3 格、價位梯現在那列（上 {above}／下 {below}）")
                check(info["arrows"] == 5, f"{sym} {tf}：週期按鈕 5 個方向")
                check("🔋 量能與力道" in info["vol"], f"{sym} {tf}：量能卡")
                if OUT:
                    await pg.screenshot(path=os.path.join(OUT, f"b80_{sym}_{tf}.png"), full_page=False)
        # 劇本分頁
        await pg.click('[data-wv-sym="TWII"]')
        await pg.click('[data-wv-tf="60m"]')
        await ready(pg, "TWII", "60m")
        await pg.click('[data-wv-tab="plan"]')
        await pg.wait_for_timeout(400)
        pl = await pg.evaluate("""() => ({ trees: document.querySelectorAll('#wv-plan .wv-tree-box').length,
            dec: document.querySelectorAll('#wv-plan .wv-dec li').length, roads: document.querySelectorAll('#wv-plan .wv-road').length,
            chartHidden: document.querySelector('[data-pane=chart]').hidden })""")
        check(pl["trees"] >= 1 and pl["roads"] == 3 and pl["chartHidden"], f"劇本分頁：版本樹 {pl['trees']}、三條路 {pl['roads']}、如果…就… {pl['dec']}")
        # 重新整理記住分頁；在別的分頁重新整理再切回圖表 → K 線寬度 >0
        await pg.reload(wait_until="domcontentloaded")
        await pg.wait_for_function("() => document.querySelector('[data-wv-tab].on') && document.querySelector('#wv-sum .wv-head')", timeout=60000)
        on = await pg.evaluate("() => document.querySelector('[data-wv-tab].on').dataset.wvTab")
        check(on == "plan", f"重新整理記住分頁（{on}）")
        await pg.click('[data-wv-tab="chart"]')
        await pg.wait_for_function("() => window.__wvState && window.__wvState.candles > 0", timeout=60000)
        await pg.wait_for_timeout(500)
        w = await pg.evaluate("() => { const c = document.querySelector('#wv-chart canvas'); return c ? c.getBoundingClientRect().width : 0; }")
        check(w > 200, f"從別的分頁切回圖表，K 線寬度 {w:.0f}")
        for tab in ("chips", "ai", "macro"):
            await pg.click(f'[data-wv-tab="{tab}"]')
            await pg.wait_for_timeout(500)
            vis = await pg.evaluate(f"() => !document.querySelector('[data-pane={tab}]').hidden")
            check(vis, f"分頁 {tab} 打得開")
        hw = await pg.evaluate("() => document.getElementById('history-chart').getBoundingClientRect().width")
        check(hw > 200, f"總經分頁 60 日走勢圖寬度 {hw:.0f}")
        ids = await pg.evaluate("() => ['regime-label-top','suggest-action','oh-val','pa-val','dir-val','factors-grid','series-list','wv-ctx'].filter(i => !document.getElementById(i))")
        check(not ids, f"總經程式用到的 id 都在（缺：{ids}）")
        check(not errs, f"桌機 0 個 JS 錯誤（{errs[:3]}）")
        # 手機寬度
        for wpx in (360, 390):
            m = await b.new_context(viewport={"width": wpx, "height": 800})
            mp = await m.new_page()
            merrs = []
            mp.on("pageerror", lambda e: merrs.append(str(e)))
            await mp.goto(BASE + "/regime/", wait_until="domcontentloaded")
            await mp.evaluate("() => localStorage.setItem('wv_tab','chart')")
            await mp.reload(wait_until="domcontentloaded")
            await mp.wait_for_function("() => window.__wvState && window.__wvState.candles > 0", timeout=60000)
            await mp.wait_for_timeout(600)
            sw = await mp.evaluate("() => document.documentElement.scrollWidth")
            check(sw <= wpx + 1, f"{wpx} 寬沒有整頁橫向捲動（scrollWidth {sw}）")
            check(not merrs, f"{wpx} 寬 0 個 JS 錯誤（{merrs[:2]}）")
            if OUT:
                await mp.screenshot(path=os.path.join(OUT, f"b80_mobile{wpx}.png"), full_page=True)
            await m.close()
        # 舊快照：拿掉 B80 欄位
        o = await b.new_context(viewport={"width": 1280, "height": 900})
        op = await o.new_page()
        oerrs = []
        op.on("pageerror", lambda e: oerrs.append(str(e)))

        async def strip(route):
            r = await route.fetch()
            d = json.loads(await r.text())
            for k in ("volume", "levelmap", "vol_unit"):
                d.pop(k, None)
            (d.get("chart") or {}).pop("i15", None)
            for k in ("bars", "weekly", "i30", "i60"):
                for x in (d.get("chart") or {}).get(k) or []:
                    x.pop("volume", None)
            await route.fulfill(status=200, content_type="application/json", body=json.dumps(d, ensure_ascii=False))
        await op.route("**/api/wave/snapshot*", strip)
        await op.goto(BASE + "/regime/", wait_until="domcontentloaded")
        await op.evaluate("() => { localStorage.setItem('wv_tab','chart'); localStorage.setItem('wv_tf','15m'); }")
        await op.reload(wait_until="domcontentloaded")
        await op.wait_for_function("() => window.__wvState", timeout=60000)
        await op.wait_for_timeout(600)
        txt = await op.evaluate("() => document.getElementById('wv-vol').textContent")
        check(not oerrs and ("舊版快照" in txt or "沒有量" in txt), f"舊快照 0 個 JS 錯誤、量能卡顯示沒有資料（{oerrs[:2]}）")
        await b.close()
    print(f"\n{len(fails)} 個失敗" if fails else "\n全部通過")
    sys.exit(1 if fails else 0)


asyncio.run(main())
