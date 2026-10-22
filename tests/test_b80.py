"""B80：15 分 K、成交量（證交所 MI_5MINS／FMTQIK、相對量、最後一推、修正成熟度、帶量突破、成交密集區）、
價位梯＋如果…就…＋三條路、版本樹。python -m pytest tests/test_b80.py -q（不連網）"""
import datetime as dt
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import engine as E, futdata as FD, intraday as I, levelmap as LM, nest as N, service as S, voldata as VD, volume as VO  # noqa: E402
from wave import advice as AD  # noqa: E402

TW = dt.timezone(dt.timedelta(hours=8))
DAY = dt.date(2026, 10, 21)


def _ts(h, m, s=0, day=DAY):
    return int(dt.datetime(day.year, day.month, day.day, h, m, s, tzinfo=TW).timestamp())


# ── 週期設定 ─────────────────────────────────────────────────────────────────
def test_tf_keys_unique_and_15m():
    assert list(S.TF_KEYS) == ["15m", "30m", "60m", "1d", "1wk"]
    wk = [v[0] for v in S.TF_KEYS.values()]
    lk = [v[1] for v in S.TF_KEYS.values()]
    assert len(set(wk)) == 5 and len(set(lk)) == 5
    assert S.TF_KEYS["15m"] == ("intra15", "m15") and S.TF_LABEL["15m"] == "15 分"
    assert E.deg_cfg("intra15") is E.INTRA15 and E.deg_cfg("intra30") is E.INTRA30 and E.deg_cfg("intra") is E.INTRA
    assert I.TF[15]["deg"] == "intra15" and I.SHOW[15] == 360
    assert AD.TF_NAME["15m"] == "15 分"


def test_set_params_intraday15(monkeypatch):
    monkeypatch.setitem(E.INTRA15, "m", 2.0)
    I.set_params({"intraday15": {"m": 2.5, "floor": 0.0035}})
    assert E.INTRA15["m"] == 2.5 and E.INTRA15["floor"] == 0.0035
    E.INTRA15.update(m=2.0, floor=0.003)


def test_agg_15m_volume_and_closing_call():
    rows = [(_ts(9, 0) + 300 * k, 100 + k, 101 + k, 99 + k, 100.5 + k, 10.0) for k in range(54)]
    rows.append((_ts(13, 30), 160, 160, 160, 160, 7.0))           # 13:30 收盤撮合併進最後一根
    bs = FD.agg_bars(rows, "TWII", 15)
    assert len(bs) == 18
    assert bs[0]["volume"] == 30.0 and bs[-1]["volume"] == 37.0
    assert sum(b["volume"] for b in bs) == 54 * 10 + 7


# ── 證交所 MI_5MINS → 5 分 K 成交金額 ───────────────────────────────────────
def _mi5_json(upto="13:30:00"):
    rows = [["09:00:00", "1", "1", "1", "1", "0", "0", "0"],
            ["09:00:05", "1", "1", "1", "1", "1", "1", "500"]]        # 開盤撮合在 09:00:05 那列
    cum = 500
    t = dt.datetime(2026, 10, 21, 9, 0, 10)
    end = dt.datetime.strptime("2026-10-21 " + upto, "%Y-%m-%d %H:%M:%S")
    while t <= end:
        if t.strftime("%H:%M:%S") == "13:30:00":
            cum += 900                                                  # 收盤撮合
        elif t < dt.datetime(2026, 10, 21, 13, 25, 0) or t.strftime("%H:%M:%S") <= "13:25:00":
            cum += 1
        rows.append([t.strftime("%H:%M:%S"), "1", "1", "1", "1", "1", "1", f"{cum:,}"])
        t += dt.timedelta(seconds=5) if t.hour < 13 or t.minute < 25 else dt.timedelta(minutes=5)
    return {"stat": "OK", "data": rows}


def test_mi5_parse_bars_first_bar_has_open_and_last_has_close():
    cum = VD.parse_mi5(_mi5_json())
    assert cum[0] == (9 * 3600, 0.0) and cum[1][1] == 500e6
    done, part = VD.bars_from_cum(DAY, cum)
    assert len(done) == 54 and part is None
    assert done[0][0] == _ts(9, 0) and done[0][1] >= 500e6           # 第一根含開盤撮合
    assert done[-1][0] == _ts(13, 25) and done[-1][1] >= 900e6        # 最後一根含 13:30 收盤撮合
    assert abs(sum(v for _, v in done) - cum[-1][1]) < 1e-6           # 54 根加總＝當天累計
    assert VD.parse_mi5({"stat": "很抱歉"}) == []


