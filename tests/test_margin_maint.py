"""🩸 個股融資維持率（估計）：用每天融資買進 × 當天均價累積平均融資成本 → 維持率＝股價 ÷（成本 × 融資成數）
用戶：「我想知道股票的融資維持率 140% 以下的標的」（交易所只公布整體維持率，個股要估）
python -m pytest tests/test_margin_maint.py -q（不連網）"""
import os
import sqlite3
import sys
from datetime import date, timedelta

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chip_course as cc  # noqa: E402
import margin_maint as MM  # noqa: E402
from cb.parser import parse_tpex_margin_flow, parse_twse_margin_flow  # noqa: E402

# 2026-10-30 官方回應的真實列（GitHub Actions 實測：前日餘額＋買進－賣出－現償＝今日餘額，上市 1304 檔、上櫃 919 檔全部成立）
TW = {"date": "20261030", "stat": "OK", "tables": [
    {"title": "信用交易統計", "fields": ["項目", "買進", "賣出", "現金(券)償還", "前日餘額", "今日餘額"]},
    {"fields": ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額", "次一營業日限額", "買進", "賣出", "現券償還",
                "前日餘額", "今日餘額", "次一營業日限額", "資券互抵", "註記"],
     "groups": [{"title": "股票", "span": 2}, {"title": "融資", "span": 6}, {"title": "融券", "span": 6}, {"title": "", "span": 1},
                {"title": "", "span": 1}],
     "data": [["2409", "友達", "14,366", "32,448", "338", "288,417", "269,997", "1,886,774", "4,887", "10,966", "0", "13,905", "19,984",
               "1,886,774", "124", " "],
              ["3481", "群創", "5,755", "15,759", "150", "313,846", "303,692", "1,997,299", "448", "2,499", "5", "1,974", "4,020",
               "1,997,299", "59", " "]]}]}
TP = {"tables": [{"title": "上櫃股票融資融券餘額", "date": "115/10/30",
                  "fields": ["代號", "名稱", "前資餘額(張)", "資買", "資賣", "現償", "資餘額", "資屬證金", "資使用率(%)", "資限額",
                             "前券餘額(張)", "券賣", "券買", "券償", "券餘額", "券屬證金", "券使用率(%)", "券限額", "資券相抵(張)", "備註"],
                  "data": [["3105", "穩懋", "40,995", "1,898", "1,782", "2", "41,109", "424", "38.78", "105,985", "1,566", "376", "550",
                            "0", "1,392", "53", "1.31", "105,985", "68", ""]]}]}


def test_parsers_and_balance_identity():
    tw, tp = parse_twse_margin_flow(TW), parse_tpex_margin_flow(TP)
    assert tw["2409"] == ("友達", 14366, 32448, 338, 288417, 269997, 124)
    assert tp["3105"] == ("穩懋", 1898, 1782, 2, 40995, 41109, 68)
    for _, b, s, r, pv, bl, _off in list(tw.values()) + list(tp.values()):
        assert pv + b - s - r == bl
    assert parse_twse_margin_flow({"stat": "很抱歉，沒有符合條件的資料!"}) == {}


def test_official_totals():
    """官方融資金額總數（大盤融資維持率用）：證交所「信用交易統計」、櫃買 summary（2026-10-30 真實數字）"""
    from cb.parser import parse_tpex_margin_total, parse_twse_margin_total
    tw = {"tables": [{"fields": ["項目", "買進", "賣出", "現金(券)償還", "前日餘額", "今日餘額"],
                      "data": [["融資(交易單位)", "353,926", "377,224", "9,729", "9,588,756", "9,555,729"],
                               ["融券(交易單位)", "36,026", "45,607", "1,224", "189,002", "197,359"],
                               ["融資金額(仟元)", "20,744,449", "29,996,997", "1,190,414", "633,910,848", "623,467,886"]]}] + TW["tables"][1:]}
    assert parse_twse_margin_total(tw) == {"bal_lots": 9555729, "amt_k": 623467886, "buy_lots": 353926, "buy_amt_k": 20744449,
                                           "sell_amt_k": 29996997, "repay_amt_k": 1190414}
    tp = {"tables": [{**TP["tables"][0], "summary": [
        ["", "合計(張)", "2,335,123", "53,116", "79,207", "1,764", "2,307,268", "", "", "", "37,451", "5,362", "6,062", "573", "36,178",
         "", "", "", "", ""],
        ["", "融資金(仟元)", "209,958,881", "6,036,883", "10,403,471", "290,948", "205,301,345", "", "", "", "", "", "", "", "", "", "",
         "", "", ""]]}]}
    assert parse_tpex_margin_total(tp) == {"bal_lots": 2307268, "amt_k": 205301345, "buy_lots": 53116, "buy_amt_k": 6036883,
                                           "sell_amt_k": 10403471, "repay_amt_k": 290948}
    assert parse_twse_margin_total(TW) is None and parse_tpex_margin_total(TP) is None


