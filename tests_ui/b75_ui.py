"""B75 版面腳本（PLAN-B75 §11；playwright，本機跑、不進 CI）
用法：python tests_ui/b75_ui.py [網址，預設 http://127.0.0.1:8077] [截圖資料夾]
- 加權／台指期 × 三個模式 × 四個時間框切換：0 個 JS 錯誤、K 線有畫、摘要第 3 格是轉弱點／轉強點且離現價 ≤ 模式窗口
- 過熱恐慌在摘要卡下面、K 線上面，高度 ≤ 90px（桌機）
- 綜合研判、融資增減區塊出現
- 390 寬不出現整頁橫向捲動"""
import asyncio
import os
import re
import sys

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"
OUT = sys.argv[2] if len(sys.argv) > 2 else None
WIN = {"ultra": 3.0, "short": 6.0, "swing": 15.0}
fails = []


def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


async def wait_ready(pg, sym):
    await pg.wait_for_function(f"""() => {{ const b=document.querySelector('[data-wv-sym="{sym}"]');
        return b && b.classList.contains('on') && document.querySelector('#wv-chart canvas') && document.getElementById('wv-sum').innerText.includes('走勢'); }}""",
                               timeout=60000)
    await pg.wait_for_timeout(1200)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1512, "height": 900})
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE + "/regime/", wait_until="domcontentloaded", timeout=60000)
        await pg.evaluate("() => { try { localStorage.removeItem('wv_sym'); localStorage.setItem('wv_mode','short'); localStorage.setItem('wv_iv','1d'); } catch(e){} }")
        await pg.reload(wait_until="domcontentloaded")
        await wait_ready(pg, "TWII")
        # 過熱恐慌位置
        pos = await pg.evaluate("""() => { const r=e=>e.getBoundingClientRect(); const s=r(document.getElementById('wv-sum')), o=r(document.querySelector('.oh-mini')),
            c=r(document.getElementById('wv-chart')); return {s:s.bottom, o:o.top, oh:o.height, c:c.top, old: document.querySelectorAll('.oh-grid').length}; }""")
        check(pos["s"] <= pos["o"] < pos["c"] and pos["oh"] <= 90 and pos["old"] == 1,
              f"過熱恐慌在摘要卡下、K 線上，高度 {pos['oh']:.0f}px、只有一組（{pos}）")
        for sym in ("TWII", "TX"):
            await pg.click(f'[data-wv-sym="{sym}"]')
            await wait_ready(pg, sym)
            for mode in ("ultra", "short", "swing"):
                await pg.click(f'[data-wv-mode="{mode}"]')
                await pg.wait_for_timeout(900)
                tile = await pg.evaluate("() => { const t=document.querySelectorAll('#wv-sum .wv-tile')[2]; return t ? t.innerText : ''; }")
                head = tile.split("\n")[0] if tile else ""
                m = re.search(r"([+\-−]?\d+(?:\.\d+)?)%", tile.split("\n")[1] if "\n" in tile else "")
                dist = abs(float(m.group(1).replace("−", "-"))) if m else None
                # 計畫 §1-1：中位數在範圍內（研究驗）；單次只要求比波浪最後防線近、而且不超過窗口 1.5 倍
                wm = re.search(r"最後防線 [\d,]+（([+\-−]?\d+(?:\.\d+)?)%", tile)
                wdist = abs(float(wm.group(1).replace("−", "-"))) if wm else None
                ok = head in ("轉弱點", "轉強點") and dist is not None and dist <= WIN[mode] * 1.5 and (wdist is None or dist < wdist)
                if head == "轉折點":       # 超短線資料不足時的照實說明
                    ok = mode == "ultra"
                check(ok, f"{sym} {mode}：第 3 格「{head}」離現價 {dist}%（窗口 {WIN[mode]}%，波浪最後防線 {wdist}%）")
                for iv in ("30m", "60m", "1d", "1wk"):
                    await pg.click(f'[data-wv-iv="{iv}"]')
                    await pg.wait_for_timeout(500)
                    n = await pg.evaluate("() => { const c=document.querySelector('#wv-chart canvas'); return c ? c.width : 0; }")
                    leg = await pg.evaluate("() => document.getElementById('wv-legend').innerText")
                    check(n > 0 and len(leg) > 3, f"{sym} {mode} {iv}：K 線有畫（圖例：{leg[:30]}…）")
                if OUT and mode == "ultra":
                    await pg.click('[data-wv-iv="60m"]')
                    await pg.wait_for_timeout(800)
                    await pg.screenshot(path=os.path.join(OUT, f"b75_{sym}_ultra_60m.png"))
            for sec in ("wv-comp", "wv-margin", "wv-chips"):
                t = await pg.evaluate(f"() => document.getElementById('{sec}').innerText")
                check(len(t) > 10, f"{sym} 區塊 {sec} 有內容：{t[:40]}…")
        # 切模式自動換 K 線
        await pg.click('[data-wv-mode="ultra"]')
        await pg.wait_for_timeout(500)
        on = await pg.evaluate("() => document.querySelector('[data-wv-iv].on').dataset.wvIv")
        check(on == "60m", f"超短線預設 60 分 K（{on}）")
        await pg.click('[data-wv-mode="short"]')
        await pg.wait_for_timeout(500)
        on = await pg.evaluate("() => document.querySelector('[data-wv-iv].on').dataset.wvIv")
        check(on == "1d", f"短線預設日 K（{on}）")
        await pg.evaluate("() => document.getElementById('wv-comp').open = true")
        if OUT:
            await pg.screenshot(path=os.path.join(OUT, "b75_1512.png"), full_page=False)
            await pg.locator("#wv-comp").screenshot(path=os.path.join(OUT, "b75_comp.png"))
        check(not errs, f"1512 寬 JS 錯誤 {errs[:3]}")
        await ctx.close()
        # 手機
        ctx = await b.new_context(viewport={"width": 390, "height": 844})
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE + "/regime/", wait_until="domcontentloaded", timeout=60000)
        await wait_ready(pg, await pg.evaluate("() => localStorage.getItem('wv_sym') || 'TWII'"))
        sw = await pg.evaluate("() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})")
        check(sw["sw"] <= sw["cw"] + 1, f"390 寬沒有整頁橫向捲動（{sw}）")
        check(not errs, f"390 寬 JS 錯誤 {errs[:3]}")
        if OUT:
            await pg.screenshot(path=os.path.join(OUT, "b75_390.png"), full_page=False)
        await ctx.close()
        await b.close()
    print("\n結果：", "全部通過" if not fails else f"{len(fails)} 項失敗")
    sys.exit(1 if fails else 0)


asyncio.run(main())
