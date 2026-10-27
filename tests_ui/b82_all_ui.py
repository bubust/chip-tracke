"""B82 §8 全分頁版面（playwright，本機或正式站跑、不進 CI）
用法：python tests_ui/b82_all_ui.py [網址，預設 http://127.0.0.1:8782] [截圖資料夾或 -]
14 個分頁 × 電腦 1440／手機 390：整頁不橫捲、沒有元素跑出畫面（可捲動的表格外框裡除外）、可見文字 ≥ 11px、
手機按鈕高 ≥ 28px；電腦分頁列一行；手機標題列 ≤ 60px；觀察清單／全市場排行手機是卡片；可轉債／收購說明預設收起；0 個 JS 錯誤"""
import asyncio
import json
import sys

from playwright.async_api import async_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8782").rstrip("/")
OUT = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
LOCAL = "127.0.0.1" in BASE or "localhost" in BASE
TABS = ["watchlist", "market", "screen", "tail", "warrant", "regime", "sector", "relationship", "link", "treasury", "mna", "cb", "notes", "discuss"]
IFR = {"warrant": "/warrant/", "regime": "/regime/", "sector": "/sector/", "relationship": "/relationship/"}
fails = []

FAKE_MKT = {"date": "20261022", "server_now": "2026-10-23T20:00:00", "total": 2, "price_ok": True, "markets": {"twse": 1, "tpex": 1},
            "top_buyers": [{"stock_id": "2330", "name": "台積電", "market": "twse", "total_lots": 5000, "foreign_lots": 4000, "trust_lots": 500,
                            "dealer_lots": 500, "sum5_total": 9000, "ratio_pct": 12.5, "close": 1000, "change_pct": 1.2, "foreign_streak": 3,
                            "trust_streak": -2, "signal_level": 2, "signal_emoji": "📈", "signal_title": "強力買超"}],
            "top_sellers": [], "notes": []}

MEASURE = """(vw) => {
  const out = {sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth};
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0'; };
  const over = [], small = [], tiny = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.bottom < 0) continue;
    let p = el.parentElement, inScroll = false;
    while (p && p !== document.body) { const cs = getComputedStyle(p); if (/(auto|scroll|hidden)/.test(cs.overflowX)) { inScroll = true; break; } p = p.parentElement; }
    if (!inScroll && r.right > vw + 2 && el.tagName !== 'OPTION') over.push((el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + String(el.className).slice(0, 24)) + ' r=' + Math.round(r.right));
    const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 0);
    if (hasText && !el.closest('svg,canvas,.tv-lightweight-charts')) { const fs = parseFloat(getComputedStyle(el).fontSize); if (fs < 11) small.push(el.tagName.toLowerCase() + ' ' + fs + 'px「' + el.textContent.trim().slice(0, 12) + '」'); }
    if (vw < 500 && el.tagName === 'BUTTON' && r.height < 28 && !el.closest('.tv-lightweight-charts')) tiny.push(Math.round(r.width) + 'x' + Math.round(r.height) + '「' + el.textContent.trim().slice(0, 10) + '」');
  }
  out.over = over.slice(0, 6); out.small = small.slice(0, 6); out.tiny = tiny.slice(0, 6); out.nOver = over.length; out.nSmall = small.length; out.nTiny = tiny.length;
  return out;
}"""


def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg, flush=True)
    if not ok:
        fails.append(msg)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for name, vw in (("電腦", {"width": 1440, "height": 900}), ("手機", {"width": 390, "height": 844})):
            ctx = await b.new_context(viewport=vw)
            pg = await ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)[:120]))
            if LOCAL:
                body = json.dumps(FAKE_MKT, ensure_ascii=False)

                async def mk(route, request=None, body=body):
                    await route.fulfill(status=200, content_type="application/json", body=body)
                await pg.route("**/api/market/scan**", mk)
            await pg.goto(BASE + "/", wait_until="domcontentloaded")
            await pg.wait_for_function("() => /每天 18:00|還沒有掃描結果/.test((document.getElementById('gh-scan-last-badge') || {}).innerText || '')", timeout=90000)
            hdr = await pg.evaluate("() => ({ h: document.querySelector('header').getBoundingClientRect().height, nav: document.querySelector('nav').getBoundingClientRect().height })")
            if vw["width"] >= 1280:
                check(hdr["nav"] <= 60, f"{name} 分頁列一行（高 {round(hdr['nav'])}px）")
            else:
                check(hdr["h"] <= 60, f"{name} 標題列 ≤ 60px（{round(hdr['h'])}px）")
            for tab in TABS:
                await pg.evaluate(f"switchTab('{tab}')")
                await pg.wait_for_timeout(9000 if tab in IFR else 4500)
                m = await pg.evaluate(MEASURE, vw["width"])
                fr = None
                if tab in IFR:
                    fr = next((f for f in pg.frames if f.url and IFR[tab] in f.url), None)
                    if fr:
                        try:
                            mi = await fr.evaluate(MEASURE, vw["width"] - 16)
                            for k in ("over", "small", "tiny"):
                                m[k] += ["(iframe) " + x for x in mi[k]]
                                m["n" + k.capitalize()] += mi["n" + k.capitalize()]
                        except Exception as e:      # noqa: BLE001
                            m["over"].append(f"(iframe 讀不到 {str(e)[:40]})")
                check(m["sw"] <= m["cw"], f"{name}／{tab}：整頁不橫捲（{m['sw']}／{m['cw']}）")
                check(m["nOver"] == 0, f"{name}／{tab}：沒有元素跑出畫面 {m['over']}")
                check(m["nSmall"] == 0, f"{name}／{tab}：文字 ≥ 11px {m['small']}")
                if vw["width"] < 500:
                    check(m["nTiny"] == 0, f"{name}／{tab}：按鈕高 ≥ 28px {m['tiny']}")
                if OUT:
                    await pg.screenshot(path=f"{OUT}/all_{'d' if vw['width'] > 500 else 'm'}_{tab}.png")
                if vw["width"] < 500 and tab == "watchlist":
                    c = await pg.evaluate("() => [...document.querySelectorAll('#watchlist-table tr.wl-row')].map(r => ({d: getComputedStyle(r).display, w: r.getBoundingClientRect().width}))")
                    check(not c or all(x["d"] == "grid" and x["w"] <= vw["width"] for x in c), f"手機觀察清單是卡片（{len(c)} 張）")
                if vw["width"] < 500 and tab == "market":
                    await pg.wait_for_timeout(1500)
                    c = await pg.evaluate("() => [...document.querySelectorAll('#mkt-tbody tr')].filter(r => !r.querySelector('td[colspan]')).map(r => getComputedStyle(r).display)")
                    check(c and all(x == "grid" for x in c), f"手機全市場排行是卡片（{len(c)} 張）")
                if tab in ("cb", "mna") and name == "電腦":
                    op = await pg.evaluate(f"() => document.getElementById('{tab}-guide').open")
                    check(op is False, f"{tab} 使用說明預設收起")
            check(not errs, f"{name} 0 個 JS 錯誤 {errs[:3]}")
            await ctx.close()
        await b.close()
    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAIL'}")
    sys.exit(1 if fails else 0)


asyncio.run(main())