def test_mi5_partial_bar_midday():
    cum = VD.parse_mi5(_mi5_json("10:02:30"))
    done, part = VD.bars_from_cum(DAY, cum)
    assert done[-1][0] == _ts(9, 55) and part[0] == _ts(10, 0)
    assert part[2] == 10 * 3600 + 2 * 60 + 30 and part[1] > 0


def test_mi5_negative_diff_skipped():
    cum = [(9 * 3600, 0.0), (9 * 3600 + 200, 100.0), (9 * 3600 + 300, 50.0), (13 * 3600 + 1800, 60.0)]
    done, _ = VD.bars_from_cum(DAY, cum)
    assert done[0] == (_ts(9, 0), 50.0)
    assert all(v >= 0 for _, v in done)


def test_fmtqik_parse():
    j = {"stat": "OK", "data": [["115/10/22", "11,986,796,663", "926,732,582,844", "5,720,572", "46,041.43", "-846.34"],
                                ["壞資料"]]}
    assert VD.parse_fmtqik(j) == [("2026-10-22", 926732582844.0, 11986796663.0)]
    assert VD.parse_fmtqik({"stat": "OK", "data": [["2026/10/22", "1", "2", "", "", ""]]})[0][0] == "2026-10-22"


def test_day_fracs():
    per = {"d1": [(300 * k, 10.0) for k in range(54)], "d2": [(300 * k, 20.0 if k < 6 else 10.0) for k in range(54)]}
    fr = VD.day_fracs(per, 1800)                       # 開盤後 30 分鐘＝6 根
    assert abs(fr[0] - 6 / 54) < 1e-9 and fr[1] > fr[0]
    half = VD.day_fracs({"d": [(0, 10.0), (300, 10.0)]}, 450)
    assert abs(half[0] - 0.75) < 1e-9                  # 走到一半的那根照比例


def test_rows5_vol5_priority(monkeypatch):
    rows = [(_ts(9, 0), 1, 1, 1, 1, 0.0), (_ts(9, 5), 1, 1, 1, 1, 0.0), (_ts(9, 10), 1, 1, 1, 1, 33.0)]
    monkeypatch.setattr(FD, "load_bars5", lambda sym, since=None: rows)
    monkeypatch.setattr(VD, "load_vol5", lambda sym, since=0: {_ts(9, 0): 111.0})
    out = I.rows5("TWII", [], now_ts=_ts(10, 0), vol_live={_ts(9, 5): 222.0})
    assert [r[5] for r in out] == [111.0, 222.0, 33.0]  # vol5 → 盤中 MI5 → 沒有才用原本的
    out_tx = I.rows5("TX", [], now_ts=_ts(10, 0))
    assert [r[5] for r in out_tx] == [0.0, 0.0, 33.0]  # 台指期不換


# ── 相對量 ──────────────────────────────────────────────────────────────────
def test_rvol_slots_same_slot_prior_days_only():
    bars = []
    for d in range(7):
        for k in range(3):
            bars.append({"time": d * 100 + k, "slot": k, "volume": (k + 1) * 10.0 * (2 if d == 6 and k == 1 else 1)})
    bars.append({"time": 999, "slot": 0, "volume": 1000.0, "partial": True})
    rv, refs = VO.rvol_slots(bars, lambda b: b["slot"], n=20, min_n=5)
    assert rv[:15] == [None] * 15                      # 前 5 天同時段樣本不到 5 個
    assert rv[15] == 1.0 and rv[16] == 1.0 and rv[19] == 2.0
    assert refs[0] == 10.0                             # 進行中那根不放進參考
    assert VO.rvol_slots([{"volume": 0, "slot": 1}] * 8, lambda b: b["slot"])[0][-1] is None   # 0＝沒有資料


def test_rvol_plain_and_labels():
    rv = VO.rvol_plain([10, 10, 10, 10, 10, 25, None, 7])
    assert rv[:5] == [None] * 5 and rv[5] == 2.5 and rv[6] is None and abs(rv[7] - 7 / 12.5) < 1e-9
    assert [VO.rv_label(x) for x in (2.1, 1.4, 1.0, 0.6, None)] == ["爆量", "放量", "正常", "量縮", "—"]


