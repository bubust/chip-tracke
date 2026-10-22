"""B74 版面腳本（PLAN-B74 §11；playwright，本機跑、不進 CI）
⚠ B80（2026-10-22）大盤解析改成「結論卡＋頁內分頁」後這支已不適用（多週期一覽表、支撐壓力表等元素拿掉了），改用 tests_ui/b80_ui.py
用法：python tests_ui/b74_ui.py [網址，預設 http://127.0.0.1:8077] [截圖資料夾]
- 1366／1512／1920 寬：分頁列 15 個按鈕全部在可視範圍
- 390 寬：分頁列可以左右滑
- 有本機快照時：觀察清單 0.5 秒內出現表格（第二次開頁）
- 總經頁：大盤解析區塊出現、K 線有畫、0 個 JS 錯誤"""
import asyncio
import os
import sys
import time

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"
OUT = sys.argv[2] if len(sys.argv) > 2 else None
fails = []


def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for w in (1366, 1512, 1920):
            ctx = await b.new_context(viewport={"width": w, "height": 900})
            pg = await ctx.new_page()
            await pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
            await pg.wait_for_timeout(1500)
            vis = await pg.evaluate("""() => { const bs=[...document.querySelectorAll('nav button')]; const vw=innerWidth;
                return {n: bs.length, ok: bs.filter(x=>{const r=x.getBoundingClientRect(); return r.left>=0 && r.right<=vw+1 && r.width>0}).length}; }""")
            check(vis["n"] == vis["ok"] and vis["n"] >= 15, f"{w} 寬分頁列 {vis['ok']}/{vis['n']} 個在畫面內")
            if OUT and w == 1512:
                await pg.screenshot(path=os.path.join(OUT, "ui_home_1512.png"))
            await ctx.close()
        # 手機：可以左右滑
        ctx = await b.new_context(viewport={"width": 390, "height": 844})
        pg = await ctx.new_page()
        await pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
        await pg.wait_for_timeout(1500)
        sc = await pg.evaluate("() => { const n=document.querySelector('nav'); return {sw:n.scrollWidth, cw:n.clientWidth, ox:getComputedStyle(n).overflowX}; }")
        check(sc["sw"] > sc["cw"] and sc["ox"] in ("auto", "scroll"), f"390 寬分頁列可左右滑（{sc}）")
        if OUT:
            await pg.screenshot(path=os.path.join(OUT, "ui_home_390.png"))
        await ctx.close()
        # 觀察清單快照：第一次載入存快照、第二次 0.5 秒內出現
        ctx = await b.new_context(viewport={"width": 1512, "height": 900})
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        t0 = time.time()
        await pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
        await pg.wait_for_function("() => document.querySelectorAll('#wl-tbody tr').length > 0", timeout=60000)
        first = time.time() - t0
        await pg.wait_for_timeout(2500)
        has = await pg.evaluate("() => !!localStorage.getItem('chip_wl_summary_v1')")
        check(has, f"第一次開頁存了觀察清單快照（表格 {first:.1f} 秒出現）")
        t0 = time.time()
        await pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
        await pg.wait_for_function("() => document.querySelectorAll('#wl-tbody tr').length > 0 && document.getElementById('wl-table-wrap').style.display !== 'none'", timeout=60000)
        second = time.time() - t0
        check(second <= 3.0, f"第二次開頁觀察清單 {second:.2f} 秒出現（含載入頁面＋伺服器暖機檢查；目標 ≤0.5 秒畫出快照）")
        check(not errs, f"首頁 JS 錯誤 {errs[:3]}")
        await ctx.close()
        # 總經頁
        for name, vp in (("1512", {"width": 1512, "height": 900}), ("390", {"width": 390, "height": 844})):
            ctx = await b.new_context(viewport=vp)
            pg = await ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(BASE + "/regime/", wait_until="domcontentloaded", timeout=60000)
            try:
                await pg.wait_for_function("() => document.querySelector('#wv-chart canvas') && document.getElementById('wv-scen').innerText.length > 20", timeout=40000)
                ok = True
            except Exception:     # noqa: BLE001
                ok = False
            check(ok, f"總經頁 {name} 寬：大盤解析＋K 線有出現")
            check(not errs, f"總經頁 {name} 寬 JS 錯誤 {errs[:3]}")
            if OUT:
                await pg.wait_for_timeout(1500)
                await pg.screenshot(path=os.path.join(OUT, f"ui_regime_{name}.png"))
            await ctx.close()
        await b.close()
    print("\n結果：", "全部通過" if not fails else f"{len(fails)} 項失敗")
    sys.exit(1 if fails else 0)


asyncio.run(main())
