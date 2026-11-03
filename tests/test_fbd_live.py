"""B72 盤中假跌破（fbd_live）：用假歷史＋假報價，不連網、暫存 DB
python -m pytest tests/test_fbd_live.py -q"""
import os
import sqlite3
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fbd_live as F  # noqa: E402
from scanner import screen_sfbd  # noqa: E402

DAY = "20261015"


def _hist(depth=4.0, k=8, vol=1000.0, amp=2.0):
    """上漲 100 根（MA10 > MA60；B91：加振幅 amp 的鋸齒＝有波段高低點，高點、低點都墊高）→ 回檔 k 根跌破 MA10（到昨天）
    amp=2、depth=4 → 日線低不破低、高過高；amp=1.5、depth=6 → 回檔跌破前低（結構不合格）；amp=0 → 沒有波段點"""
    wig = amp * np.sin(np.arange(100) * 2 * np.pi / 14)
    c = list(np.linspace(50, 100, 100) + wig) + [100 + wig[-1] - depth * (j + 1) / k for j in range(k)]
    dates = pd.bdate_range("2026-04-01", periods=len(c)).strftime("%Y%m%d")
    a = np.array(c)
    return pd.DataFrame({"date": dates, "open": a, "high": a * 1.01, "low": a * 0.99, "close": a, "volume": vol})


def _bar(df, mult, vol=300.0):
    last = float(df["close"].iloc[-1])
    return {"date": DAY, "open": last, "high": last * mult * 1.01, "low": last * 0.99, "close": round(last * mult, 2),
            "volume": vol}


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "t.db"

    def conn():
        c = sqlite3.connect(str(path))
        c.row_factory = sqlite3.Row
        return c
    c = conn()
    c.execute("CREATE TABLE push_log (id INTEGER PRIMARY KEY, stock_id TEXT, signal_emoji TEXT, signal_title TEXT, pushed_at TEXT, ok INT)")
    c.commit(); c.close()
    monkeypatch.setattr(F, "_conn", conn)
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    import tail_track
    monkeypatch.setattr(tail_track, "DB_PATH", tmp_path / "tail.db")
    tail_track.init_db(tmp_path / "tail.db", seed=False)
    F._STATE.update(day=None, hist={}, names={}, cands=0, checked=None, sec=None, hits={}, seen={}, final=False, error=None, mkt=None)
    sent = []
    hist = {"1111": _hist(), "2222": _hist(), "3333": _hist(vol=100.0),          # 3333 量太小，不是候選
            "4444": _hist(depth=6.0, amp=1.5)}                                   # 4444 日線回檔跌破前低（結構不合格）
    load = lambda day: (hist, {"1111": "甲", "2222": "乙", "3333": "丙", "4444": "丁"})
    mkt = {"snap": {"o": 100, "h": 101, "l": 98, "x": 99, "y": 100}, "src": "live", "checked_at": "13:15", "error": None,
           "feats": {"x": 43210.0, "chg": -0.012, "M2": "開高走低", "M4": "空頭", "M5": "都跌破"},
           "verdict": {"label": "neutral", "rules": []}}
    return {"conn": conn, "sent": sent, "hist": hist, "load": load, "mkt": lambda now: mkt, "tail": tail_track,
            "send": lambda t: sent.append(t) or True}


def test_synthetic_history_really_triggers_sfbd():
    h = _hist()
    up = pd.concat([h, pd.DataFrame([_bar(h, 1.06, 1000.0)])], ignore_index=True)
    flat = pd.concat([h, pd.DataFrame([_bar(h, 1.0, 1000.0)])], ignore_index=True)
    assert screen_sfbd({"T": up}, {"T": ""}) and not screen_sfbd({"T": flat}, {"T": ""})


def test_fixture_structures():
    """B91：測試用走勢的日線結構跟名字一樣（合格／跌破前低／沒有波段點）"""
    import tail_market as TM
    for h, ok, why in ((_hist(), True, ""), (_hist(depth=6.0, amp=1.5), False, "低點跌破前低"), (_hist(amp=0), False, "波段點不夠")):
        up = pd.concat([h, pd.DataFrame([_bar(h, 1.06, 1000.0)])], ignore_index=True)
        assert screen_sfbd({"T": up}, {"T": ""})
        st = TM.struct_check(up["high"].to_numpy(), up["low"].to_numpy())
        assert st["ok"] is ok and st["reason"] == why


def test_candidates_filter():
    hist = {"1111": _hist(), "3333": _hist(vol=100.0), "4444": _hist().head(40)}
    up = _hist(depth=-5)                                                     # 一路漲：昨天收在 MA10 上 → 不是候選
    hist["5555"] = up
    assert list(F.candidates(hist, {})) == ["1111"]


