"""綜合評價（PLAN-DEEP2 §5）：python -m pytest tests/test_deep_verdict.py -q"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deep_verdict as dv


def _df(close, vol=500.0):
    c = np.asarray(close, float)
    n = len(c)
    return pd.DataFrame({"date": pd.bdate_range("2025-01-02", periods=n).strftime("%Y%m%d"),
                         "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": np.full(n, vol)})


def _row(close, vol=500.0):
    return dv.tech_series(_df(close, vol)).iloc[-1]


UP = list(np.geomspace(20, 100, 300))        # 一路漲：均線多頭、52 週高點、半年 +90%
DOWN = list(np.geomspace(100, 20, 300))


def test_strong_and_weak_buckets():
    raw, parts = dv.tech_raw(_row(UP))
    assert raw == 40 and dv.bucket_of(raw) == "strong"
    assert any("多頭排列" in t for t, _ in parts)
    raw, _ = dv.tech_raw(_row(DOWN))
    assert raw == 0 and dv.bucket_of(raw) == "weak"


def test_bucket_edges():
    assert dv.bucket_of(32) == "strong" and dv.bucket_of(31) == "neutral"
    assert dv.bucket_of(8) == "neutral" and dv.bucket_of(7) == "weak"


def test_tech_series_uses_only_past():
    df = _df(UP + [10.0] * 5)
    full = dv.tech_series(df)
    cut = dv.tech_series(df.iloc[:300])
    pd.testing.assert_series_equal(full.iloc[299], cut.iloc[299], check_names=False)


def test_vol20_tolerates_missing_days():
    df = _df(UP)
    df.loc[295, "volume"] = np.nan
    assert dv.tech_series(df).iloc[-1]["vol20"] == 500


def test_population():
    assert dv.population(500, 50) == "main"
    assert dv.population(79, 416) == "low"          # 4583 台灣精銳
    assert dv.population(20, 50) == "none"
    assert dv.population(5000, 8) == "none"
    assert dv.population(None, 50) == "none"


def test_short_history_gives_no_verdict():
    v = dv.verdict(_row(UP[:100]))
    assert v["ok"] is False and "130" in v["reason"]


LV = {"price": 100.0, "stop": {"price": 92.0}, "target": 110.0, "support": {"price": 95.0},
      "pressure1": {"low": 105.0}, "rr": 1.25}


def test_missing_components_excluded_from_denominator():
    v = dv.verdict(_row(UP), levels=LV)
    assert v["ok"] and v["score"] == 100          # 只有技術 50/50
    keys = {c["key"]: c for c in v["components"]}
    assert keys["chip"]["pts"] is None and keys["fund"]["pts"] is None and keys["sector"]["pts"] is None
    assert v["action"] == "可以做多" and "停損 92" in v["advice"][0] and "目標 110" in v["advice"][0]


def test_weak_tech_never_long_even_if_others_great():
    chip = {"days": 20, "foreign": {"d20": 5000}, "trust": {"d20": 5000, "streak": 5}}
    rev = {"ym": "2026-08", "yoy": 50, "ytd_yoy": 40}
    inc = {"eps": 5, "label": "x"}
    val = {"per": 10, "peer_pe_median": 20, "peer_n": 10}
    sector = {"rank20d": 1, "total": 30, "sector_name": "半導體"}
    v = dv.verdict(_row(DOWN, vol=500), chip=chip, vol_sum=10000, kpct_change=1.0, rev=rev, inc=inc, val=val,
                   sector=sector, levels=LV)
    assert v["bucket"]["key"] == "weak"
    assert v["action"] != "可以做多" and v["action"] != "小量試單"


def test_low_volume_halves_position_and_says_so():
    main = dv.verdict(_row(UP, vol=500), levels=LV)
    low = dv.verdict(_row(UP, vol=80), levels=LV)
    assert low["action"] == "小量試單" and low["bucket"]["pop"] == "low"
    assert abs(low["position_pct"] * 2 - main["position_pct"]) < 0.11
    assert any("低量股" in n for n in low["notes"])


def test_position_pct():
    assert dv.position_pct(100, 92, "main") == round(min(1 / (8 + 0.585) * 100, 25), 1)
    assert dv.position_pct(100, 99, "main") == 25.0          # 上限
    assert dv.position_pct(100, 100, "main") is None         # 停損 ≥ 現價
    assert dv.position_pct(100, 105, "main") is None
    assert dv.position_pct(None, 90, "main") is None


def test_already_below_stop():
    lv = dict(LV, price=90.0)
    v = dv.verdict(_row(UP), levels=lv)
    assert v["action"] == "已跌破停損"
    assert v["position_pct"] is None and not any(x.startswith("部位") for x in v["advice"])


def test_odds_lookup_and_bands():
    assert dv.rr_band(0.3) == "lo" and dv.rr_band(0.5) == "mid" and dv.rr_band(0.99) == "mid" and dv.rr_band(1) == "hi"
    assert dv.rr_band(None) is None and dv.rr_band(0) is None
    o = dv.odds_of("strong", 1.2, "main")
    assert o["target_first"] == dv.ODDS["main"]["strong"]["hi"][0] and o["small"] is False
    assert dv.odds_of("strong", 1.2, "none") is None
    assert dv.odds_of("strong", 1.2, "low")["small"] is True     # n=61


def test_neutral_advice_mentions_levels():
    flat = [100.0] * 300
    v = dv.verdict(_row(flat), levels=LV)
    assert v["bucket"]["key"] in ("neutral", "weak")
    if v["action"] == "觀望":
        assert "105" in v["advice"][0] or "95" in v["advice"][0]


def test_chip_score_ratio_and_streak():
    chip = {"days": 20, "foreign": {"d20": 300}, "trust": {"d20": 0, "streak": -4}}
    pts, mx, parts = dv.chip_score(chip, 10000, None)
    assert mx == 15 and pts == 7 + 0                # 3% 占量 → 7；投信連賣 4 天 → 0；沒有千張大戶 → 不計
    assert dv.chip_score({"error": "x"}, 1, 1) is None
    assert dv.chip_score(None, 1, 1) is None


def test_fund_score_etf_and_partial():
    assert dv.fund_score(None, None, {"etf": True}) is None
    assert dv.fund_score(None, None, None) is None
    pts, mx, _ = dv.fund_score({"ym": "2026-08", "yoy": 23.6, "ytd_yoy": 16.0}, {"eps": 6.81, "label": "q"},
                               {"per": 30.88, "peer_pe_median": 22.0, "peer_n": 30})
    assert mx == 15 and pts == 6 + 3 + 3 + 2      # 4583：YoY+23.6、累計+16、EPS 正、PE 是中位數 1.4 倍


def test_sector_score():
    assert dv.sector_score({"rank20d": 1, "total": 30})[0] == 15
    assert dv.sector_score({"rank20d": 30, "total": 30})[0] == 0
    assert dv.sector_score({"rank20d": 3, "total": 30, "stale": True}) is None
    assert dv.sector_score({"rank20d": 1, "total": 1}) is None          # 產業資料不完整
    assert dv.sector_score(None) is None


def test_grade_thresholds():
    assert dv.grade_of(70)[0] == "偏多" and dv.grade_of(69)[0] == "略偏多"
    assert dv.grade_of(45)[0] == "中性" and dv.grade_of(29)[0] == "偏空"


def test_held_position_line():
    lv = dict(LV, entry={"kind": "cost", "price": 95.0, "pnl_pct": 5.3})
    v = dv.verdict(_row(UP), levels=lv)
    assert any("成本 95" in x for x in v["advice"])


def test_volume_in_shares_is_converted():
    df = _df(UP, vol=500.0)
    df.loc[:279, "volume"] = 500_000.0            # 舊列存成「股」
    assert abs(dv.tech_series(df).iloc[-1]["vol20"] - 500) < 1e-6
    assert abs(dv.tech_series(df).iloc[-25]["vol20"] - 500) < 1e-6


def test_odds_include_avg_and_net():
    o = dv.odds_of("strong", 0.3, "main")
    assert o["band"] == "lo" and o["avg"] == dv.ODDS["main"]["strong"]["lo"][3]
    assert abs(o["net"] - (o["avg"] - dv.ROUND_TRIP_COST)) < 0.011


def test_near_target_warning_and_next_pressure():
    lv = {"price": 100.0, "stop": {"price": 88.0}, "target": 103.0, "target_kind": "pressure1",
          "pressure1": {"low": 103.0}, "pressure2": {"low": 112.0}, "support": {"price": 97.0}, "rr": 0.25}
    v = dv.verdict(_row(UP), levels=lv)
    assert v["action"] == "等突破或拉回"                          # 目標太近：方向偏多但不追價
    assert v["advice"][0].startswith("要做多的話：")
    assert any(x.startswith("部位") for x in v["advice"])
    assert any("下一關 112" in x for x in v["advice"])
    assert any("不必追價" in x for x in v["advice"])            # strong lo 扣成本 < 0.5、hi 好很多


def test_neutral_needs_70_for_long():
    # 原始 30 分（中性上緣）：站上 60 日線 4＋60 日線上彎 6＋DIF 6＋52 週 65% 7＋半年 +12% 7
    row = {"n": 300, "close": 100.0, "bull": False, "above60": True, "ma60_up": True, "dif_pos": True,
           "pos52": 0.65, "r120": 0.12, "vol20": 500.0}
    raw, _ = dv.tech_raw(row)
    assert raw == 30 and dv.bucket_of(raw) == "neutral"
    weak_chip = {"days": 20, "foreign": {"d20": -600}, "trust": {"d20": 0, "streak": -3}}
    v = dv.verdict(row, chip=weak_chip, vol_sum=10000, levels=LV)
    assert v["score"] < 55 and v["action"] == "觀望"
    v = dv.verdict(row, levels=LV)                                  # 只有技術 38/50 → 76 分
    assert v["score"] >= 70 and v["action"] in ("可以做多", "等突破或拉回")
    assert any("技術只是中性" in x for x in v["advice"])
    mid_chip = {"days": 20, "foreign": {"d20": 0}, "trust": {"d20": 0, "streak": 0}}
    v = dv.verdict(row, chip=mid_chip, vol_sum=10000, kpct_change=0.0,
                   rev={"ym": "2026-08", "yoy": 5, "ytd_yoy": 5}, levels=LV)
    if 55 <= v["score"] < 70:
        assert v["action"] == "觀望偏多" and "站上壓力 105" in v["advice"][0]