def _rows(spec):
    """spec：[(買進, 賣出, 現償, 今日餘額, 資券互抵)] → estimate 的 rows（前日餘額自動接）"""
    out, prev = [], None
    d0 = date(2026, 6, 1)
    for k, (b, s, r, bl, off) in enumerate(spec):
        pv = bl if prev is None else prev
        out.append(((d0 + timedelta(days=k)).isoformat(), b, s, r, pv, bl, off))
        prev = bl
    return out


def _px(closes):
    d0 = date(2026, 6, 1)
    return {(d0 + timedelta(days=k)).isoformat(): (c, c, c) for k, c in enumerate(closes)}


def test_average_cost_and_maintenance():
    # 第一天 1000 張、均價 100（不知道成本 → 用 100）；第二天 91 元買 1000 張 → 平均 95.5；第三天賣 1000 張 → 照平均成本扣，還是 95.5
    rows = _rows([(0, 0, 0, 1000, 0), (1000, 0, 0, 2000, 0), (0, 900, 100, 1000, 0)])
    e = MM.estimate(rows, _px([100, 91, 83]))
    assert e["avg"] == pytest.approx(95.5) and e["bal"] == 1000 and e["close"] == 83
    assert MM.maint_of(83, e["avg"], "twse") == pytest.approx(83 / (95.5 * 0.6) * 100)     # 144.9%
    assert MM.maint_of(83, e["avg"], "tpex") == MM.maint_of(83, e["avg"], "twse")          # 上櫃也是 6 成（官方買進金額實測 0.556）
    assert MM.maint_of(83, e["avg"], "twse", 0.885) == pytest.approx(83 / (95.5 * 0.6 * 0.885) * 100)   # 官方融資金額校正
    assert e["conf"] == pytest.approx(0.5)                                                 # 現在的融資一半是回補第一天就有的


def test_day_trade_offset_does_not_move_cost():
    """資券互抵（當日沖銷）同時算在買進跟賣出裡 → 先扣掉，不能讓當天價格把平均成本拉過去"""
    base = MM.estimate(_rows([(0, 0, 0, 1000, 0), (0, 0, 0, 1000, 0)]), _px([100, 92]))
    dt = MM.estimate(_rows([(0, 0, 0, 1000, 0), (800, 800, 0, 1000, 800)]), _px([100, 92]))
    assert dt["avg"] == pytest.approx(base["avg"]) == pytest.approx(100)


def test_capital_reduction_keeps_maintenance():
    """減資 2:1：張數減半、股價變兩倍 → 平均成本跟著變兩倍，維持率不跳"""
    rows = _rows([(0, 0, 0, 1000, 0), (0, 0, 0, 1000, 0)])
    rows.append(("2026-06-03", 0, 0, 0, 500, 500, 0))
    e = MM.estimate(rows, {**_px([100, 90]), "2026-06-03": (180, 180, 180)})
    assert e["adj"] == 1 and e["avg"] == pytest.approx(200)
    assert MM.maint_of(180, e["avg"], "twse") == pytest.approx(MM.maint_of(90, 100, "twse"))


def test_missing_price_day_uses_running_cost():
    e = MM.estimate(_rows([(0, 0, 0, 1000, 0), (500, 0, 0, 1500, 0), (0, 0, 0, 1500, 0)]), {"2026-06-01": (100, 100, 100),
                                                                                       "2026-06-03": (95, 95, 95)})
    assert e["avg"] == pytest.approx(100) and e["close"] == 95


