"""B72 F：08:30 國際盤（假 Yahoo／期交所回應，不連網）＋併進盤前推播"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import global_brief as G  # noqa: E402
import course_live as L  # noqa: E402

TW = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 15, 8, 30, tzinfo=TW)


def _chart(bars, price, t_last, off):
    """bars＝[(UTC datetime, close)]；t_last＝最新價時間（UTC datetime）；off＝交易所 gmtoffset 秒"""
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price, "regularMarketTime": int(t_last.timestamp()),
                                           "gmtoffset": off},
                                  "timestamp": [int(t.timestamp()) for t, _ in bars],
                                  "indicators": {"quote": [{"close": [c for _, c in bars]}]}}]}}


U = timezone.utc
US = _chart([(datetime(2026, 10, 13, 13, 30, tzinfo=U), 100.0), (datetime(2026, 10, 14, 13, 30, tzinfo=U), 102.0)],
            102.0, datetime(2026, 10, 14, 20, 0, tzinfo=U), -4 * 3600)                     # 美股 10/14 收、+2%
JP = _chart([(datetime(2026, 10, 13, 0, 0, tzinfo=U), 200.0), (datetime(2026, 10, 14, 0, 0, tzinfo=U), 190.0),
             (datetime(2026, 10, 15, 0, 0, tzinfo=U), 193.8)],
            193.8, datetime(2026, 10, 15, 0, 25, tzinfo=U), 9 * 3600)                      # 日股今早開盤中
FX = _chart([(datetime(2026, 10, 13, 23, 0, tzinfo=U), 32.0), (datetime(2026, 10, 14, 23, 0, tzinfo=U), None)],
            32.32, datetime(2026, 10, 15, 0, 20, tzinfo=U), 3600)                          # 美元/台幣 +1% → 台幣貶
OLD = _chart([(datetime(2026, 9, 1, 13, 30, tzinfo=U), 10.0), (datetime(2026, 9, 2, 13, 30, tzinfo=U), 11.0)],
             11.0, datetime(2026, 9, 2, 20, 0, tzinfo=U), 0)                               # 超過 7 天 → 略過
TNX = _chart([(datetime(2026, 10, 13, 13, 30, tzinfo=U), 5.20), (datetime(2026, 10, 14, 13, 30, tzinfo=U), 5.25)],
             5.25, datetime(2026, 10, 14, 20, 0, tzinfo=U), -4 * 3600)
NIGHT = ("交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,未沖銷契約數,最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段,價差對單式委託成交量\n"
         "2026/10/15,TX,202610  ,48433,48873,48357,48755,363,0.75%,21801,-,-,48743,48755,50265,39852,,盤後,,\n"
         "2026/10/15,TX,202611  ,48676,49007,48585,48901,294,0.60%,1047,-,-,48897,48916,50440,44435,,盤後,,\n"
         "2026/10/14,TX,202610  ,48789,49200,48650,48792,400,0.83%,44607,48798,105601,48789,48794,50265,39852,,一般,,\n")


def _get(url, params):
    t = url.rsplit("/", 1)[-1]
    if t in ("^DJI", "^GSPC", "^IXIC", "^SOX", "TSM", "^VIX", "^HSI", "000001.SS", "CL=F", "GC=F", "DX-Y.NYB"):
        return US
    if t in ("^N225", "^KS11"):
        return JP
    if t in ("TWD=X", "JPY=X", "KRW=X", "CNY=X"):
        return FX
    if t == "^TNX":
        return TNX
    raise RuntimeError("down")


def test_parse_chart_change_vs_last_close_before_latest_day():
    q = G.parse_chart(US, NOW)
    assert q["date"] == "20261014" and abs(q["chg"] - 0.02) < 1e-9            # 美股不在 OPEN_NOW，不分昨收／今早
    j = G.parse_chart(JP, NOW)
    assert j["open_today"] and j["prev_close"] == 190.0 and abs(j["chg"] - 0.02) < 1e-9 and abs(j["prev_chg"] + 0.05) < 1e-9
    f = G.parse_chart(FX, NOW)                                         # 今天那根 close 是 None → 跟 10/14 的收盤比
    assert f["prev_close"] == 32.0 and abs(f["chg"] - 0.01) < 1e-9
    assert G.parse_chart(OLD, NOW)["stale"]


def test_brief_text_groups_and_arrows():
    r = G.brief(NOW, yahoo_get=_get, taifex_post=lambda d: NIGHT)
    t = r["text"]
    assert "美股</b>（10/14 收）" in t and "道瓊 102 🔺2.00%" in t
    assert "日經 225 昨收 190 🔻5.00%；今早 08:25 194 🔺2.00%" in t
    assert "美元/台幣 32.320 🔺1.00%，台幣貶" in t
    assert "美 10 年債殖利率 5.25%（🔺5bp）" in t
    assert "台指期夜盤</b>　48,755 🔺0.75%（363 點" in t                 # 夜盤取成交量最大的月份
    assert r["night"]["month"] == "202610"


def test_brief_skips_failed_and_stale_items():
    def get(url, params):
        t = url.rsplit("/", 1)[-1]
        if t == "^DJI":
            return OLD
        if t == "^N225":
            return JP
        raise RuntimeError("down")
    t = G.brief(NOW, yahoo_get=get, taifex_post=lambda d: "")["text"]
    assert "道瓊" not in t and "日經 225" in t and "台指期夜盤" not in t and "美股" not in t
    t = G.brief(NOW, yahoo_get=lambda u, p: (_ for _ in ()).throw(RuntimeError("x")), taifex_post=lambda d: "")["text"]
    assert "國際盤抓取失敗" in t


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "c.db"

    def conn():
        c = sqlite3.connect(str(path))
        c.row_factory = sqlite3.Row
        return c
    c = conn()
    c.execute("CREATE TABLE push_log (id INTEGER PRIMARY KEY, stock_id TEXT, signal_emoji TEXT, signal_title TEXT, pushed_at TEXT, ok INT)")
    c.commit(); c.close()
    sent = []

    def fake_send(key, text):
        sent.append((key, text))
        x = conn()
        x.execute("INSERT INTO push_log (stock_id, signal_emoji, signal_title, pushed_at, ok) VALUES ('COURSE','📋',?,?,1)",
                  (key, datetime.now().isoformat()))
        x.commit(); x.close()
        return True
    monkeypatch.setattr(L, "_conn", conn)
    monkeypatch.setattr(L, "_send", fake_send)
    import wave.router as WR       # B74 大盤段：這組測試只看國際盤＋當沖，大盤段固定空的（另外測）
    monkeypatch.setattr(WR, "push_lines", lambda *a, **k: [])
    return sent


def test_premarket_has_global_first_and_daytrade(db):
    today = datetime.now().strftime("%Y%m%d")
    L.save("daytrade", "20261001", {"date": "20261001", "market": {"taiex": 48000, "side": "多"},
                                    "long": [{"stock_id": "2330", "name": "台積電"}], "short": []})
    assert L.push_premarket(lambda: {"text": "🌏 國際盤 測試"})["sent"]
    key, txt = db[0]
    assert key == f"premarket:{today}" and txt.startswith("🌏 國際盤 測試") and "盤前當沖名單" in txt and "2330 台積電" in txt
    assert L.push_premarket(lambda: {"text": "x"}).get("dup")                # 一天一次


def test_premarket_global_fails_daytrade_still_sent(db):
    L.save("daytrade", "20261001", {"date": "20261001", "market": {}, "long": [], "short": []})
    def boom():
        raise RuntimeError("yahoo down")
    assert L.push_premarket(boom)["sent"]
    assert "國際盤抓取失敗" in db[0][1] and "盤前當沖名單" in db[0][1]


def test_premarket_without_daytrade_sends_global_only(db):
    assert L.push_premarket(lambda: {"text": "🌏 只有國際盤"})["sent"]
    assert db[0][1] == "🌏 只有國際盤"


def test_premarket_wave_section_after_global(db, monkeypatch):
    import wave.router as WR
    monkeypatch.setattr(WR, "push_lines", lambda *a, **k: ["🌊 加權 46,293", "短線　撐 45,936／壓 46,974"])
    assert L.push_premarket(lambda: {"text": "🌏 國際盤"})["sent"]
    txt = db[0][1]
    assert txt.index("🌏 國際盤") < txt.index("🌊 加權 46,293") and "撐 45,936" in txt


def test_premarket_wave_failure_ignored(db, monkeypatch):
    import wave.router as WR
    def boom(*a, **k):
        raise RuntimeError("wave down")
    monkeypatch.setattr(WR, "push_lines", boom)
    assert L.push_premarket(lambda: {"text": "🌏 國際盤"})["sent"]
    assert db[0][1] == "🌏 國際盤"
