"""B67：宏爺 K 線型態／MA20・MA100 格局（deep_patterns）、營收與季報趨勢（deep_data）、AI 解盤（deep_ai）"""
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deep_ai          # noqa: E402
import deep_data as dd  # noqa: E402
import deep_patterns as dp  # noqa: E402


# ── K 線型態（宏爺 classify_kbar 的 16 種）────────────────────────────────────

@pytest.mark.parametrize("ohlc,want", [
    ((100, 108, 99.8, 107.9), "大紅K"),            # 實體 7.9%、影線很短
    ((100, 104.1, 99.9, 104), "中紅K"),
    ((100, 101.1, 99.9, 101), "小紅K"),
    ((108, 108.1, 99.9, 100), "大黑K"),
    ((100, 100.1, 95.9, 96), "中黑K"),
    ((100, 106, 99.9, 101), "倒鎚紅K(墓碑線-上漲)"),
    ((101, 106, 99.9, 100), "倒鎚黑K(墓碑線-下跌)"),
    ((100, 101.1, 95, 101), "紅K鎚子(吊人線-上漲)"),
    ((101, 101.1, 95, 100), "黑K鎚子(吊人線-下跌)"),
    ((100, 103, 97, 101), "紡錘紅K"),
    ((101, 103, 97, 100), "紡錘黑K"),
    ((100, 102, 98, 100.05), "十字線"),
    ((100, 100.05, 96, 100), "T字線"),
    ((100, 104, 99.95, 100), "倒T線"),
    ((100, 100, 100, 100), "一字線"),              # 漲跌停一字
    ((100, 100.2, 100, 100.005), "一字線"),        # 實體極小、整根不到 0.3%
])
def test_kbar_type(ohlc, want):
    assert dp.kbar_type(*ohlc) == want


def test_kbar_type_bad_input():
    assert dp.kbar_type(None, 1, 1, 1) is None
    assert dp.kbar_type(float("nan"), 1, 1, 1) is None
    assert dp.kbar_type(0, 1, 1, 1) is None
    assert all(t in dp.KBAR_MEANING and t in dp.KBAR_STATS for t in dp.KBAR_MEANING)


def test_kbar_chain_change_vs_prev_close():
    df = pd.DataFrame({"date": ["20261007", "20261008", "20261009", "20261013"],
                       "open": [100, 100, 104, 104], "high": [101, 104.1, 106, 104.1],
                       "low": [99, 99.9, 103.9, 99.9], "close": [100, 104, 104.5, 100]})
    ch = dp.kbar_chain(df, 3)
    assert [x["date"] for x in ch] == ["20261008", "20261009", "20261013"]
    assert ch[0]["type"] == "中紅K" and ch[0]["chg"] == 4.0
    assert ch[-1]["type"] == "中黑K" and ch[-1]["chg"] == round((100 / 104.5 - 1) * 100, 2)
    assert dp.kbar_chain(df.head(1), 3)[0]["chg"] is None


# ── 格局 ─────────────────────────────────────────────────────────────────────

def test_trend_box_four_states():
    assert dp.trend_box(110, 100, 105) == "多頭"
    assert dp.trend_box(90, 100, 95) == "空頭"
    assert dp.trend_box(98, 100, 95) == "多箱"      # 月線下、百日線上
    assert dp.trend_box(102, 100, 105) == "空箱"    # 月線上、百日線下
    assert dp.trend_box(100, 100, 100) == "空頭"    # 剛好等於均線算在下面
    assert dp.trend_box(100, float("nan"), 90) is None


def test_trend_info_needs_100_bars():
    c = np.linspace(50, 100, 120)
    df = pd.DataFrame({"close": c})
    t = dp.trend_info(df)
    assert t["box"] == "多頭" and t["ma20_up"] and t["ma100_up"]
    assert t["ma100"] == round(float(c[-100:].mean()), 2)
    assert t["bias20"] == round((c[-1] / c[-20:].mean() - 1) * 100, 2)
    assert dp.trend_info(df.head(99)) is None