def test_save_flows_skips_other_date_and_backfill_marks_holidays(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "DB_PATH", tmp_path / "course.db")
    c = cc.get_conn()
    n = MM.save_flows(c, "2026-10-30", {"twse": parse_twse_margin_flow(TW), "twse_date": "2026-10-30",
                                        "tpex": parse_tpex_margin_flow(TP), "tpex_date": "2026-10-29"})
    assert n == {"twse": 2, "tpex": 0}
    c.commit()
    c.close()

    import cb.fetcher as F
    calls = []

    def fake(cl, d, flows=None):
        calls.append(d)
        if d.weekday() == 0:                       # 週一當休市：有回應、沒資料
            flows.update(twse={}, twse_date=None, tpex={}, tpex_date=None)
        elif d.weekday() == 1:                     # 週二連線失敗：什麼都沒有
            pass
        else:
            ds = d.isoformat()
            tot = {"bal_lots": 100, "amt_k": 5000, "buy_lots": 10, "buy_amt_k": 500, "sell_amt_k": 0, "repay_amt_k": 0}
            flows.update(twse={"2409": ("友達", 10, 0, 0, 100, 110, 0)}, twse_date=ds, tpex={"3105": ("穩懋", 0, 5, 0, 50, 45, 0)},
                         tpex_date=ds, twse_total=tot, tpex_total=tot)
        return {}, {}
    monkeypatch.setattr(F, "fetch_margin_day", fake)
    monkeypatch.setattr(MM.time, "sleep", lambda s: None)
    st = MM.backfill(n_days=10)
    assert st["closed"] > 0 and st["failed"] > 0 and st["fetched"] > 0
    calls.clear()
    st2 = MM.backfill(n_days=10)                   # 第二次：只重抓連線失敗的日子
    assert calls and all(d.weekday() == 1 for d in calls)
    with sqlite3.connect(str(tmp_path / "course.db")) as c2:
        assert c2.execute("SELECT COUNT(*) FROM margin_total").fetchone()[0] > 0


def test_screen_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "DB_PATH", tmp_path / "course.db")
    import price_cache
    pdb = tmp_path / "cache.db"
    monkeypatch.setattr(price_cache, "DB_PATH", pdb)
    price_cache.init_price_db()
    days = [date(2026, 9, 1) + timedelta(days=k) for k in range(60)]
    days = [d for d in days if d.weekday() < 5]
    c = cc.get_conn()
    pc = sqlite3.connect(str(pdb))
    # 1111：融資 2000 張都在 100 元買，最後 5 天一路跌到 75 → 上市 125%（< 140 → 入選）
    # 2222：上櫃，只跌到 90 → 150%（不入選）；3333：餘額太少（100 張）不算；沒有官方總數 → 不校正
    for k, d in enumerate(days):
        ds = d.isoformat()
        for sid, mk, bal in (("1111", "twse", 2000), ("2222", "tpex", 2000), ("3333", "twse", 100)):
            px = ([100.0] * (len(days) - 5) + ([96.0, 93.0, 91.0, 90.0, 90.0] if sid == "2222" else [93.0, 87.0, 81.0, 76.0, 75.0]))[k]
            buy = 200 if 0 < k < len(days) - 5 else 0
            c.execute("INSERT INTO margin_flow VALUES (?,?,?,?,?,?,?,?,?,?)", (ds, sid, mk, "名" + sid, buy, buy, 0, bal, bal, 0))
            pc.execute("INSERT INTO price_daily VALUES (?,?,?,?,?,?,?,?)", (d.strftime("%Y%m%d"), sid, px, px, px, px, 5e6, "名" + sid))
    c.commit()
    pc.commit()
    c.close()
    pc.close()
    asof, est = MM.compute(min_lots=300)
    assert asof == days[-1].isoformat() and set(est) == {"1111", "2222"}
    assert est["1111"]["avg"] == pytest.approx(100, rel=0.01) and est["1111"]["conf"] > 0.9

    def get_df(sid):
        df = price_cache.get_stock_ohlcv(sid, days=120)
        return df if not df.empty else None
    p = {x["key"]: x["default"] for x in cc.CHIP_PARAMS["S_MAINT_LOW"]}
    rows = MM.screen(get_df, {"1111": "甲"}, p)
    assert [r["stock_id"] for r in rows] == ["1111"]
    r = rows[0]
    assert r["name"] == "甲" and r["maint"] == pytest.approx(125, abs=1) and r["market"] == "上市"
    assert r["call_price"] == pytest.approx(78, abs=0.5) and r["to_call_pct"] > 0      # 75 < 追繳價 78 → 已跌破 130%
    assert "已跌破 130% 追繳線" in r["note"]
    rows2 = MM.screen(get_df, None, {**p, "max_maint": 155})
    assert [x["stock_id"] for x in rows2] == ["1111", "2222"]                           # 維持率由低到高
    # run_all 有接上（不重抓資料）
    out = cc.run_all({}, {}, do_refresh=False)
    assert [x["stock_id"] for x in out["S_MAINT_LOW"]] == ["1111"] and "S_MAINT_LOW" not in cc.last_errors


