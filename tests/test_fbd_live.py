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


def _hist(depth=4.0, k=8, vol=1000.0):
    """上漲 100 根（MA10 > MA60）→ 回檔 k 根跌破 MA10（到昨天）"""
    c = list(np.linspace(50, 100, 100)) + [100 - depth * (j + 1) / k for j in range(k)]
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
    F._STATE.update(day=None, hist={}, names={}, cands=0, checked=None, sec=None, hits={}, seen={}, final=False, error=None)
    sent = []
    hist = {"1111": _hist(), "2222": _hist(), "3333": _hist(vol=100.0)}         # 3333 量太小，不是候選
    load = lambda day: (hist, {"1111": "甲", "2222": "乙", "3333": "丙"})
    return {"conn": conn, "sent": sent, "hist": hist, "load": load,
            "send": lambda t: sent.append(t) or True}


def test_synthetic_history_really_triggers_sfbd():
    h = _hist()
    up = pd.concat([h, pd.DataFrame([_bar(h, 1.06, 1000.0)])], ignore_index=True)
    flat = pd.concat([h, pd.DataFrame([_bar(h, 1.0, 1000.0)])], ignore_index=True)
    assert screen_sfbd({"T": up}, {"T": ""}) and not screen_sfbd({"T": flat}, {"T": ""})


def test_candidates_filter():
    hist = {"1111": _hist(), "3333": _hist(vol=100.0), "4444": _hist().head(40)}
    up = _hist(depth=-5)                                                     # 一路漲：昨天收在 MA10 上 → 不是候選
    hist["5555"] = up
    assert list(F.candidates(hist, {})) == ["1111"]


def test_tick_pushes_new_once_and_partial_volume(env):
    h = env["hist"]["1111"]
    # 盤中累計量只有 50 張（< min_vol_lots 300），傳進去會用前 20 日均量 1000 → 照樣成立
    assert not screen_sfbd({"T": pd.concat([h, pd.DataFrame([_bar(h, 1.06, 50.0)])], ignore_index=True)}, {"T": ""})
    q = {"1111": _bar(h, 1.06, 50.0), "2222": _bar(h, 1.0, 50.0)}
    r = F.tick(datetime(2026, 10, 15, 9, 30), quotes_fn=lambda ids, d: q, load_hist_fn=env["load"], params={},
               send_fn=env["send"])
    assert [x["stock_id"] for x in r["new"]] == ["1111"] and len(env["sent"]) == 1
    assert "1111 甲" in env["sent"][0] and "盤中假跌破" in env["sent"][0]
    assert F._STATE["cands"] == 2                                           # 3333 量太小
    F.tick(datetime(2026, 10, 15, 9, 35), quotes_fn=lambda ids, d: q, load_hist_fn=env["load"], params={},
           send_fn=env["send"])
    assert len(env["sent"]) == 1                                            # 同一檔一天只推一次
    F._STATE.update(seen={})                                                # 程式重啟：push_log 還在 → 不重推
    F.tick(datetime(2026, 10, 15, 9, 40), quotes_fn=lambda ids, d: q, load_hist_fn=env["load"], params={},
           send_fn=env["send"])
    assert len(env["sent"]) == 1


def test_final_list_at_1310(env):
    h = env["hist"]["1111"]
    q1 = {"1111": _bar(h, 1.06), "2222": _bar(h, 1.0)}
    F.tick(datetime(2026, 10, 15, 10, 0), quotes_fn=lambda ids, d: q1, load_hist_fn=env["load"], params={},
           send_fn=env["send"])
    q2 = {"1111": _bar(h, 1.0), "2222": _bar(h, 1.06)}                       # 1111 掉回去、2222 新出現
    r = F.tick(datetime(2026, 10, 15, 13, 10), quotes_fn=lambda ids, d: q2, load_hist_fn=env["load"], params={},
               send_fn=env["send"])
    assert len(env["sent"]) == 2
    final = env["sent"][1]
    assert "收盤前還成立" in final and "2222 乙" in final and "🆕" in final
    assert "現在不成立：1111 甲" in final
    assert [x["stock_id"] for x in r["final"]["hits"]] == ["2222"]
    F.tick(datetime(2026, 10, 15, 13, 15), quotes_fn=lambda ids, d: q2, load_hist_fn=env["load"], params={},
           send_fn=env["send"])
    assert len(env["sent"]) == 2                                            # 13:10 清單只發一次


def test_final_runs_at_1315_if_1310_missed_and_not_after_1325(env):
    h = env["hist"]["1111"]
    q = {"1111": _bar(h, 1.06)}
    F.tick(datetime(2026, 10, 15, 13, 15), quotes_fn=lambda ids, d: q, load_hist_fn=env["load"], params={},
           send_fn=env["send"])
    assert len(env["sent"]) == 1 and "收盤前還成立" in env["sent"][0]
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
