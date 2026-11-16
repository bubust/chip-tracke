"""B113 核對她 11/16（@fanny55520 台指期）
1. 漲跌的基準是「結算價」不是最後成交價：期交所日行情表 11/16 日盤收 40,885、結算 40,781、漲跌 −2,954（比 11/13 結算 43,839）；
   她的看盤軟體夜盤 41,449 是 ▲668（比 40,781）。網站原本比 40,885（▲564）。鉅亨報價沒有參考價欄位，用「成交 − 漲跌」反推。
2. 她下午：主路徑＝標準五波 5-2-C、目前在 C-3 末端 → C-4 橫盤箱體 → C-5；黃金極限區 40,451～40,894；針尖 40,313～40,451；
   第二層 39,238～39,977（0.786＋前波 60 分平台低點）。「還沒到 0.618 差一點」。
   網站照 60 分轉折切：C-1 42,956、C-2 43,770、C-3 40,714、C-4 41,465、C-5 40,616；C-5 量度 40,311（0.618 倍 C-1）、39,597（等幅）
python -m pytest tests/test_b113_settle_c5.py -q（不連網）"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
import test_b101_neck as T  # noqa: E402
import test_b110_fork as B  # noqa: E402
import test_b111_sessions as S  # noqa: E402
from wave import futdata as FD  # noqa: E402

# 正式站 11/16 21:19 的 60 分轉折：初推裡還有 40,845／39,977；44,824 之後 42,956、43,770、40,714、41,465、（暫定）40,616
SMALL = T.SMALL[:10] + [{"p": 40845, "t": "H"}, {"p": 39977, "t": "L"}] + T.SMALL[10:]
TAIL = B.TAIL + [{"p": 40714, "t": "L"}, {"p": 41465, "t": "H"}, {"p": 40616, "t": "L"}]
FINE = B.FINE + [{"p": 40714, "t": "L"}, {"p": 41465, "t": "H"}, {"p": 40616, "t": "L"}]


def _o(price, tail=TAIL):
    return W.structure(T.BIG, SMALL + tail, price, 43800.0, 43400.0, T.LB, first_leg=T.FIRST, full=17015.0, fine=FINE)


def test_quote_ref_is_price_minus_change():
    q = FD.parse_cnyes_quote({"data": [{"6": 41126.0, "11": 345.0, "56": 0.85, "12": 41484.0, "13": 40616.0, "200007": 1794835147}]})
    assert q["price"] == 41126 and q["ref"] == 40781 and q["chg"] == 345                     # 21:19 的報價：基準 40,781＝11/16 結算價
    assert FD.parse_cnyes_quote({"data": [{"6": 100.0, "21": 98.0, "11": 5.0}]})["ref"] == 98   # 有參考價欄位就用它


def test_changes_use_settlement_price():
    """夜盤比當天日盤結算價、日盤那一行比前一天結算價（跟期交所日行情表、看盤軟體一樣）"""
    rows = (S.ROWS[:-61] + S._sess(S.T(2026, 11, 16, 8, 45), S.T(2026, 11, 16, 13, 45), 43656, 40885)
            + [(S.T(2026, 11, 16, 15, 0) + 300 * k, 40900, 41465, 40860, 41449, 5) for k in range(20)])
    st = {"2026-11-13": 43839.0, "2026-11-16": 40781.0}
    x = FD.session_changes(rows, 41449, S.T(2026, 11, 16, 16, 38), {"2026-11-13": 43834.0}, settles=st)
    c, o = x["cur"], x["other"]
    assert (c["ref"], c["ref_label"], c["chg"], c["chg_pct"]) == (40781.0, "11/16 日盤結算價", 668.0, 1.64)   # 她的軟體：▲668（1.64%）
    assert (o["close"], o["ref"], o["chg"], o["chg_pct"]) == (40885.0, 43839.0, -2954.0, -6.74)             # 期交所：−2,954（−6.74%）
    y = FD.session_changes(rows, 41449, S.T(2026, 11, 16, 16, 38), {"2026-11-13": 43834.0}, settles={"2026-11-13": 43839.0}, live_ref=40781.0)
    assert y["cur"]["ref"] == 40781.0 and y["cur"]["chg"] == 668.0                                          # 日資料還沒進來：用報價反推的
    z = FD.session_changes(rows, 41449, S.T(2026, 11, 16, 16, 38), {"2026-11-13": 43834.0}, live_ref=30000.0)
    assert z["cur"]["ref"] == 40885.0 and z["cur"]["ref_label"] == "11/16 日盤收盤"                          # 報價基準離收盤太遠＝不用；沒有結算價才用收盤
    w = FD.session_changes(rows[:-20], 40885, S.T(2026, 11, 16, 14, 20), {"2026-11-13": 43834.0}, settles=st)
    assert (w["cur"]["label"], w["cur"]["ref"], w["cur"]["chg"]) == ("日盤收", 43839.0, -2954.0) and w["other"]["chg"] == -138.0   # 夜盤 43,701 比 43,839


def test_select_continuous_keeps_day_settlement():
    df = pd.DataFrame([
        {"date": "2026-11-16", "futures_id": "TX", "contract_date": "202611", "open": 43656, "max": 43672, "min": 40714, "close": 40885,
         "volume": 167772, "settlement_price": 40781, "open_interest": 53037, "trading_session": "position"},
        {"date": "2026-11-16", "futures_id": "TX", "contract_date": "202611", "open": 43921, "max": 44423, "min": 42956, "close": 43706,
         "volume": 56132, "settlement_price": 0, "open_interest": 0, "trading_session": "after_market"}])
    out = FD.select_continuous(df)
    day, night = out[out.sess == "day"].iloc[0], out[out.sess == "night"].iloc[0]
    assert day["settle"] == 40781 and day["c"] == 40885 and pd.isna(night["settle"])


def test_tx_1116_standard_five_wave_c_and_second_layer():
    o = _o(41165.0)
    sb = B._sb(o)
    cg = sb["cleg"]
    assert sb["stage"] == "C" and [(x["k"], x["p"]) for x in cg["legs"]] == [(1, 42956), (2, 43770), (3, 40714), (4, 41465), (5, 40616)]
    assert cg["kind"] == "標準五波" and not cg["overlap"] and cg["c1"] == 1868
    assert [int(v + 0.5) for v, _ in cg["t5"]] == [40311, 39597]                             # 她的針尖區下緣 40,313；等幅落在第二層
    z7 = sb["z786"]
    assert (int(z7["lo"] + 0.5), z7["hi"], z7["hit"]) == (39238, 39977, False)               # 她：39,238～39,977
    assert [z["near"] for z in sb["z52"]] == [42165, None, 40715]                            # 多給 39,977 不影響三個大買點
    c = W.plan_card(o, 41165.0, None, 190.0, 464.0)
    assert "標準五波：C-1 42,956、C-2 43,770、C-3 40,714、C-4 41,465、C-5 40,616" in c["pos"][1]
    assert "0.618 的 40,451 還差 165 點" in c["pos"][1] and c["pos"][2].startswith("接下來：五腳走齊：站回 C-4 高點 41,465")
    assert "第二層 39,238～39,977" in c["plays"][1]["t"] and "0.618 倍 C-1 40,311、C-1 等幅 39,597" in c["plays"][1]["t"]
    tl = c["tiles"]
    assert (tl["up"]["price"], tl["down"]["price"], tl["stop"]["price"], tl["stop"]["name"]) == (41302.5, 40715, 41465, "C-4 高點")
    assert "站上 41,465（C-4 高點）＝C 段五腳走完" in c["flip"]
    assert {40616, 39977} <= {v for v, _ in c["watch"]["long"]}                              # 訊號線：C-5 低點、平台低點


def test_c3_end_then_c4_box():
    """她下午發文時（C-3 末端）：C-4 反彈看 C-3 的 0.236～0.382，不能回到 C-1 低點 42,956 上面"""
    o = _o(40885.0, TAIL[:-2])
    cg = B._sb(o)["cleg"]
    assert cg["n"] == 3 and [int(v + 0.5) for v, _ in cg["c4z"]] == [41435, 41881] and cg["t5"] == []
    c = W.plan_card(o, 40885.0, None, 190.0, 464.0)
    assert "C-4 橫盤箱體" in c["pos"][2] and (c["tiles"]["stop"]["price"], c["tiles"]["stop"]["name"]) == (42956, "C-1 低點")
    assert "4 碰到 1" in c["flip"]
    o4 = _o(41400.0, TAIL[:-1])                                                               # 16:30 反彈到 41,465：C-4，後面還有 C-5
    c4 = W.plan_card(o4, 41400.0, None, 190.0, 464.0)
    assert B._sb(o4)["cleg"]["n"] == 4 and "後面還有最後一腳 C-5" in c4["pos"][2] and c4["tiles"]["stop"]["price"] == 42956