def test_strategy_is_registered_everywhere():
    import scanner
    assert "S_MAINT_LOW" in scanner.STRATEGIES and "S_MAINT_LOW" in scanner.STRATEGY_PARAMS_SCHEMA
    assert "S_MAINT_LOW" in cc.CHIP_SHORT                     # 不加做多的品質分
    html = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard.html"), encoding="utf-8").read()
    for frag in ("data-s=\"S_MAINT_LOW\"", "'S_MAINT_LOW']", "S_MAINT_LOW: [['估計維持率'", "S_MAINT_LOW: '🩸 融資維持率偏低'"):
        assert frag in html


def test_set_strategy_results(monkeypatch):
    import yahoo_price as yp
    saved = []
    monkeypatch.setattr(yp, "_save_scan_cache", lambda r: saved.append(r))
    monkeypatch.setitem(yp._scan_status, "results", {"S1": [1]})
    yp.set_strategy_results("S_MAINT_LOW", [{"stock_id": "1111"}])
    assert yp._scan_status["results"]["S_MAINT_LOW"] == [{"stock_id": "1111"}] and saved[-1]["S1"] == [1]


def test_gap_days_are_not_corporate_actions():
    """中間缺價 3 天、收盤 100 → 75（4 天各跌 7%，合理）：不能當成減資把成本跟著調低；真的減資（×2）還是要抓到"""
    rows = _rows([(0, 0, 0, 1000, 0)] * 5)
    px = {"2026-06-01": (100, 100, 100), "2026-06-05": (75, 75, 75)}
    e = MM.estimate(rows, px)
    assert e["adj"] == 0 and e["avg"] == pytest.approx(100)
    rows2 = _rows([(0, 0, 0, 1000, 0)] * 2) + [("2026-06-03", 0, 0, 0, 500, 500, 0)]
    e2 = MM.estimate(rows2, {"2026-06-01": (100, 100, 100), "2026-06-03": (190, 190, 190)})
    assert e2["adj"] == 1


@pytest.fixture(autouse=True)
def _clear_caches():
    MM._ALL.clear()
    MM._CACHE.clear()
    MM._MKT_CACHE.clear()
    yield


def _seed(tmp_path, monkeypatch):
    """1111（上市）、2222（上櫃）融資各 2000 張在 100 元買、最後跌到 75；
    官方融資金額：上市＝100 元 × 6 成（校正 1）、上櫃＝再打 9 折（估計比官方多 → 校正 0.9）"""
    monkeypatch.setattr(cc, "DB_PATH", tmp_path / "course.db")
    import price_cache
    pdb = tmp_path / "cache.db"
    monkeypatch.setattr(price_cache, "DB_PATH", pdb)
    price_cache.init_price_db()
    MM._CACHE.clear()
    MM._MKT_CACHE.clear()
    days = [d for d in (date(2026, 9, 1) + timedelta(days=k) for k in range(60)) if d.weekday() < 5]
    c = cc.get_conn()
    pc = sqlite3.connect(str(pdb))
    for k, d in enumerate(days):
        ds, px = d.isoformat(), ([100.0] * (len(days) - 5) + [93.0, 87.0, 81.0, 76.0, 75.0])[k]
        for sid, mk in (("1111", "twse"), ("2222", "tpex")):
            buy = 200 if 0 < k < len(days) - 5 else 0
            c.execute("INSERT INTO margin_flow VALUES (?,?,?,?,?,?,?,?,?,?)", (ds, sid, mk, "名" + sid, buy, buy, 0, 2000, 2000, 0))
            pc.execute("INSERT INTO price_daily VALUES (?,?,?,?,?,?,?,?)", (d.strftime("%Y%m%d"), sid, px, px, px, px, 5e6, "名" + sid))
            f = 0.6 if mk == "twse" else 0.6 * 0.9
            c.execute("INSERT INTO margin_total VALUES (?,?,?,?,?,?,?,?)", (ds, mk, 2000, 2000 * 100 * f, buy, buy * 100 * f, 0, 0))
    c.commit()
    pc.commit()
    c.close()
    pc.close()
    return days