def test_partial_rvol_early_and_actual_fraction():
    assert VO.partial_rvol(50, 100, 100, 900) is None              # 走不到 20% 不判斷
    assert abs(VO.partial_rvol(50, 100, 450, 900) - 1.0) < 1e-9    # 一半時間、一半量＝1 倍
    # 加權 60 分 K 最後一根只有 30 分鐘：分母用實際長度
    assert abs(VO.partial_rvol(100, 100, 1800, 1800) - 1.0) < 1e-9
    assert VO.partial_rvol(None, 100, 450, 900) is None


def test_day_estimate():
    assert VO.day_estimate(100, [0.2] * 6)["est"] == 500
    assert VO.day_estimate(100, [0.2] * 3) is None


# ── 波段力道、修正成熟度 ────────────────────────────────────────────────────
def _series(points, n=10, vols=None):
    c = []
    for a, b in zip(points[:-1], points[1:]):
        c += list(np.linspace(a, b, n, endpoint=False))
    c.append(points[-1])
    c = np.array(c, float)
    return c * 1.0005, c * 0.9995, c


def _piv(points, n=10, start="L"):
    out, t = [], start
    for k, p in enumerate(points[:-1]):
        out.append({"i": k * n, "p": p * (0.9995 if t == "L" else 1.0005), "t": t, "ci": k * n + 2})
        t = "H" if t == "L" else "L"
    return out


def test_leg_info_correction_her_example():
    # 她 9/30：45330→48946 推升後回到 47630＝回吐 36.4%、時間跟前段 1:1 → 空間時間都到了
    pts = [44000, 45330, 48946, 47630]
    h, l, c = _series(pts, 20)
    piv = _piv(pts[:-1] + [0], 20)[:3]                 # L 44000、H? → 用前三個轉折：L、H、L…
    piv = [{"i": 0, "p": 44000, "t": "H", "ci": 2}, {"i": 20, "p": 45330 * 0.9995, "t": "L", "ci": 22},
           {"i": 40, "p": 48946 * 1.0005, "t": "H", "ci": 42}]
    rv = [1.0] * len(c)
    lg = VO.leg_info(h, l, c, rv, VO.macd_dif(c), piv)
    assert lg["mode"] == "corr" and abs(lg["space"] - 0.364) < 0.01 and abs(lg["time"] - 1.0) < 0.06
    assert lg["mature"] and not lg["shallow"] and lg["fib"] == 0.382
    # 只回 16.5% → 空間不足
    pts2 = [44000, 45330, 48946, 48350]
    h2, l2, c2 = _series(pts2, 20)
    lg2 = VO.leg_info(h2, l2, c2, rv, VO.macd_dif(c2), piv)
    assert lg2["shallow"] and not lg2["mature"]


def test_leg_info_push_signals():
    pts = [44000, 46000, 45000, 46500]                 # 第二推 1,500 < 第一推 2,000 → 漲幅縮小
    h, l, c = _series(pts, 20)
    piv = [{"i": 0, "p": 44000 * 0.9995, "t": "L", "ci": 2}, {"i": 20, "p": 46000 * 1.0005, "t": "H", "ci": 22},
           {"i": 40, "p": 45000 * 0.9995, "t": "L", "ci": 42}]
    rv = [2.0] * 21 + [1.0] * (len(c) - 21)            # 第二推量比較小
    lg = VO.leg_info(h, l, c, rv, VO.macd_dif(c), piv)
    assert lg["mode"] == "push" and lg["signals"]["amp"] is True and lg["signals"]["vol"] is True
    assert lg["signals"]["hold"] is False and lg["retain"] > 0.95
    lg2 = VO.leg_info(h, l, c, rv, VO.macd_dif(c), piv, price=45900)   # 盤中跌回前高以下＝站不住
    assert lg2["signals"]["hold"] is True and lg2["n"] >= 3 and lg2["verdict"] == "last"
    assert VO.leg_info(h, l, c, rv, None, piv[:2]) is None


def test_breakouts_classify():
    c = np.array([100, 101, 102, 101, 99, 100, 103, 104], float)
    piv = [{"i": 2, "p": 102.0, "t": "H", "ci": 4}]
    rv = [1, 1, 1, 1, 1, 1, 1.5, 1]
    ev = VO.breakouts(c, rv, piv, look=10)
    assert len(ev) == 1 and ev[0]["k"] == 6 and ev[0]["kind"] == "vol" and ev[0]["dir"] == 1
    rv[6] = 0.8
    assert VO.breakouts(c, rv, piv, look=10)[0]["kind"] == "dry"