def test_tick_pushes_new_once_and_partial_volume(env):
    h = env["hist"]["1111"]
    # 盤中累計量只有 50 張（< min_vol_lots 300），傳進去會用前 20 日均量 1000 → 照樣成立
    assert not screen_sfbd({"T": pd.concat([h, pd.DataFrame([_bar(h, 1.06, 50.0)])], ignore_index=True)}, {"T": ""})
    h4 = env["hist"]["4444"]
    q = {"1111": _bar(h, 1.06, 50.0), "2222": _bar(h, 1.0, 50.0), "4444": _bar(h4, 1.06, 50.0)}
    r = F.tick(datetime(2026, 10, 15, 9, 30), quotes_fn=lambda ids, d: q, load_hist_fn=env["load"], params={},
               send_fn=env["send"])
    assert [x["stock_id"] for x in r["new"]] == ["1111"] and len(env["sent"]) == 1      # 4444 成立但結構不合格 → 不推
    assert "1111 甲" in env["sent"][0] and "盤中假跌破" in env["sent"][0] and "4444" not in env["sent"][0]
    assert r["hits"] == 2 and F._STATE["hits"]["4444"]["struct_ok"] is False
    assert F._STATE["cands"] == 3                                           # 3333 量太小
    F.tick(datetime(2026, 10, 15, 9, 35), quotes_fn=lambda ids, d: q, load_hist_fn=env["load"], params={},
           send_fn=env["send"])
    assert len(env["sent"]) == 1                                            # 同一檔一天只推一次
    F._STATE.update(seen={})                                                # 程式重啟：push_log 還在 → 不重推
    F.tick(datetime(2026, 10, 15, 9, 40), quotes_fn=lambda ids, d: q, load_hist_fn=env["load"], params={},
           send_fn=env["send"])
    assert len(env["sent"]) == 1


def test_final_list_at_1315(env):
    h, h4 = env["hist"]["1111"], env["hist"]["4444"]
    q1 = {"1111": _bar(h, 1.06), "2222": _bar(h, 1.0)}
    F.tick(datetime(2026, 10, 15, 10, 0), quotes_fn=lambda ids, d: q1, load_hist_fn=env["load"], params={},
           send_fn=env["send"], market_fn=env["mkt"])
    q2 = {"1111": _bar(h, 1.0), "2222": _bar(h, 1.06), "4444": _bar(h4, 1.06)}  # 1111 掉回去、2222 新出現、4444 結構不合格
    r = F.tick(datetime(2026, 10, 15, 13, 10), quotes_fn=lambda ids, d: q2, load_hist_fn=env["load"], params={},
               send_fn=env["send"], market_fn=env["mkt"])
    assert r["final"] is None and len(env["sent"]) == 2 and "盤中假跌破" in env["sent"][1]   # B91：13:10 還不是清單時間
    r = F.tick(datetime(2026, 10, 15, 13, 15), quotes_fn=lambda ids, d: q2, load_hist_fn=env["load"], params={},
               send_fn=env["send"], market_fn=env["mkt"])
    assert len(env["sent"]) == 3
    final = env["sent"][2]
    assert "13:15 還成立" in final and "2222 乙" in final and "（早上已通知）" in final
    assert "大盤 13:15 43,210（-1.20%）開高走低｜日線空頭｜月線、季線都跌破" in final
    assert "🚫 不計入" in final and "4444 丁" in final
    assert "現在不成立：1111 甲" in final
    assert [x["stock_id"] for x in r["final"]["hits"]] == ["2222"] and [x["stock_id"] for x in r["final"]["ng"]] == ["4444"]
    # 尾盤追蹤：兩檔都加進去（結構不合格的也記錄、struct_ok=0），大盤存 tail_mkt
    with sqlite3.connect(str(env["tail"].DB_PATH)) as c:
        rows = dict(c.execute("SELECT stock_id, struct_ok FROM tail_track WHERE entry_date='2026-10-15'").fetchall())
        assert rows == {"2222": 1, "4444": 0}
        assert c.execute("SELECT src, verdict FROM tail_mkt WHERE date='2026-10-15'").fetchone() == ("live", "neutral")
    F.tick(datetime(2026, 10, 15, 13, 20), quotes_fn=lambda ids, d: q2, load_hist_fn=env["load"], params={},
           send_fn=env["send"], market_fn=env["mkt"])
    assert len(env["sent"]) == 3                                            # 13:15 清單只發一次


def test_final_market_sources_both_fail_still_sends(env, monkeypatch):
    """B91：MIS、鉅亨都丟例外 → 清單照發、大盤行寫抓不到、不當掉"""
    import wave.data as WD
    import wave.futdata as FD

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(WD, "live_taiex", boom)
    monkeypatch.setattr(FD, "fetch_cnyes_quote", boom)
    m = F.market_snapshot(datetime(2026, 10, 15, 13, 15))
    assert m["snap"] is None and m["feats"] is None and m["verdict"]["label"] == "nodata" and "鉅亨" in m["error"]
    h = env["hist"]["1111"]
    r = F.tick(datetime(2026, 10, 15, 13, 15), quotes_fn=lambda ids, d: {"1111": _bar(h, 1.06)}, load_hist_fn=env["load"],
               params={}, send_fn=env["send"])
    assert len(env["sent"]) == 1 and "大盤 13:15 抓不到" in env["sent"][0] and "1111 甲" in env["sent"][0]
    assert r["final"]["mkt"]["feats"] is None
    # market_fn 自己丟例外也一樣
    F._STATE.update(day=None)
    r = F.tick(datetime(2026, 10, 16, 13, 15), quotes_fn=lambda ids, d: {"1111": _bar(h, 1.06)}, load_hist_fn=env["load"],
               params={}, send_fn=env["send"], market_fn=boom)
    assert len(env["sent"]) == 2 and "抓不到" in env["sent"][1]


