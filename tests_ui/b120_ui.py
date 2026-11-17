"""B120 觀察清單順序：手機為準＋兩邊即時同步＋手機拖拉（playwright，本機跑、不進 CI）
用法：python tests_ui/b120_ui.py [網址，預設 http://127.0.0.1:8791]（觀察清單要先有 3481 2449 4583 4916 6147）
- 伺服器是電腦的順序、手機本機是別的順序 → 手機第一次打開新版：伺服器改成手機的順序
- 電腦開著 → 切回來（visibilitychange）就跟著重排
- 手機按住 ⠿ 拖到別張卡片 → 順序變、伺服器存起來、電腦跟著變；全程 0 個 JS 錯誤"""
import asyncio
import json
import sys
import urllib.request

from playwright.async_api import async_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8791").rstrip("/")
DESK = ["3481", "2449", "4583", "4916", "6147"]
PHONE = ["6147", "4916", "3481", "2449", "4583"]
fails = []


def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg, flush=True)
    if not ok:
        fails.append(msg)


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


async def rows(page):
    return await page.eval_on_selector_all("#wl-tbody tr.wl-row", "els => els.map(e => e.dataset.sid)")


async def wait_rows(page, want, ms=15000):
    for _ in range(ms // 250):
        if await rows(page) == want:
            return True
        await page.wait_for_timeout(250)
    return False


async def main():
    call("POST", "/api/watchlist/order", {"order": DESK})
    errs = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        desk = await b.new_context(viewport={"width": 1400, "height": 900})
        await desk.add_init_script(f"localStorage.setItem('chip_wl_order_v1', '{json.dumps(DESK)}')")
        dp = await desk.new_page()
        dp.on("pageerror", lambda e: errs.append(f"desk: {e}"))
        await dp.goto(BASE + "/")
        check(await wait_rows(dp, DESK), f"電腦：伺服器順序 {DESK}")
        check(call("GET", "/api/watchlist/order")["order"] == DESK, "電腦打開不會改伺服器")

        phone = await b.new_context(**p.devices["iPhone 13"])
        await phone.add_init_script(f"if (!sessionStorage.getItem('x')) {{ sessionStorage.setItem('x', 1); localStorage.setItem('chip_wl_order_v1', '{json.dumps(PHONE)}'); }}")
        pp = await phone.new_page()
        pp.on("pageerror", lambda e: errs.append(f"phone: {e}"))
        await pp.goto(BASE + "/")
        check(await wait_rows(pp, PHONE), f"手機：用手機本機的順序 {PHONE}")
        await pp.wait_for_timeout(800)
        check(call("GET", "/api/watchlist/order")["order"] == PHONE, "手機第一次打開 → 伺服器改成手機的順序")

        await dp.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        check(await wait_rows(dp, PHONE), "電腦切回來 → 跟著變手機的順序")

        await pp.reload()
        check(await wait_rows(pp, PHONE), "手機重新整理：順序不變（不會再被覆蓋）")
        h = pp.locator('#wl-tbody tr.wl-row[data-sid="2449"] .wl-handle')
        check(await h.is_visible(), "手機看得到 ⠿ 拖拉把手")
        check(not await dp.locator('#wl-tbody tr.wl-row[data-sid="2449"] .wl-handle').is_visible(), "電腦不顯示把手")
        # 把 2449 拖到上一張 3481 上 → 2449 排到 3481 前面
        await pp.evaluate("document.querySelector('#wl-tbody tr.wl-row[data-sid=\"3481\"]').scrollIntoView({block: 'start'}); window.scrollBy(0, -120)")
        await pp.wait_for_timeout(300)
        hb = await h.bounding_box()
        tb = await pp.locator('#wl-tbody tr.wl-row[data-sid="3481"]').bounding_box()
        print("handle", hb, "target", tb)
        cdp = await phone.new_cdp_session(pp)
        x, y = hb["x"] + hb["width"] / 2, hb["y"] + hb["height"] / 2
        ty = tb["y"] + tb["height"] / 2
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        for i in range(1, 11):
            await cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y + (ty - y) * i / 10}]})
            await pp.wait_for_timeout(30)
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        want = ["6147", "4916", "2449", "3481", "4583"]
        check(await wait_rows(pp, want, 3000), f"手機拖拉後 {want}（實際 {await rows(pp)}）")
        await pp.wait_for_timeout(800)
        check(call("GET", "/api/watchlist/order")["order"] == want, "拖拉後伺服器存起來")
        check(not await pp.evaluate("document.querySelector('#tab-detail, .modal.open') && document.querySelector('.modal.open') !== null"),
              "拖拉沒有誤開詳細／K 線")
        await dp.evaluate("_pollWlOrder()")
        check(await wait_rows(dp, want), "電腦跟著變（每 20 秒／切回來）")
        await b.close()
    check(not errs, f"0 個 JS 錯誤 {errs[:3]}")
    print("全部通過" if not fails else f"{len(fails)} 項失敗")
    sys.exit(1 if fails else 0)


asyncio.run(main())