def test_stats_and_hongye_claims():
    s = dp.kbar_stat("倒T線", 0.85)                  # 高檔倒T：宏爺說見頂，回測續漲
    assert s["band"] == "hi" and s["claim"] == "見頂" and s["x20"] > s["base_x20"] > 0
    s = dp.kbar_stat("黑K鎚子(吊人線-下跌)", 0.1)     # 低檔鎚子：宏爺說止跌，回測續跌
    assert s["band"] == "lo" and s["claim"] == "止跌" and s["x20"] < s["base_x20"] < 0
    s = dp.kbar_stat("倒T線", 0.5)
    assert s["band"] == "mid" and "claim" not in s
    s = dp.kbar_stat("倒T線", None)
    assert s["band"] == "all" and "base_x20" not in s
    assert dp.kbar_stat("不存在", 0.5) is None
    b = dp.box_stat("多頭", "strong")
    assert b["x20"] == dp.BOX_STATS["多頭"][1] and b["in_bucket"]["x20"] > b["x20"]
    assert "in_bucket" not in dp.box_stat("空頭", "strong")   # 強勢裡空頭樣本太少
    assert dp.box_stat(None) is None


# ── 營收／季報（FinMind）────────────────────────────────────────────────────

def test_revenue_history(monkeypatch):
    rows = [{"revenue_year": y, "revenue_month": m, "revenue": (1e9 if y == 2025 else 1.5e9) + m * 1e7}
            for y in (2025, 2026) for m in range(1, 13) if not (y == 2026 and m > 9)]
    monkeypatch.setattr(dd, "_finmind", lambda ds, sid, start, ttl, fresh=False: rows if ds == "TaiwanStockMonthRevenue" else None)
    r = dd.revenue_history("2330")
    assert len(r["months"]) == 12 and r["months"][-1]["ym"] == "2026-09"
    assert r["months"][-1]["rev"] == round((1.5e9 + 9e7) / 1e8, 2)
    assert r["months"][-1]["yoy"] == round(((1.5e9 + 9e7) / (1e9 + 9e7) - 1) * 100, 1)
    assert r["months"][0]["ym"] == "2025-10" and r["months"][0]["yoy"] is None   # 沒有 2024 年的
    assert r["yoy3"] is not None and r["is_high"] and r["span"] == 21
    assert dd.revenue_history("0050") is None
    monkeypatch.setattr(dd, "_finmind", lambda *a, **k: None)
    assert dd.revenue_history("2330") is None