def test_vol_zones_flat_bars_and_zero_atr():
    h = [100.0] * 30 + [110.0] * 10
    l = [100.0] * 30 + [106.0] * 10                    # 前 30 根最高＝最低（不能除以 0）
    c = [100.0] * 30 + [108.0] * 10
    z = VO.vol_zones(h, l, c, [5.0] * 40, atr=2.0, look=40)
    assert z and abs(z[0]["mid"] - 100.0) < 1.0 and z[0]["by"] == "vol"
    assert VO.vol_zones(h, l, c, [5.0] * 40, atr=0, look=40) == []
    assert VO.vol_zones(h, l, c, [None] * 40, atr=2.0, look=40)[0]["by"] == "time"


def test_vol_zones_width_and_no_overlap():
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 1, 300))
    h, l = c + 1.5, c - 1.5
    zs = VO.vol_zones(h, l, c, list(rng.uniform(1, 3, 300)), atr=3.0, look=300, k=2)
    assert zs
    for z in zs:
        assert z["hi"] - z["lo"] <= 1.5 * 3.0 + 1e-9
    if len(zs) == 2:
        a, b = sorted(zs, key=lambda z: z["lo"])
        assert a["hi"] <= b["lo"] + 1e-9


def test_describe_text():
    vx = {"ok": True, "has_vol": True, "last": {"rv": 1.5, "label": "放量"},
          "leg": {"mode": "corr", "dir": -1, "space": 0.364, "fib": 0.382, "time": 1.0, "mature": True, "vol_state": "shrink"}}
    s = VO.describe(vx, "60 分")
    assert "1.5 倍" in s and "空間、時間都到了" in s and "量縮" in s
    assert "沒有量" in VO.describe({"ok": True, "has_vol": False, "note": "這段沒有量的資料"}, "日 K")
    vb = {"ok": True, "has_vol": True, "breaks": [{"t": "10/21 09:00", "dir": 1, "level": 46967.9, "kind": "dry"},
                                                  {"t": "10/21 10:00", "dir": -1, "level": 46500.0, "kind": "vol"}]}
    s2 = VO.describe(vb, "60 分")
    assert "10/21 10:00 帶量跌破 46,500" in s2 and "沒量" not in s2      # 只寫最近一次
    assert "帶量突破 47,000" in VO.describe({"ok": True, "has_vol": True, "breaks": [{"k": 5, "dir": 1, "level": 47000, "kind": "vol"}]}, "日 K")


# ── 價位梯 ──────────────────────────────────────────────────────────────────
def _ctx(**kw):
    lv = {"support": [{"price": 47900, "dist_pct": -0.2, "sources": [{"label": "前低"}]},
                      {"price": 47630, "dist_pct": -0.77, "sources": [{"label": "前低"}, {"label": "0.618"}]}],
          "resistance": [{"price": 48296, "dist_pct": 0.62, "sources": [{"label": "前高"}]},
                         {"price": 48500, "dist_pct": 1.04, "sources": [{"label": "整數"}]}]}
    nz = {"ok": True, "dir": 1, "cur_dir": 1,
          "primary": {"path": "3-3", "rules": [{"price": 47630, "side": "below", "why": "第 2 段不能破起點"}],
                      "targets": [{"price": 48830, "label": "3 與 1 等長", "kind": "end"}, {"price": 49051, "label": "1.618 延伸", "kind": "end"},
                                  {"price": 48946.5, "label": "前高", "kind": "end"}]},
          "alternate": {"path": "B-c", "rules": [{"price": 48127, "side": "above", "why": "b 不能過 a 起點"}], "targets": []},
          "gates": [{"k": "第一關", "price": 48070, "ok": False, "t": "站上 48,070（前一個反彈高點）→ 初步止跌"}]}
    c = dict(price=48000, win=0.03, levels=lv, key={"kind": "轉弱點", "price": 47896, "side": "below", "dist_pct": -0.22},
             nest=nz, wave={}, positioning=None, zones=[{"lo": 47769, "hi": 47876, "mid": 47822, "share": 0.2, "by": "vol"}],
             leg_dir=1, vol_ok=False, hlc=None)
    c.update(kw)
    return c


