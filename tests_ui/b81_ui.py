"""B81 版面腳本（PLAN-B81 §9；playwright，本機跑、不進 CI）
用法：python tests_ui/b81_ui.py [網址，預設 http://127.0.0.1:8098] [截圖資料夾] [B80 結論卡高度（390 寬，量測基準）]
- B80 的檢查全部保留（tests_ui/b80_ui.py）
- 加權／台指期 × 5 週期：結論卡有「🎯 試單」那行；三格沒有空白格（沒有停損就兩格）；三格價位不重複
- 劇本分頁：🎯 現在怎麼試單（試單卡 ≥1、每張有停損或減碼說明、出場步驟 ≥4 步）；週 K 母尺跟日 K 同一段時有提示
- 390 寬：結論卡高度 ≤ B80 的 75%（有給基準時）；沒有橫向捲動
- 舊快照（沒有 setups）：0 個 JS 錯誤"""
import asyncio
import json
import os
import re
import subprocess
import sys

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8098"
OUT = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
BASELINE = float(sys.argv[3]) if len(sys.argv) > 3 else None
TFS = ["15m", "30m", "60m", "1d", "1wk"]
fails = []


def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg, flush=True)
    if not ok:
        fails.append(msg)


async def ready(pg, sym, tf):
    await pg.wait_for_function(f"""() => {{ const s = window.__wvState; const b = document.querySelector('[data-wv-sym="{sym}"]');
        return b && b.classList.contains('on') && s && s.sym === '{sym}' && s.tf === '{tf}'; }}""", timeout=90000)
    await pg.wait_for_timeout(400)


