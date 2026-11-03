"""B91 尾盤追蹤 13:15＋日線結構＋大盤盤面、總經頁過熱恐慌移到最上面、融資使用率（playwright，本機跑、不進 CI）
用法：python tests_ui/b91_ui.py [網址，預設 http://127.0.0.1:8789] [截圖資料夾或 -]
- 尾盤追蹤：結論列只算計入的；分盤勢一行；盤勢下拉篩選有效；不計入收起來、展開有表、超過 30 筆有「顯示全部」；研究卡有表；
  每列股名下有大盤小字；手機 390 沒有橫向捲動；0 個 JS 錯誤
- 總經頁：過熱、恐慌在最上面標題列（第一屏、捲下去還看得到）、籌碼分頁沒有重複的卡
- 融資卡：深度分析的融資維持率卡有「融資使用率」那一行（假資料 route）"""
import asyncio
import json
import sys

from playwright.async_api import async_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8789").rstrip("/")
OUT = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
fails = []


def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg, flush=True)
    if not ok:
        fails.append(msg)


RULES = [{"family": "M4", "family_name": "大盤日線結構", "bucket": "空頭", "side": "bad", "pass": True,
          "is": {"n": 300, "win": .2, "mean": -.02}, "oos": {"n": 120, "win": .18, "mean": -.031}, "rand_oos": {"n": 500, "win": .22}},
         {"family": "M1", "family_name": "13:15 大盤漲跌", "bucket": "≥+1%", "side": "good", "pass": False,
          "is": {"n": 300, "win": .35, "mean": .02}, "oos": {"n": 120, "win": .27, "mean": .001}, "rand_oos": {"n": 500, "win": .25}}]