def test_market_lines_with_research(monkeypatch):
    import tail_market as TM
    rule = {"family": "M4", "family_name": "大盤日線結構", "bucket": "空頭", "side": "bad", "pass": True,
            "oos": {"n": 120, "win": 0.18, "mean": -0.031}}
    monkeypatch.setattr(TM, "load_research", lambda path=None: {"rules": [rule]})
    f = {"x": 43210.0, "chg": -0.012, "M2": "開高走低", "M4": "空頭", "M5": "都跌破"}
    lines = F.market_lines({"feats": f, "verdict": TM.verdict(f, {"rules": [rule]})})
    assert "比較差 ⚠" in lines[1] and "大盤日線結構＝空頭" in lines[1] and "樣本外勝率 18%" in lines[1] and "-3.1%" in lines[1]
    f2 = {**f, "M4": "多頭"}
    assert F.market_lines({"feats": f2, "verdict": TM.verdict(f2, {"rules": [rule]})})[1] == "研究：今天的盤勢沒有落在比較好或比較差的格子"
    monkeypatch.setattr(TM, "load_research", lambda path=None: {"rules": [{**rule, "pass": False}]})
    assert "沒找到明顯" in F.market_lines({"feats": f2, "verdict": {"label": "neutral", "rules": []}})[1]
    yrs = {str(y): {"n": 30, "mean": m} for y, m in zip(range(2021, 2027), (-.01, -.02, .03, -.01, -.02, -.01))}
    fam = {"M4": {"buckets": {"盤整": {"years": yrs}, "多頭": {"years": {"2021": {"n": 5, "mean": 1}}}}}}
    monkeypatch.setattr(TM, "load_research", lambda path=None: {"rules": [], "families": fam, "generated": "x"})
    f3 = {**f, "M4": "盤整"}
    out = F.market_lines({"feats": f3, "verdict": {"label": "neutral", "rules": []}})
    assert out[-1] == "參考（事後統計、沒通過檢定）：大盤日線盤整時，這招過去 6 年有 5 年平均是賠的"
    assert len(F.market_lines({"feats": f2, "verdict": {"label": "neutral", "rules": []}})) == 2     # 多頭只有 1 年（筆數也不夠）→ 不加


def test_final_runs_at_1320_if_1315_missed_and_not_after_1325(env):
    h = env["hist"]["1111"]
    q = {"1111": _bar(h, 1.06)}
    F.tick(datetime(2026, 10, 15, 13, 20), quotes_fn=lambda ids, d: q, load_hist_fn=env["load"], params={},
           send_fn=env["send"], market_fn=env["mkt"])
    assert len(env["sent"]) == 1 and "13:15 還成立" in env["sent"][0]
    F._STATE.update(day=None)
    assert F.tick(datetime(2026, 10, 16, 13, 30), quotes_fn=lambda ids, d: q, load_hist_fn=env["load"],
                  params={}, send_fn=env["send"])["hits"] == 0


def test_no_quotes_or_holiday_no_push(env):
    calls = []

    def fail(ids, d):
        calls.append(len(ids))
        raise RuntimeError("cnyes down")
    r = F.tick(datetime(2026, 10, 15, 10, 0), quotes_fn=fail, load_hist_fn=env["load"], params={}, send_fn=env["send"])
    assert r["new"] == [] and env["sent"] == [] and len(calls) == 2         # 失敗重試一次、不丟例外
    r = F.tick(datetime(2026, 10, 15, 10, 5), quotes_fn=lambda ids, d: {}, load_hist_fn=env["load"], params={},
               send_fn=env["send"])                                         # 休市：報價日期不是今天＝空
    assert r["new"] == [] and env["sent"] == []
    assert F.tick(datetime(2026, 10, 18, 10, 0), quotes_fn=fail, load_hist_fn=env["load"])["hits"] == 0   # 星期六


def test_telegram_failure_retried_next_tick(env):
    h = env["hist"]["1111"]
    q = {"1111": _bar(h, 1.06)}
    out = []
    F.tick(datetime(2026, 10, 15, 9, 30), quotes_fn=lambda ids, d: q, load_hist_fn=env["load"], params={},
           send_fn=lambda t: out.append(t) and False)
    assert len(out) == 1
    F.tick(datetime(2026, 10, 15, 9, 35), quotes_fn=lambda ids, d: q, load_hist_fn=env["load"], params={},
           send_fn=env["send"])
    assert len(env["sent"]) == 1                                            # 上次失敗 → 這次再推
    st = F.live_status()
    assert st["checked"] == "09:35" and [x["stock_id"] for x in st["hits"]] == ["1111"]
