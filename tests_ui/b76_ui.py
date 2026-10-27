"""B76 版面腳本（PLAN-B76 §1-8；playwright，本機跑、不進 CI）
⚠ B80（2026-10-22）大盤解析改成「結論卡＋頁內分頁」後這支已不適用（多週期一覽表、支撐壓力表等元素拿掉了），改用 tests_ui/b80_ui.py
用法：python tests_ui/b76_ui.py [網址，預設 http://127.0.0.1:8077] [截圖資料夾]
- 加權／台指期 × 4 個週期：0 個 JS 錯誤、K 線有畫、劇本標題跟著週期換（30 分／60 分 K 級數、小級、中級）、撐壓表標題含週期
- 多週期一覽 4 列、點一列會切週期；操作建議（細部解讀）在 K 線上面；之前研究的訊號在上面且展開；融資近 10 天 10 列
- 重新整理、切商品都保留週期（審查 Groq F4）；舊的 wv_mode＝ultra 自動對到 60 分
- 390 寬不出現整頁橫向捲動（審查 Groq F6）"""
import asyncio
import os
import sys

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"
OUT = sys.argv[2] if len(sys.argv) > 2 else None
SCEN = {"30m": "30 分 K", "60m": "60 分 K", "1d": "小級", "1wk": "中級"}
NAME = {"30m": "30 分", "60m": "60 分", "1d": "日 K", "1wk": "週 K"}
fails = []


def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


async def ready(pg, sym):
    await pg.wait_for_function(f"""() => {{ const b=document.querySelector('[data-wv-sym="{sym}"]');
        return b && b.classList.contains('on') && document.querySelector('#wv-chart canvas') && document.querySelectorAll('#wv-ladder tr[data-tf]').length === 4; }}""",
                               timeout=60000)
    await pg.wait_for_timeout(900)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1512, "height": 900})
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE + "/regime/", wait_until="domcontentloaded", timeout=60000)
        await pg.evaluate("() => { try { localStorage.removeItem('wv_tf'); localStorage.setItem('wv_mode','ultra'); localStorage.setItem('wv_sym','TWII'); } catch(e){} }")
        await pg.reload(wait_until="domcontentloaded")
        await ready(pg, "TWII")
        on = await pg.evaluate("() => document.querySelector('[data-wv-tf].on').dataset.wvTf")
        check(on == "60m", f"舊 wv_mode＝ultra 對到 60 分（{on}）")
        pos = await pg.evaluate("""() => { const t=id=>document.getElementById(id).getBoundingClientRect().top;
            return {adv: t('wv-advice'), ctx: t('wv-ctx'), lad: t('wv-ladder'), chart: t('wv-chart'), ctxOpen: document.getElementById('wv-ctx').open,
                    regime: document.getElementById('regime-label-top').getBoundingClientRect().top}; }""")
        check(pos["adv"] < pos["chart"] and pos["lad"] < pos["chart"] and pos["ctx"] < pos["chart"] and pos["regime"] < pos["chart"] and pos["ctxOpen"],
              f"操作建議、總經狀態、之前研究的訊號、多週期一覽都在 K 線上面，研究訊號展開（{pos}）")
        adv = await pg.evaluate("() => document.getElementById('wv-advice').innerText")
        check("建議持股" in adv and ("站上" in adv or "跌破" in adv or "附近沒有" in adv), f"細部解讀有持股範圍和條件：{adv[:60]}…")
        for sym in ("TWII", "TX"):
            await pg.click(f'[data-wv-sym="{sym}"]')
            await ready(pg, sym)
            for tf in ("30m", "60m", "1d", "1wk"):
                await pg.click(f'[data-wv-tf="{tf}"]')
                await pg.wait_for_timeout(900)
                info = await pg.evaluate("""() => ({scen: document.querySelector('#wv-scen .wv-h3').innerText.replace(/\\s+/g, ' '),
                    lv: document.querySelector('#wv-levels .wv-h3').innerText, head: document.querySelector('#wv-sum .wv-head').innerText.split('\\n')[0],
                    canvas: (document.querySelector('#wv-chart canvas')||{}).width || 0, on: document.querySelector('#wv-ladder tr.on').dataset.tf})""")
                ok = SCEN[tf] in info["scen"] and NAME[tf] in info["lv"] and NAME[tf] in info["head"] and info["canvas"] > 0 and info["on"] == tf
                check(ok, f"{sym} {tf}：劇本「{info['scen']}」、撐壓「{info['lv'][:20]}」、標題「{info['head'][:24]}」、一覽標 {info['on']}")
                if OUT and tf in ("30m", "1wk"):
                    await pg.screenshot(path=os.path.join(OUT, f"b76_{sym}_{tf}.png"))
        # 一覽點一列切週期
        await pg.click('#wv-ladder tr[data-tf="1d"]')
        await pg.wait_for_timeout(700)
        on = await pg.evaluate("() => document.querySelector('[data-wv-tf].on').dataset.wvTf")
        check(on == "1d", f"點一覽「日 K」切到日 K（{on}）")
        # 切商品、重新整理保留週期
        await pg.click('[data-wv-tf="30m"]')
        await pg.click('[data-wv-sym="TWII"]')
        await ready(pg, "TWII")
        on1 = await pg.evaluate("() => document.querySelector('[data-wv-tf].on').dataset.wvTf")
        await pg.reload(wait_until="domcontentloaded")
        await ready(pg, "TWII")
        on2 = await pg.evaluate("() => document.querySelector('[data-wv-tf].on').dataset.wvTf")
        check(on1 == "30m" and on2 == "30m", f"切商品、重新整理保留 30 分（{on1}、{on2}）")
        n10 = await pg.evaluate("() => document.querySelectorAll('#wv-margin .wv-m10 tr').length - 1")
        check(n10 == 10, f"融資近 10 天 {n10} 列")
        old = await pg.evaluate("() => document.querySelectorAll('.status-row').length + document.querySelectorAll('[data-wv-iv]').length + document.querySelectorAll('[data-wv-mode]').length")
        check(old == 0, f"舊的總經狀態列／K 線週期按鈕／三模式按鈕都拿掉了（剩 {old}）")
        if OUT:
            await pg.screenshot(path=os.path.join(OUT, "b76_top_1512.png"), full_page=False)
            await pg.locator(".wv-advgrid").screenshot(path=os.path.join(OUT, "b76_advice.png"))
            await pg.locator("#wv-ladder").screenshot(path=os.path.join(OUT, "b76_ladder.png"))
            await pg.locator("#wv-margin").screenshot(path=os.path.join(OUT, "b76_margin.png"))
        check(not errs, f"1512 寬 JS 錯誤 {errs[:3]}")
        await ctx.close()
        ctx = await b.new_context(viewport={"width": 390, "height": 844})
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE + "/regime/", wait_until="domcontentloaded", timeout=60000)
        await ready(pg, "TWII")
        sw = await pg.evaluate("() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})")
        check(sw["sw"] <= sw["cw"] + 1, f"390 寬沒有整頁橫向捲動（{sw}）")
        check(not errs, f"390 寬 JS 錯誤 {errs[:3]}")
        if OUT:
            await pg.screenshot(path=os.path.join(OUT, "b76_390.png"), full_page=False)
        await ctx.close()
        await b.close()
    print("\n結果：", "全部通過" if not fails else f"{len(fails)} 項失敗")
    sys.exit(1 if fails else 0)


asyncio.run(main())
