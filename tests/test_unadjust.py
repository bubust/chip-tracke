"""價格不還原（B52）：Yahoo 把配股／減資當 split，_parse_yahoo_json 要用 split 事件乘回實際成交價"""
import datetime

from yahoo_price import _parse_yahoo_json, split_factor_fn


def _ts(d):   # 台灣 09:00（UTC 01:00）開盤的 Yahoo 時間戳
    return int(datetime.datetime.strptime(d, "%Y%m%d").replace(tzinfo=datetime.timezone.utc).timestamp()) + 3600


def _yahoo(days, closes, vols, splits=None, adj=None):
    res = {"meta": {}, "timestamp": [_ts(d) for d in days],
           "indicators": {"quote": [{"open": closes, "high": closes, "low": closes, "close": closes, "volume": vols}]}}
    if adj:
        res["indicators"]["adjclose"] = [{"adjclose": adj}]
    if splits:
        res["events"] = {"splits": {str(_ts(d)): {"date": _ts(d), "numerator": n, "denominator": m} for d, n, m in splits}}
    return {"chart": {"result": [res]}}


def test_stock_dividend_multiplied_back():
    # 1815 富喬 2026-09-09 除權（配股 5%）：Yahoo 9/8 給 128.5712，官方 135
    data = _yahoo(["20260903", "20260908", "20260909"], [114.28553009, 128.5712127685547, 126.0],
                  [126554624, 120513217, 69209188], splits=[("20260909", 1050.0017, 1000.0)])
    df = _parse_yahoo_json(data)
    assert list(df["date"]) == ["20260903", "20260908", "20260909"]
    assert list(df["close"]) == [120.0, 135.0, 126.0]
    assert list(df["volume"]) == [120528, 114774, 69209]          # 量也除回去（張）


def test_capital_reduction_reverse_split():
    # 減資一半：Yahoo 把事件前的價格乘 2（還原），splitRatio 1:2 → 乘 0.5 回到實際 10 元
    data = _yahoo(["20260101", "20260102"], [20.0, 21.0], [1000000, 1000000], splits=[("20260102", 1.0, 2.0)])
    df = _parse_yahoo_json(data)
    assert list(df["close"]) == [10.0, 21.0]


def test_no_events_unchanged_and_adjclose_kept():
    data = _yahoo(["20260101", "20260102"], [50.0, 51.0], [1000, 2000], adj=[48.0, 51.0])
    df = _parse_yahoo_json(data, adjusted=True)
    assert list(df["close"]) == [50.0, 51.0]
    assert list(df["adjclose"]) == [48.0, 51.0]
    assert split_factor_fn({"events": {}}) is None


def test_two_splits_multiply():
    f = split_factor_fn({"events": {"splits": {
        "a": {"date": _ts("20250601"), "numerator": 1100, "denominator": 1000},
        "b": {"date": _ts("20260601"), "numerator": 1050, "denominator": 1000}}}})
    assert round(f("20250101"), 6) == round(1.1 * 1.05, 6)
    assert round(f("20250601"), 6) == 1.05          # 事件當天已經是新價格
    assert f("20260601") == 1.0
