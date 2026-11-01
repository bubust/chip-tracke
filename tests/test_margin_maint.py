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
    assert MM.maint_of(83, e["avg"], "tpex") == pytest.approx(83 / (95.5 * 0.5) * 100)     # 上櫃融資 5 成
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
            flows.update(twse={"2409": ("友達", 10, 0, 0, 100, 110, 0)}, twse_date=ds, tpex={"3105": ("穩懋", 0, 5, 0, 50, 45, 0)},
                         tpex_date=ds)
        return {}, {}
    monkeypatch.setattr(F, "fetch_margin_day", fake)
    monkeypatch.setattr(MM.time, "sleep", lambda s: None)
    st = MM.backfill(n_days=10)
    assert st["closed"] > 0 and st["failed"] > 0 and st["fetched"] > 0
    calls.clear()
    st2 = MM.backfill(n_days=10)                   # 第二次：只重抓連線失敗的日子
    assert calls and all(d.weekday() == 1 for d in calls)


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
    # 2222：同樣但上櫃（5 成）→ 150%（不入選）；3333：餘額太少（100 張）不算
    for k, d in enumerate(days):
        ds, px = d.isoformat(), ([100.0] * (len(days) - 5) + [93.0, 87.0, 81.0, 76.0, 75.0])[k]
        for sid, mk, bal in (("1111", "twse", 2000), ("2222", "tpex", 2000), ("3333", "twse", 100)):
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