def fake_list(real):
    """真的清單＋假研究（有一條通過的規則），讓前端每個區塊都畫得出來"""
    real = dict(real)
    real["research"] = {"generated": "2026-11-03 18:00", "is": ["20211001", "20240630"], "oos": ["20240701", "20261103"],
                        "base": {"oos": {"n": 1800, "win": .267, "mean": -.002}},
                        "q1": {"A": {"oos": {"n": 4500, "win": .26, "mean": -.003}}, "B": {"oos": {"n": 1800, "win": .267, "mean": -.002}},
                               "rand_B": {"oos": {"n": 1800, "win": .24, "mean": -.01}}},
                        "rules": RULES, "notes": ["測試用的假研究"],
                        "families": {"M4": {"name": "大盤日線結構", "buckets": {"多頭": {"oos": {"n": 600, "win": .3, "mean": .004}},
                                                                            "盤整": {"oos": {"n": 900, "win": .26, "mean": -.002}},
                                                                            "空頭": {"oos": {"n": 120, "win": .18, "mean": -.031}}}},
                                     "M1": {"name": "13:15 大盤漲跌", "buckets": {"≥+1%": {"oos": {"n": 120, "win": .27, "mean": .001}}}}}}
    for r in real.get("rows", []):                        # 讓某幾天變成 ⚠
        if r["mkt"].get("label") == "neutral" and r["entry_date"] >= "2026-10-28":
            r["mkt"] = {**r["mkt"], "label": "bad", "text": "⚠ 不適合"}
    return real


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for w, h, tag in ((1440, 900, "d"), (390, 844, "m")):
            ctx = await b.new_context(viewport={"width": w, "height": h})
            pg = await ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))

            async def tail_route(route):
                r = await route.fetch()
                body = fake_list(await r.json())
                await route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))
            await pg.route("**/api/tail/list", tail_route)
            await pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=90000)
            await pg.wait_for_timeout(2500)
            await pg.evaluate("() => switchTab('tail')")
            await pg.wait_for_function("() => document.getElementById('tail-status').textContent.includes('更新')", timeout=120000)
            await pg.wait_for_timeout(800)
            info = await pg.evaluate("""() => {
                const t = id => (document.getElementById(id) || {}).textContent || '';
                const ng = document.getElementById('tail-ng'), rs = document.getElementById('tail-research');
                return {sum: t('tail-summary'), bymkt: t('tail-bymkt'), ng: t('tail-ng-sum'), ngShown: ng.style.display !== 'none', ngOpen: ng.open,
                        res: t('tail-research-sum'), resShown: rs.style.display !== 'none',
                        sub: (document.querySelector('#tail-watch td.l, #tail-stop-zone td.l') || {}).textContent || '',
                        nw: +t('tail-n-watch'), ns: +t('tail-n-stop'),
                        sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth}; }""")
            check("計入" in info["sum"], f"[{tag}] 結論列只算計入的：{info['sum'][:60]}")
            check("⚠ 不適合盤勢" in info["bymkt"] and "依進場那天的大盤" in info["bymkt"], f"[{tag}] 分盤勢一行：{info['bymkt'][:80]}")
            check(info["ngShown"] and not info["ngOpen"] and "不計入" in info["ng"], f"[{tag}] 不計入收起來：{info['ng'][:60]}")
            check(info["resShown"] and "大盤盤勢研究" in info["res"] and "比較差" in info["res"], f"[{tag}] 研究卡結論：{info['res'][:60]}")
            check("大盤" in info["sub"], f"[{tag}] 股名下有大盤小字：{info['sub'][:60]}")
            check(info["sw"] <= info["cw"] + 1, f"[{tag}] 沒有橫向捲動 {info['sw']}/{info['cw']}")
            # 盤勢篩選
            before = info["nw"] + info["ns"]
            await pg.select_option("#tail-mkt", "bad")
            await pg.wait_for_timeout(300)
            after = await pg.evaluate("() => +document.getElementById('tail-n-watch').textContent + +document.getElementById('tail-n-stop').textContent")
            check(0 < after < before, f"[{tag}] 盤勢篩選 ⚠：{before} → {after}")
            await pg.select_option("#tail-mkt", "")
            # 展開不計入、研究卡
            await pg.evaluate("() => { document.getElementById('tail-ng').open = true; document.getElementById('tail-research').open = true; }")
            await pg.wait_for_timeout(300)
            ex = await pg.evaluate("""() => ({rows: document.querySelectorAll('#tail-ng-body tbody tr').length,
                more: !!document.querySelector('#tail-ng-body button'),
                resRows: document.querySelectorAll('#tail-research-body tbody tr').length,
                reason: (document.querySelector('#tail-ng-body tbody tr td:nth-child(6)') || {}).textContent || '',
                sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})""")
            check(ex["rows"] > 0 and ex["reason"].strip() != "", f"[{tag}] 不計入表 {ex['rows']} 列、有原因：{ex['reason'][:20]}")
            check(ex["resRows"] >= 4, f"[{tag}] 研究卡表 {ex['resRows']} 列")
            check(ex["sw"] <= ex["cw"] + 1, f"[{tag}] 展開後沒有橫向捲動 {ex['sw']}/{ex['cw']}")
            if OUT:
                await pg.screenshot(path=f"{OUT}/b91_tail_{tag}.png", full_page=True)
            check(not errs, f"[{tag}] 尾盤追蹤 0 個 JS 錯誤 {errs[:2]}")

            # 總經頁：過熱恐慌在最上面
            rp = await ctx.new_page()
            rerrs = []
            rp.on("pageerror", lambda e: rerrs.append(str(e)))
            await rp.goto(BASE + "/regime/", wait_until="domcontentloaded", timeout=90000)
            await rp.wait_for_timeout(5000)
            o = await rp.evaluate("""() => { const e = document.getElementById('oh-top'); const r = e.getBoundingClientRect();
                return {top: r.top, bottom: r.bottom, vh: innerHeight, inSticky: !!e.closest('#wv-sticky'),
                        mini: document.querySelectorAll('.oh-mini').length, ids: ['oh-val','pa-val','oh-bar','pa-bar','oh-st','pa-st'].filter(i => !document.getElementById(i)),
                        v: document.getElementById('oh-val').textContent, st: document.getElementById('pa-st').textContent}; }""")
            check(o["inSticky"] and o["bottom"] < o["vh"] * 0.5 and not o["mini"] and not o["ids"],
                  f"[{tag}] 過熱恐慌在最上面固定列 top={o['top']:.0f}、籌碼分頁沒有重複、id 都在（{o['v']}｜{o['st']}）")
            await rp.mouse.wheel(0, 2500)
            await rp.wait_for_timeout(800)
            o2 = await rp.evaluate("() => document.getElementById('oh-top').getBoundingClientRect().top")
            check(0 <= o2 < 200, f"[{tag}] 捲下去還看得到過熱恐慌 top={o2:.0f}")
            if OUT:
                await rp.screenshot(path=f"{OUT}/b91_regime_{tag}.png")
            check(not rerrs, f"[{tag}] 總經頁 0 個 JS 錯誤 {rerrs[:2]}")
            await ctx.close()

        # 真的研究結果（tail_research.json 沒有通過的規則）→ 分組改用大盤日線多頭／盤整／空頭、研究卡寫沒找到
        ctx = await b.new_context(viewport={"width": 1440, "height": 900})
        pg = await ctx.new_page()
        await pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=90000)
        await pg.wait_for_timeout(2500)
        await pg.evaluate("() => switchTab('tail')")
        await pg.wait_for_function("() => document.getElementById('tail-status').textContent.includes('更新')", timeout=120000)
        await pg.wait_for_timeout(500)
        real = await pg.evaluate("""() => ({by: document.getElementById('tail-bymkt').textContent, res: document.getElementById('tail-research-sum').textContent,
              passed: _tailPassed().length, body: document.getElementById('tail-research-body').textContent})""")
        check(real["passed"] == 0 and "大盤日線" in real["by"] and "沒有通過檢定" in real["by"], f"真研究：沒有通過的規則 → 用大盤日線分組：{real['by'][:90]}")
        check("沒找到明顯" in real["res"] and "事後觀察" in real["body"], f"真研究卡：{real['res'][:60]}")
        await ctx.close()

        # 融資卡（深度分析）：直接呼叫 _dpMaint 用假資料畫
        ctx = await b.new_context(viewport={"width": 1440, "height": 900})
        pg = await ctx.new_page()
        await pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=90000)
        await pg.wait_for_timeout(2000)
        html = await pg.evaluate("""() => _dpMaint({maint: 153, level: 'ok', cost: 50.69, lev: 0.6, calib: 0.8851, market: '上市', call_price: 35,
              to_call_pct: -15.1, bal: 299939, chg5: -14674, conf: 100, date: '2026-11-02', use_rate: 31.27, lim: 959200, err_ref: 0.5,
              series: Array.from({length: 30}, (_, i) => ({date: '2026-10-' + String(i + 1).padStart(2, '0'), maint: 150 + i, cost: 50, close: 76, bal: 300000, use: 28 + i * 0.1}))})""")
        check("融資使用率" in html and "31.3%" in html and "偏高" in html and "20 天前 28.9%" in html, "融資卡有融資使用率（31.3%、偏高、20 天前）")
        check("誤差參考 ±0.5 點" in html and "回補一年內" in html and "驗算" in html, "融資卡有誤差參考＋驗算說明")
        html2 = await pg.evaluate("() => _dpMaint({maint: 153, level: 'ok', cost: 50, lev: 0.6, market: '上市', call_price: 35, to_call_pct: -15, bal: 1, chg5: 0, conf: 100, date: 'x'})")
        check("融資限額還沒抓到" in html2, "沒有限額 → 寫還沒抓到")
        await ctx.close()
        await b.close()
    print("ALL PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
