"""可轉債資料解析（純函式，方便測試）"""
from __future__ import annotations

import csv
import io
import re
from typing import Optional

_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def num(v) -> Optional[float]:
    s = str(v if v is not None else "").replace(",", "").replace("+", "").strip()
    if s in ("", "-", "--", "---", "X", "除權", "除息"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def ymd(s) -> Optional[str]:
    """20241210 / 115/09/02 / 1150902 → 2024-12-10"""
    s = re.sub(r"\D", "", str(s or ""))
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if len(s) == 7:
        return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:]}"
    return None


def parse_bonds(rows: list) -> list:
    """櫃買 OpenAPI bond_ISSBD5_data（轉(交)換債發行資料）→ 上櫃掛牌中的國內可轉債"""
    out = []
    for x in rows or []:
        code = str(x.get("BondCode") or "").strip()
        sid = str(x.get("IssuerCode") or "").strip()
        if not code or not re.fullmatch(r"[0-9A-Z]{4,6}", sid) or str(x.get("ListingStatus")) != "2":
            continue
        out.append({
            "code": code, "name": str(x.get("ShortName") or "").strip(), "sid": sid,
            "issuer": str(x.get("IssuerName") or "").strip(),
            "issue_date": ymd(x.get("IssueDate")), "maturity_date": ymd(x.get("MaturityDate")),
            "issue_amt": num(x.get("IssueAmount")), "outstanding": num(x.get("OutstandingAmount")),
            "conv_price_issue": num(x.get("Conversion/ExchangePriceAtIssuance")),
            "conv_start": ymd(x.get("Conversion/ExchangePeriodStartDate")),
            "conv_end": ymd(x.get("Conversion/ExchangePeriodEndDate")),
            "put_date": ymd(x.get("PutOptionDate")), "put_price": num(x.get("PutOptionPrice")),
        })
    return out


def parse_quotes_csv(text: str) -> tuple:
    """櫃買 RSta0113（轉(交)換公司債買賣斷交易行情表）CSV → (date, [rows])；只取「等價」列"""
    date = None
    m = re.search(r"日期:(\d{2,3})年(\d{1,2})月(\d{1,2})日", text or "")
    if m:
        date = f"{int(m.group(1)) + 1911}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    out = []
    for r in csv.reader(io.StringIO(text or "")):
        if len(r) < 16 or r[0] != "BODY" or r[3].strip() != "等價":
            continue
        code = r[1].strip()
        if not re.fullmatch(r"[0-9A-Z]{4,7}", code):
            continue
        out.append({"code": code, "name": r[2].strip(), "close": num(r[4]), "chg": num(r[5]),
                    "volume": num(r[10]) or 0.0, "amount": num(r[11]) or 0.0, "avg": num(r[12]), "ref": num(r[13])})
    return date, out


def series_of(code: str, sid: str = "") -> Optional[int]:
    """債券代號＝股票代號＋第幾次發行（11011 → 1；140202 → 2）"""
    code = code or ""
    rest = code[len(sid):] if sid and code.startswith(sid) else code[4:]
    return int(rest) if rest.isdigit() and 0 < len(rest) <= 2 else None


def parse_conv_adjust(subject: str, text: str) -> list:
    """重大訊息「轉換價格（調整）」→ [{series, price}]；海外可轉債不算"""
    if "海外" in (subject or "") or not re.search(r"轉換價格", subject or ""):
        return []
    body = (text or "").replace("\n", "").replace("\r", "").replace(" ", "")
    out = []
    # 「第X次…由新台幣A元調整為新台幣B元」（同一則可能有多次）
    for m in re.finditer(r"第([一二三四五六七八九十0-9]+)次[^。；]{0,60}?轉換價格(?:由|自)(?:每股)?(?:新[臺台]幣)?[0-9,.]+元調整為(?:每股)?(?:新[臺台]幣)?([0-9,.]+)元", body):
        out.append((m.group(1), m.group(2)))
    if not out:
        ms = re.search(r"第([一二三四五六七八九十0-9]+)次", subject or "") or re.search(r"第([一二三四五六七八九十0-9]+)次", body)
        prices = re.findall(r"調整為(?:每股)?(?:新[臺台]幣)?([0-9,.]+)元", body) or \
            re.findall(r"(?:訂定|訂為|定為)轉換價格(?:為)?(?:每股)?(?:新[臺台]幣)?([0-9,.]+)元", body)
        if ms and prices:
            out.append((ms.group(1), prices[-1]))      # 訂價後又因除息調整：取最後一個
    res = []
    for s, p in out:
        n = int(s) if s.isdigit() else _CN.get(s) if len(s) == 1 else (10 + _CN.get(s[-1], 0) if s.startswith("十") else None)
        v = num(p.rstrip("."))
        if n and v and v > 0:
            res.append({"series": n, "price": v})
    return res


def parse_twse_margin(j: dict) -> dict:
    """TWSE rwd MI_MARGN（selectType=ALL）→ {sid: 融券今日餘額（張）}"""
    out = {}
    for t in (j or {}).get("tables") or []:
        f = t.get("fields") or []
        if len(f) < 13 or "代號" not in f[0]:
            continue
        for r in t.get("data") or []:
            v = num(r[12])
            if v is not None:
                out[str(r[0]).strip()] = v
    return out


def parse_tpex_margin(j: dict) -> dict:
    """櫃買 /www/zh-tw/margin/balance → {sid: 券餘額（張）}"""
    out = {}
    for t in (j or {}).get("tables") or []:
        f = t.get("fields") or []
        if "券餘額" not in f:
            continue
        i = f.index("券餘額")
        for r in t.get("data") or []:
            v = num(r[i]) if i < len(r) else None
            if v is not None:
                out[str(r[0]).strip()] = v
    return out


def parse_openapi_margin(rows: list) -> dict:
    """TWSE openapi MI_MARGN / 櫃買 tpex_mainboard_margin_balance → {sid: 融券餘額（張）}"""
    out = {}
    for x in rows or []:
        sid = str(x.get("股票代號") or x.get("SecuritiesCompanyCode") or "").strip()
        v = num(x.get("融券今日餘額") if "融券今日餘額" in x else x.get("ShortSaleBalance"))
        if sid and v is not None:
            out[sid] = v
    return out


def parse_revenue(rows: list) -> dict:
    """t187ap05_L / mopsfin_t187ap05_O → {sid: {ym, yoy, mom, cum_yoy}}"""
    out = {}
    for x in rows or []:
        sid = str(x.get("公司代號") or "").strip()
        if not sid:
            continue
        out[sid] = {"ym": str(x.get("資料年月") or ""), "yoy": num(x.get("營業收入-去年同月增減(%)")),
                    "mom": num(x.get("營業收入-上月比較增減(%)")), "cum_yoy": num(x.get("累計營業收入-前期比較增減(%)"))}
    return out