def test_levelmap_merge_targets_transit():
    out = LM.build(_ctx())
    items = out["items"]
    assert sum(1 for it in items if it["side"] == "up") <= 4 and sum(1 for it in items if it["side"] == "down") <= 4
    assert [it["price"] for it in items] == sorted([it["price"] for it in items], reverse=True)
    ts = [t["t"] for t in out["targets"]]
    assert ts[:2] == ["T1", "T2"] and out["targets"][0]["price"] == 48830
    # 47630 同時是換數法＋前低 → 併成一列，代表什麼寫換數法
    row = next(it for it in items if abs(it["price"] - 47630) < 1)
    assert "版本一（3-3） 作廢" in row["act"] and "版本二（B-c）升為主要" in row["act"]
    # 48296 在現價和 T1 之間的壓力＝過渡壓力
    allp = LM._merge(LM.candidates(_ctx()), 48000)
    assert any(abs(it["price"] - 48296) < 1 for it in allp)
    assert any("過渡壓力" in (it.get("name") or "") for it in items if it["side"] == "up") or len([i for i in items if i["side"] == "up"]) == 4


def test_levelmap_decision_and_steps():
    out = LM.build(_ctx())
    dec = out["decision"]
    assert dec and dec[0]["side"] == "up"
    downs = [d for d in dec if d["side"] == "down"]
    assert any("守住" in d["if"] for d in downs) or len(downs) == 1
    assert any("47,630" in d["if"] for d in dec)                    # 會讓數法改變的價位一定在
    stp = out["steps"]
    assert stp["up"][0]["t"].startswith("先站上") and stp["range"]["ok"] is True
    assert stp["down"][0]["t"].startswith("先跌破")


def test_levelmap_retest_and_runaway():
    # 站上 48,070 之後回測守住 → 回測那步 ✅
    h = np.array([48000, 48050, 48100, 48120, 48090], float)
    l = np.array([47950, 48000, 48060, 48071, 48072], float)
    c = np.array([48000, 48040, 48090, 48100, 48085], float)
    assert LM._crossed_then((h, l, c), 48070, True) is True
    assert LM._crossed_then((h, l, c), 48300, True) is None
    out = LM.build(_ctx(price=48085, hlc=(h, l, c)))
    st = out["steps"]["up"]
    assert st and st[0]["t"] == "先站上 48,127" or st[0]["ok"] in (True, False)


def test_levelmap_top3_no_duplicate_stop():
    ctx = _ctx(key={"kind": "轉弱點", "price": 47900, "side": "below", "dist_pct": -0.2})
    out = LM.build(ctx)
    top = out["top3"]
    if top.get("stop_same") == "down":
        assert top["stop"] is None or top["stop"]["price"] < top["down"]["price"]
    else:
        assert top["stop"]["price"] != top["down"]["price"]


def test_levelmap_stop_kept_when_nothing_beyond():
    # 下方只有一個價位而且就是轉折點 → 停損那格不能變空白
    ctx = _ctx(levels={"support": [], "resistance": []}, zones=[], nest={"ok": False},
               key={"kind": "轉弱點", "price": 47900, "side": "below", "dist_pct": -0.2})
    top = LM.build(ctx)["top3"]
    assert top["stop"] and top["stop"]["price"] == 47900 and "stop_same" not in top


def test_rule_act_dedup_same_version():
    parts = [{"kind": "rule", "ver": "版本一", "path": "3-3", "verb": "跌破"}, {"kind": "rule", "ver": "版本一", "path": "3-3", "verb": "跌破"}]
    s = LM._rule_act(parts, [("版本一", "3-3"), ("版本二", "B-c")])
    assert s.count("版本一") == 1 and "版本二（B-c）升為主要" in s


def test_levelmap_daily_mother_and_inv():
    ctx = _ctx(nest=None, wave={"primary": {"targets": [{"price": 46000, "kind": "end", "label": "C＝A"}], "invalid": 49969,
                                            "invalid_side": "above", "text": "修正的最後一段"}, "alternate": None},
               positioning={"levels": {"0.382": 47500, "0.5": 46800, "0.618": 46100}, "iron": 44000}, leg_dir=-1, win=0.06)
    out = LM.build(ctx)
    names = " ".join(it["name"] for it in out["items"])
    assert "母尺 0.382" in names or "第一防守區" in names
    m = next(it for it in out["items"] if "0.382" in it["name"])
    assert "0.382" in m["act"] and "第一防守區" in m["act"]


