"""08:30 盤前推播的「國際盤」區塊（PLAN-B72 F）：前一晚美股、今早日韓、港陸、匯率、債市原物料、台指期夜盤。
- 來源：Yahoo chart API（日 K 10 天）、期交所 futDataDown（TX 盤後＝夜盤）
- 漲跌＝最新價 vs「最新價那天之前最後一個收盤」（休市自然變成上一個交易日；每組標資料日期）
- 日韓 08:30 已開盤（最新價時間是當地今天）→「昨收 X（昨天漲跌）；今早 HH:MM Y（漲跌）」
- 單一項目抓不到就略過；最新資料超過 7 天的略過；全部抓不到 → 一行「國際盤抓取失敗」"""
import html
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)
TW = timezone(timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
STALE_DAYS = 7

# (群組, 名稱, Yahoo 代號, 小數位, 種類)；種類 fx＝美元兌外幣（漲＝外幣貶）、yield＝殖利率（變動用 bp）
ITEMS = [
    ("us", "道瓊", "^DJI", 0, ""), ("us", "S&P 500", "^GSPC", 0, ""), ("us", "那斯達克", "^IXIC", 0, ""),
    ("us", "費城半導體", "^SOX", 0, ""), ("us", "台積電 ADR", "TSM", 2, ""), ("us", "VIX 恐慌指數", "^VIX", 2, ""),
    ("asia", "🇯🇵 日經 225", "^N225", 0, ""), ("asia", "🇰🇷 韓國 KOSPI", "^KS11", 2, ""),
    ("asia", "🇭🇰 香港恆生", "^HSI", 0, ""), ("asia", "🇨🇳 上證", "000001.SS", 0, ""),
    ("fx", "美元/台幣", "TWD=X", 3, "fx:台幣"), ("fx", "美元/日圓", "JPY=X", 2, "fx:日圓"),
    ("fx", "美元/韓元", "KRW=X", 1, "fx:韓元"), ("fx", "美元/人民幣", "CNY=X", 4, "fx:人民幣"),
    ("fx", "美元指數", "DX-Y.NYB", 2, ""),
    ("other", "美 10 年債殖利率", "^TNX", 3, "yield"), ("other", "WTI 原油", "CL=F", 2, ""), ("other", "黃金", "GC=F", 1, ""),
]
OPEN_NOW = {"^N225", "^KS11", "^HSI", "000001.SS"}       # 亞洲市場：08:30 可能已開盤 → 分昨收／今早


def parse_chart(j: dict, now: datetime | None = None) -> dict | None:
    """Yahoo chart JSON → {price, date, time, prev_close, chg, prev_chg, open_today}；資料不足回 None"""
    try:
        r = j["chart"]["result"][0]
        m = r["meta"]
        off = int(m.get("gmtoffset") or 0)
        price = float(m["regularMarketPrice"])
        t_last = int(m["regularMarketTime"])
    except Exception:
        return None
    loc = lambda ts: datetime.fromtimestamp(ts + off, timezone.utc)
    last_day = loc(t_last).strftime("%Y%m%d")
    closes = (r.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    bars = [(loc(ts).strftime("%Y%m%d"), float(c)) for ts, c in zip(r.get("timestamp") or [], closes) if c is not None]
    before = [c for d, c in bars if d < last_day]
    if not before:
        return None
    prev = before[-1]
    now = now or datetime.now(TW)
    today_local = datetime.fromtimestamp(now.timestamp() + off, timezone.utc).strftime("%Y%m%d")
    return {"price": price, "date": last_day, "time": datetime.fromtimestamp(t_last, TW).strftime("%H:%M"),
            "prev_close": prev, "chg": price / prev - 1 if prev else None,
            "prev_chg": prev / before[-2] - 1 if len(before) >= 2 and before[-2] else None,
            "open_today": last_day == today_local,
            "stale": (now - datetime.fromtimestamp(t_last, TW)).days > STALE_DAYS}


def fetch_yahoo(tickers: list, now: datetime | None = None, get=None) -> dict:
    out = {}
    with httpx.Client(timeout=12, headers=UA, follow_redirects=True) as c:
        g = get or (lambda url, params: c.get(url, params=params).json())
        for t in tickers:
            for attempt in range(2):
                try:
                    q = parse_chart(g(f"https://query1.finance.yahoo.com/v8/finance/chart/{t}",
                                      {"range": "10d", "interval": "1d"}), now)
                    if q:
                        out[t] = q
                        break
                except Exception as e:
                    log.info(f"[global] {t} 第 {attempt + 1} 次失敗：{e}")
                time.sleep(0.5 if get is None else 0)
    return out


def parse_taifex_night(text: str, day: str) -> dict | None:
    """期交所 futDataDown CSV → 指定交易日的 TX「盤後」（夜盤）成交量最大的月份"""
    want = f"{day[:4]}/{day[4:6]}/{day[6:]}"
    best = None
    for line in text.splitlines()[1:]:
        c = [x.strip() for x in line.split(",")]
        if len(c) < 18 or c[0] != want or c[1] != "TX" or c[17] != "盤後" or not (len(c[2]) == 6 and c[2].isdigit()):
            continue
        try:
            close, chg, vol = float(c[6]), float(c[7]), float(c[9])
            pct = float(c[8].rstrip("%")) / 100
        except ValueError:
            continue
        if best is None or vol > best["volume"]:
            best = {"month": c[2], "close": close, "chg_pt": chg, "chg": pct, "volume": vol}
    return best


def fetch_taifex_night(day: str, post=None) -> dict | None:
    d = f"{day[:4]}/{day[4:6]}/{day[6:]}"
    for attempt in range(2):
        try:
            if post:
                text = post(d)
            else:
                r = httpx.post("https://www.taifex.com.tw/cht/3/futDataDown", timeout=20,
                               headers={**UA, "Referer": "https://www.taifex.com.tw/cht/3/futDataDown"},
                               data={"down_type": "1", "commodity_id": "TX", "commodity_id2": "",
                                     "queryStartDate": d, "queryEndDate": d})
                text = r.content.decode("ms950", errors="replace")
            return parse_taifex_night(text, day)
        except Exception as e:
            log.info(f"[global] 期交所夜盤第 {attempt + 1} 次失敗：{e}")
            if not post:
                time.sleep(1)
    return None


def _arrow(x):
    if x is None:
        return ""
    return "🔺" if x > 0.00005 else "🔻" if x < -0.00005 else "➖"


def _num(v, nd):
    return f"{v:,.{nd}f}"


def _pct(x):
    return "" if x is None else f"{_arrow(x)}{abs(x) * 100:.2f}%"


def _md(d):
    return f"{d[4:6]}/{d[6:]}"


def _item_line(name, q, nd, kind) -> str:
    nm = html.escape(name)
    if kind == "yield":
        bp = (q["price"] - q["prev_close"]) * 100
        return f"{nm} {q['price']:.2f}%（{_arrow(bp / 1e4)}{abs(bp):.0f}bp）"
    if kind.startswith("fx:"):
        cur = kind[3:]
        side = "" if not q["chg"] or abs(q["chg"]) < 0.00005 else f"，{cur}{'貶' if q['chg'] > 0 else '升'}"
        return f"{nm} {_num(q['price'], nd)} {_pct(q['chg'])}{side}"
    return f"{nm} {_num(q['price'], nd)} {_pct(q['chg'])}"


def build(quotes: dict, night: dict | None, now: datetime) -> str:
    """組 Telegram HTML 文字"""
    lines = [f"🌏 <b>國際盤</b>　{now:%m/%d %H:%M}（🔺漲 🔻跌）"]
    got = 0

    def use(t):
        q = quotes.get(t)
        if not q or q.get("stale"):
            if q and q.get("stale"):
                log.info(f"[global] {t} 資料超過 {STALE_DAYS} 天（{q['date']}），略過")
            return None
        return q
    us = [(n, use(t), nd, k) for g, n, t, nd, k in ITEMS if g == "us"]
    us = [x for x in us if x[1]]
    if us:
        lines.append(f"🇺🇸 <b>美股</b>（{_md(us[0][1]['date'])} 收）")
        lines += ["　" + _item_line(n, q, nd, k) for n, q, nd, k in us]
        got += len(us)
    if night:
        lines.append(f"🇹🇼 <b>台指期夜盤</b>　{night['close']:,.0f} {_pct(night['chg'])}（{abs(night['chg_pt']):,.0f} 點，對日盤結算價）")
        got += 1
    asia = [(n, t, use(t), nd, k) for g, n, t, nd, k in ITEMS if g == "asia"]
    asia = [x for x in asia if x[2]]
    if asia:
        lines.append("🌏 <b>亞洲</b>")
        for n, t, q, nd, k in asia:
            if t in OPEN_NOW and q["open_today"]:
                y = f"昨收 {_num(q['prev_close'], nd)} {_pct(q['prev_chg'])}；" if q.get("prev_chg") is not None else ""
                lines.append(f"　{html.escape(n)} {y}{'今早' if now.hour < 12 else '今天'} {q['time']} {_num(q['price'], nd)} {_pct(q['chg'])}")
            else:
                lines.append(f"　{_item_line(n, q, nd, k)}（{_md(q['date'])} 收）")
        got += len(asia)
    for g, title in (("fx", "💱 <b>匯率</b>"), ("other", "🛢 <b>債市／原物料</b>")):
        xs = [(n, use(t), nd, k) for gg, n, t, nd, k in ITEMS if gg == g]
        xs = [x for x in xs if x[1]]
        if xs:
            lines.append(title)
            lines += ["　" + _item_line(n, q, nd, k) for n, q, nd, k in xs]
            got += len(xs)
    if not got:
        return "🌏 國際盤抓取失敗（Yahoo／期交所都沒回資料），請自行查看。"
    return "\n".join(lines)


def brief(now: datetime | None = None, yahoo_get=None, taifex_post=None) -> dict:
    now = now or datetime.now(TW)
    quotes = fetch_yahoo([t for _, _, t, _, _ in ITEMS], now, yahoo_get)
    night = fetch_taifex_night(now.strftime("%Y%m%d"), taifex_post)
    return {"text": build(quotes, night, now), "quotes": quotes, "night": night, "at": now.strftime("%Y-%m-%d %H:%M")}