def test_estimate_many_and_one(tmp_path, monkeypatch):
    days = _seed(tmp_path, monkeypatch)
    many = MM.estimate_many(["1111", "2222", "9999"], {"1111": 72.0})
    assert set(many) == {"1111", "2222"}
    a = many["1111"]
    assert a["maint"] == pytest.approx(120, abs=0.5) and a["level"] == "call" and a["close"] == 72     # 用傳進來的現價
    assert a["call_price"] == pytest.approx(78, abs=0.3) and a["to_call_pct"] > 0
    assert MM.calib() == {"twse": 1.0, "tpex": 0.9}
    assert many["2222"]["maint"] == pytest.approx(75 / 54 * 100, abs=0.5) and many["2222"]["level"] == "low"   # 75 ÷（100×0.6×0.9）
    assert many["2222"]["calib"] == 0.9
    one = MM.estimate_one("1111")
    assert one["maint"] == pytest.approx(125, abs=0.5) and one["date"] == days[-1].isoformat()
    assert len(one["series"]) == min(60, len(days)) and one["series"][-1]["maint"] == pytest.approx(125, abs=0.5)
    assert one["series"][0]["maint"] == pytest.approx(166.7, abs=0.5)                                    # 買在 100、收 100
    assert MM.estimate_one("9999") is None


def test_market_maint_uses_official_amount(tmp_path, monkeypatch):
    days = _seed(tmp_path, monkeypatch)
    mt = MM.market_maint()
    assert mt["ok"] and mt["date"] == days[-1].isoformat()
    assert mt["twse"] == pytest.approx(125, abs=0.1) and mt["tpex"] == pytest.approx(150000 / 108000 * 100, abs=0.1)
    # 整體＝（2000×75＋2000×75）÷ 官方（120,000＋108,000 仟元）＝ 個股校正後加起來
    assert mt["all"] == pytest.approx(300000 / 228000 * 100, abs=0.1) and mt["amt_yi"] == pytest.approx(228000 / 1e5, abs=0.05)
    assert mt["series"][0]["twse"] == pytest.approx(166.7, abs=0.1) and mt["low60"] == mt["all"]


def test_verdict_and_ai_mention_low_maintenance():
    """深度分析：維持率偏低 → 評價的提醒第一行（不計分）；AI 圓桌拿得到維持率"""
    import numpy as np
    import deep_ai
    import deep_verdict as DV
    c = np.geomspace(100, 60, 300)
    df = pd.DataFrame({"date": pd.bdate_range("2025-01-02", periods=300).strftime("%Y%m%d"), "open": c, "high": c * 1.01,
                       "low": c * 0.99, "close": c, "volume": np.full(300, 5000.0)})
    row = DV.tech_series(df).iloc[-1]
    mt = {"maint": 125.0, "bal": 2000, "cost": 100.0, "call_price": 78.0, "to_call_pct": -3.8, "level": "low", "market": "上市",
          "lev": 0.6, "conf": 95, "chg5": -50}
    v = DV.verdict(row, chip={"maint": mt})
    assert v["ok"] and v["notes"][0].startswith("🩸 融資維持率（估）125%") and "再跌 3.8%" in v["notes"][0]
    v_ok = DV.verdict(row, chip={"maint": {**mt, "maint": 170.0, "level": "ok"}})
    assert not any("融資維持率" in n for n in v_ok["notes"])
    assert v["score"] == v_ok["score"]                          # 不計分
    txt = deep_ai._data_block({"stock_id": "1111", "name": "甲", "chip": {"maint": mt}}, [])
    assert "融資維持率（估計）125%" in txt and "追繳價（130%）78 元" in txt