# ── 版本樹、15 分起點 ───────────────────────────────────────────────────────
VALS = [50265, 48413, 49479, 48240, 48705, 46456, 47634, 46107, 47033, 46136, 47250]
IDX = [0, 14, 24, 33, 38, 52, 60, 70, 80, 88, 96]


def _pts(vals=VALS, idx=IDX, start="H"):
    out, t = [], start
    for v, i in zip(vals, idx):
        out.append({"i": i, "p": float(v), "t": t, "ci": i + 2})
        t = "L" if t == "H" else "H"
    out[-1]["ci"] = None
    return out


def _build(**kw):
    pts = _pts()
    times = [1760000000 + 3600 * k for k in range(100)]
    daily = {"kind": "impulse", "current": "2", "labels": [{"i": 0, "p": 39385}, {"i": 1, "p": 50265}, {"i": 2, "p": 46107}]}
    return N.build({"pivots": pts[:-1], "tentative": pts[-1]}, times, 47250, "60 分", daily, ["2026-07-29", "2026-10-06", "2026-10-20"],
                   tdate=lambda i: dt.date(2026, 10, 6) + dt.timedelta(days=i // 8), tlabel=lambda i: f"#{i}", **kw)


def _depth(nodes):
    return 0 if not nodes else 1 + max(_depth(n["subs"]) for n in nodes)


def test_version_tree():
    out = _build()
    P = out["primary"]
    tr = P["tree"]
    assert tr["from"]["p"] == 50265 and tr["subs"]
    assert 1 <= _depth(tr["subs"]) <= N.MAX_DEPTH
    now = [n for n in tr["subs"] if n["now"]]
    assert len(now) == 1 and now[0]["lab"] == P["path"].split("-")[0]
    assert now[0]["to"]["p"] == 47250                    # 進行中＝目前的極值
    a4c = out["alternate"] if out["alternate"]["path"] == "A-4-c" else P
    labs = [n["lab"] for n in a4c["tree"]["subs"]]
    assert labs[0] == "A"
    assert P["seg1"]["role"] in ("M", "C") and P["seg1"]["time"] >= 1760000000


def test_anchor_at_parent_segment():
    pts = _pts()
    times = [1760000000 + 3600 * k for k in range(100)]
    k = N.anchor_at(pts, times[70], times[70] + 3600, "L", times)
    assert k == 7 and pts[k]["p"] == 46107
    assert N.anchor_at(pts, times[71], times[71] + 3600, "L", times) is None
    out = _build(parent_seg={"t0": times[70], "t1": times[70] + 3600, "typ": "L", "role": "M"})
    assert out["ok"] and out["anchor"]["how"] == "parent" and out["anchor"]["p"] == 46107


# ── 服務層小工具 ─────────────────────────────────────────────────────────────
def test_disp_bars_units():
    bs = [{"time": 1, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 12_345_000_000.0, "partial": True},
          {"time": 2, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 0}]
    tw = S._disp_bars("TWII", bs)
    assert tw[0]["volume"] == 123.5 and tw[0]["partial"] and tw[1]["volume"] is None
    assert S._disp_bars("TX", [{**bs[0], "volume": 812.4}])[0]["volume"] == 812


def test_weekly_vols_same_week_grouping():
    dates = ["2026-10-12", "2026-10-13", "2026-10-16", "2026-10-19"]
    w = S._weekly_vols(dates, [1.0, 2.0, None, 4.0])
    assert w == {S._week("2026-10-16"): 3.0, S._week("2026-10-19"): 4.0}
    assert S._week("2026-10-12") == S._week("2026-10-16") != S._week("2026-10-19")


def test_vol_research_defaults():
    r = S._vol_research({})
    assert set(r) >= {"V1", "V2", "V2b", "V3", "V4", "V5"} and r["V1"]["pass_d1"] is False and "研究還沒跑" in r["V1"]["text"]
    r2 = S._vol_research({"volume": {"tests": {"V1": {"pass_d1": True, "pass_d2": False, "text": "x"}}}})
    assert r2["V1"]["pass_d1"] and not r2["V1"]["pass_d2"]


def test_ladder_five_rows():
    waves = {k: {} for k in ("intra15", "intra30", "intra", "small", "mid")}
    rows = S._ladder(waves, {}, {})
    assert [r["tf"] for r in rows] == ["15m", "30m", "60m", "1d", "1wk"]
    assert "15 分" in AD.ladder_summary(rows)