def test_eps_history_adds_margins(monkeypatch):
    rows = []
    for i, d in enumerate(["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"]):
        rows += [{"date": d, "type": "EPS", "value": 1 + i}, {"date": d, "type": "Revenue", "value": 1e10},
                 {"date": d, "type": "GrossProfit", "value": 4e9 + i * 1e8},
                 {"date": d, "type": "OperatingIncome", "value": 2e9}, {"date": d, "type": "TAX", "value": 1}]
    rows.append({"date": "2026-06-30", "type": "EPS", "value": 9})     # 金融業：只有 EPS
    monkeypatch.setattr(dd, "_finmind", lambda *a, **k: rows)
    e = dd.eps_history("2330")
    q = e["quarters"]
    assert [x["q"] for x in q] == ["2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    assert q[0] == {"q": "2025Q1", "eps": 1, "rev": 100.0, "gm": 40.0, "om": 20.0}
    assert q[-1]["rev"] is None and q[-1]["gm"] is None and q[-1]["eps"] == 9
    assert e["ttm"] == 3 + 4 + 5 + 9 and e["eps_yoy"] == round((9 - 2) / 2 * 100, 1)


def test_chip_30_days_main_and_series(monkeypatch):
    import chip_course as cc
    local = [(f"2026-09-{d:02d}" if d <= 30 else f"2026-10-{d - 30:02d}", 1000.0, -2000.0, 500.0) for d in range(1, 31)]
    monkeypatch.setattr(cc, "inst_series", lambda sid, n=20: local[-n:])
    ms = [(f"2026-09-{d:02d}", 100.0 + d, 5.0) for d in range(1, 31)]
    monkeypatch.setattr(cc, "margin_series", lambda sid, n=6: ms[-n:])
    c = dd.chip("2330")
    assert c["days"] == 20 and c["span"] == 30 and len(c["series"]) == 30 and len(c["daily"]) == 10
    assert c["foreign"]["d20"] == 20 and c["foreign"]["dall"] == 30
    assert c["main"] == {"d1": 0, "d5": -2, "d20": -10, "dall": -15, "streak": -30}
    assert c["margin"]["margin_chg"] == 5.0 and c["margin"]["span"] == 5      # 舊的 5 日變化不變
    assert c["margin"]["margin_chg_all"] == 29.0 and len(c["margin"]["series"]) == 30


# ── AI 解盤 ──────────────────────────────────────────────────────────────────

def _payload():
    return {
        "stock_id": "2330", "name": "台積電", "market": "twse",
        "technical": {"date": "20261013", "close": 2490, "change_pct": -2.35, "volume": 40796, "vol20": 20624,
                      "ma": {"ma10": 2522.5, "ma20": 2477.75, "ma60": 2414.5, "bull": True, "ma60_up": True},
                      "macd": {"dif": 35.3, "dea": 31.5, "osc": 3.8}, "pos52": 0.92, "w52_low": 1305, "w52_high": 2590,
                      "ret": {"5": -0.4, "20": 1, "60": 2, "120": 23}, "tech_raw": 37},
        "levels": {"price": 2490, "target": 2590, "target_method": "前高", "pressure1": {"low": 2505},
                   "support": {"price": 2470, "label": "前低"}, "stop": {"price": 2375, "label": "結構低點"}},
        "verdict": {"ok": True, "score": 82, "grade": "偏多", "action": "可以做多", "summary": "技術強勢",
                    "advice": ["可以做多：停損 2375"], "bucket": {"key": "strong", "label": "強勢",
                                                            "stats": {"x20": 2.2, "up": 48.7, "mdd": -11.0}}},
        "patterns": {"kbars": [{"date": "20261013", "type": "紡錘黑K", "meaning": "多空交戰", "chg": -2.35}],
                     "kbar_stat": dp.kbar_stat("紡錘黑K", 0.92),
                     "trend": {"box": "多頭", "desc": "站上", "ma20": 2477.75, "ma100": 2397.75, "bias20": 0.49,
                               "bias100": 3.85, "ma20_up": True, "ma100_up": True, "stat": dp.box_stat("多頭", "strong")}},
        "chip": {"error": "沒有法人資料"}, "valuation": {"etf": False, "per": 29.4},
        "revenue": None, "income": None, "eps_history": None, "revenue_history": None,
        "sector": {"rank20d": 1, "total": 1, "sector_name": "半導體業"},
        "news": {"items": [{"title": "法說會", "date": "2026-10-12", "publisher": "鉅亨"}]},
    }


def test_build_prompt_contains_system_numbers():
    p = deep_ai.build_prompt(_payload(), [])
    assert "2330 台積電" in p and "## 五、操作策略" in p
    assert "停損 2,375" in p and "目標 2,590" in p and "只能用這些價位" in p
    assert "紡錘黑K" in p and "格局：多頭" in p and "技術強勢又是多頭" in p
    assert "產業強度" not in p                       # 產業家數太少不寫名次
    assert "法人：沒有法人資料" in p


def test_kline_rows_merges_inst():
    df = pd.DataFrame({"date": [f"202610{d:02d}" for d in range(1, 6)], "open": [10] * 5, "high": [11] * 5,
                       "low": [9.5] * 5, "close": [10.5] * 5, "volume": [100] * 5})
    rows = deep_ai.kline_rows(df, {"series": [{"date": "2026-10-05", "foreign": 12, "trust": -3, "dealer": 0}]}, 3)
    assert [r["date"] for r in rows] == ["2026-10-03", "2026-10-04", "2026-10-05"]
    assert rows[-1]["foreign"] == 12 and rows[0]["foreign"] is None and rows[0]["kbar"] == "紡錘紅K"


def test_clean_strips_fence_and_preamble():
    assert deep_ai._clean("```markdown\n## 一、K\nabc\n```") == "## 一、K\nabc"
    assert deep_ai._clean("好的，以下是報告。\n\n## 一、K\nabc") == "## 一、K\nabc"
    assert deep_ai._clean("## 一、K\nabc") == "## 一、K\nabc"


def test_save_latest_keeps_five(tmp_path):
    db = tmp_path / "ai.db"
    for i in range(7):
        deep_ai.save("2330", f"2026100{i}", {"text": f"t{i}", "model": "m", "searched": True,
                                              "sources": [{"title": "x", "uri": "https://a"}], "queries": ["q"]}, db)
    r = deep_ai.latest("2330", db)
    assert r["text"] == "t6" and r["kdate"] == "20261006" and r["sources"][0]["uri"] == "https://a" and r["searched"]
    with deep_ai.get_conn(db) as c:
        assert c.execute("SELECT COUNT(*) FROM deep_ai").fetchone()[0] == 5
    assert deep_ai.latest("2454", db) is None


def test_generate_falls_back_and_daily_limit(monkeypatch):
    from discuss import ai
    calls = []

    def fake_call(model, parts, search, key, timeout):
        calls.append((model, search))
        if search:
            raise RuntimeError("429 quota")
        return {"text": "好的\n## 一、K 線型態\n" + "內容" * 200, "grounding": {}}
    monkeypatch.setattr(ai, "api_key", lambda: "k")
    monkeypatch.setattr(ai, "_call", fake_call)
    monkeypatch.setattr(deep_ai.time, "sleep", lambda s: None)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    out = deep_ai.generate(_payload(), [])
    assert out["text"].startswith("## 一、") and out["searched"] is False and calls[0][1] is True

    monkeypatch.setattr(deep_ai, "DAILY_LIMIT", 1)
    monkeypatch.setattr(deep_ai, "_daily", {"date": deep_ai.tw_today(), "n": 1})
    with pytest.raises(OverflowError):
        deep_ai.start_job("2330", "20261013", _payload(), [])


def test_start_job_reuses_running_job(monkeypatch):
    monkeypatch.setattr(deep_ai, "_jobs", {"abc": {"status": "running", "sid": "2330", "t": deep_ai.time.time()}})
    monkeypatch.setattr(deep_ai, "_daily", {"date": deep_ai.tw_today(), "n": 999})   # 額度滿了也回同一個
    assert deep_ai.start_job("2330", "20261013", _payload(), []) == "abc"


# ── B69：stocks.csv 沒有的股名（ETF、新上市）從官方收盤表補 ─────────────────────

def test_official_names_parse_and_fallback(monkeypatch):
    import yahoo_price as yp
    rows = [{"Code": "0050", "Name": "元大台灣50"}, {"Code": "7855", "Name": "新股"}, {"Code": "", "Name": "x"}]
    m = yp.parse_official_names(rows, "Code", "Name", "twse")
    assert m == {"0050": ("元大台灣50", "twse"), "7855": ("新股", "twse")}
    assert yp.parse_official_names({"error": 1}, "Code", "Name", "twse") == {}
    monkeypatch.setattr(yp, "official_names", lambda max_age=0: m)
    assert yp.stock_name_market("0050") == ("元大台灣50", "twse")
    assert yp.stock_name_market("9999") == ("", None)
    sid, name, mkt = yp.get_stock_list().iloc[0][["stock_id", "stock_name", "type"]]
    assert yp.stock_name_market(sid) == (name, mkt)            # stocks.csv 有的不查官方表