async def main():
    # 先跑 B80 那支（舊的檢查都要過）
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "b80_ui.py"), BASE], capture_output=True, text=True, encoding="utf-8")
    tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
    b80_fail = [x for x in (r.stdout or "").splitlines() if x.startswith("FAIL")]
    check(r.returncode == 0, f"B80 舊檢查全過（{tail[0]}；{b80_fail[:3]}）")
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1512, "height": 950})
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE + "/regime/", wait_until="domcontentloaded", timeout=90000)
        await pg.evaluate("() => { localStorage.setItem('wv_tab','chart'); localStorage.setItem('wv_sym','TWII'); localStorage.setItem('wv_tf','60m'); }")
        await pg.reload(wait_until="domcontentloaded")
        await ready(pg, "TWII", "60m")
        for sym in ("TWII", "TX"):
            await pg.click(f'[data-wv-sym="{sym}"]')
            for tf in TFS:
                await pg.click(f'[data-wv-tf="{tf}"]')
                await ready(pg, sym, tf)
                info = await pg.evaluate("""() => {
                    const ks = [...document.querySelectorAll('#wv-sum .wv-lines .k')].map(x => x.textContent);
                    const tiles = [...document.querySelectorAll('#wv-sum .wv-tile')];
                    return { ks, n: tiles.length, vals: tiles.map(t => (t.querySelector('.v') || {}).textContent || ''),
                             blank: tiles.filter(t => /附近沒有系統價位/.test(t.textContent)).length,
                             two: document.querySelector('#wv-sum .wv-tiles').classList.contains('two') }; }""")
                prices = [re.sub(r"[^\d]", "", v.split("+")[0].split("-")[0].split("−")[0])[:6] for v in info["vals"]]
                check("🎯 試單" in info["ks"], f"{sym} {tf}：結論卡有 🎯 試單（{info['ks'][:3]}）")
                check(info["blank"] == 0 and (info["n"] == 3 or (info["n"] == 2 and info["two"])), f"{sym} {tf}：三格沒有空白（{info['n']} 格、空白 {info['blank']}）")
                check(len(set(prices)) == len(prices), f"{sym} {tf}：三格價位不重複（{prices}）")
        # 劇本分頁：試單拆解
        for sym, tf in (("TWII", "60m"), ("TX", "1d"), ("TWII", "1wk")):
            await pg.click(f'[data-wv-sym="{sym}"]')
            await pg.click(f'[data-wv-tf="{tf}"]')
            await ready(pg, sym, tf)
            await pg.click('[data-wv-tab="plan"]')
            await pg.wait_for_timeout(400)
            pl = await pg.evaluate("""() => { const el = document.getElementById('wv-plan');
                return { cards: el.querySelectorAll('.wv-setup').length, steps: el.querySelectorAll('.wv-exit li').length,
                         stop: [...el.querySelectorAll('.wv-setup')].every(c => /停損|減碼/.test(c.textContent)),
                         res: [...el.querySelectorAll('.wv-setup')].every(c => /回測/.test(c.textContent)),
                         twShort: [...el.querySelectorAll('.wv-setup')].some(c => /減碼區/.test(c.textContent)),
                         txt: el.textContent }; }""")
            check(pl["cards"] >= 1 and pl["stop"] and pl["res"] and pl["steps"] >= 4,
                  f"{sym} {tf} 劇本：試單卡 {pl['cards']}、每張有停損／回測、出場 {pl['steps']} 步")
            if sym == "TWII":
                check(pl["twShort"] or pl["cards"] < 3, f"{sym} {tf} 劇本：加權的試空寫成減碼區")
            if tf == "1wk":
                d = await (await pg.request.get(BASE + f"/api/wave/snapshot?sym={sym}")).json()
                note = ((d.get("levelmap") or {}).get("1wk") or {}).get("mother_note")
                check((not note) or ("母尺跟日 K 同一段" in pl["txt"]), f"{sym} 週 K：母尺同一段時有提示（{note}）")
            await pg.click('[data-wv-tab="chart"]')
        check(not errs, f"桌機 0 個 JS 錯誤（{errs[:3]}）")
        # 手機 390：結論卡高度、橫向捲動
        for wpx in (360, 390):
            m = await b.new_context(viewport={"width": wpx, "height": 800})
            mp = await m.new_page()
            merrs = []
            mp.on("pageerror", lambda e: merrs.append(str(e)))
            await mp.goto(BASE + "/regime/", wait_until="domcontentloaded")
            await mp.evaluate("() => { localStorage.setItem('wv_tab','chart'); localStorage.setItem('wv_sym','TWII'); localStorage.setItem('wv_tf','1d'); }")
            await mp.reload(wait_until="domcontentloaded")
            await mp.wait_for_function("() => window.__wvState && window.__wvState.candles > 0", timeout=90000)
            await mp.wait_for_timeout(600)
            hh = await mp.evaluate("() => document.getElementById('wv-sum').getBoundingClientRect().height")
            sw = await mp.evaluate("() => document.documentElement.scrollWidth")
            check(sw <= wpx + 1, f"{wpx} 寬沒有橫向捲動（{sw}）")
            if wpx == 390 and BASELINE:
                check(hh <= BASELINE * 0.75, f"390 寬結論卡高度 {hh:.0f}px ≤ B80 {BASELINE:.0f} 的 75%")
            else:
                print(f"INFO {wpx} 寬結論卡高度 {hh:.0f}px")
            check(not merrs, f"{wpx} 寬 0 個 JS 錯誤（{merrs[:2]}）")
            if OUT:
                await mp.screenshot(path=os.path.join(OUT, f"b81_mobile{wpx}.png"), full_page=True)
            await m.close()
        # 舊快照（沒有 setups、mother_note、bt）
        o = await b.new_context(viewport={"width": 1280, "height": 900})
        op = await o.new_page()
        oerrs = []
        op.on("pageerror", lambda e: oerrs.append(str(e)))

        async def strip(route):
            r = await route.fetch()
            d = json.loads(await r.text())
            for lm in (d.get("levelmap") or {}).values():
                if isinstance(lm, dict):
                    lm.pop("setups", None)
                    lm.pop("mother_note", None)
                    (lm.get("top3") or {}).pop("stop_src", None)
            ((d.get("advice") or {}).get("range") or {}).pop("bt", None)
            await route.fulfill(status=200, content_type="application/json", body=json.dumps(d, ensure_ascii=False))
        await op.route("**/api/wave/snapshot*", strip)
        await op.goto(BASE + "/regime/", wait_until="domcontentloaded")
        await op.evaluate("() => { localStorage.setItem('wv_tab','plan'); localStorage.setItem('wv_tf','60m'); }")
        await op.reload(wait_until="domcontentloaded")
        await op.wait_for_function("() => document.querySelector('#wv-sum .wv-head') && document.querySelector('#wv-plan .wv-h3')", timeout=90000)
        await op.wait_for_timeout(800)
        check(not oerrs, f"舊快照（沒有試單）0 個 JS 錯誤（{oerrs[:2]}）")
        if OUT:
            for sym, tf, tab in (("TWII", "1d", "chart"), ("TWII", "60m", "plan"), ("TX", "15m", "chart"), ("TX", "1d", "plan")):
                await pg.click('[data-wv-tab="chart"]')                 # 圖表分頁才會更新 __wvState
                await pg.click(f'[data-wv-sym="{sym}"]')
                await pg.click(f'[data-wv-tf="{tf}"]')
                await ready(pg, sym, tf)
                await pg.click(f'[data-wv-tab="{tab}"]')
                await pg.wait_for_timeout(500)
                await pg.screenshot(path=os.path.join(OUT, f"b81_{sym}_{tf}_{tab}.png"), full_page=False)
        await b.close()
    print(f"\n{len(fails)} 個失敗" if fails else "\n全部通過")
    sys.exit(1 if fails else 0)


asyncio.run(main())
