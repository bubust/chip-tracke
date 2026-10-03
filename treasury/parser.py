"""
解析 MOPS「庫藏股買回資訊彙總」（t35sc09）的 HTML 表格或另存的 CSV。

不依賴固定欄位順序：先把表格（含 rowspan/colspan 的多列表頭）展開成格子，
再用表頭關鍵字對應欄位，MOPS 調整欄位順序或多一欄也不會解析錯。
"""
from __future__ import annotations

import csv
import io
import re
from html.parser import HTMLParser
from typing import Optional

# ── 表頭關鍵字 → 欄位（依序比對，先比對的先佔用；比例欄要排在股數欄前面）──
_FIELD_RULES = [
    ("stock_id",        lambda h: "公司代號" in h or h == "代號"),
    ("name",            lambda h: "公司名稱" in h or h == "名稱"),
    ("board_date",      lambda h: "決議日" in h),
    ("purpose",         lambda h: "買回目的" in h),
    ("amount_cap",      lambda h: "金額上限" in h),
    ("price_low",       lambda h: "價格區間" in h and "低" in h),
    ("price_high",      lambda h: "價格區間" in h and "高" in h),
    ("price_range",     lambda h: "價格區間" in h),
    ("period_start",    lambda h: "買回期間" in h and "起" in h),
    ("period_end",      lambda h: "買回期間" in h and "迄" in h),
    ("period",          lambda h: "買回期間" in h),
    ("done_flag",       lambda h: "是否執行完畢" in h or "執行完畢" in h and "註銷" not in h and "原因" not in h),
    ("exec_ratio",      lambda h: "預定買回股數" in h and ("比例" in h or "佔" in h)),
    ("pct_of_capital",  lambda h: "已發行" in h and ("比例" in h or "佔" in h)),
    ("plan_shares",     lambda h: "預定買回股數" in h),
    ("cancelled_shares", lambda h: "註銷" in h or "轉讓" in h and "股數" in h),
    ("bought_amount",   lambda h: "已買回" in h and "金額" in h),
    ("avg_price",       lambda h: "平均" in h and "價" in h),
    ("bought_shares",   lambda h: "已買回股數" in h),
    ("not_done_reason", lambda h: "原因" in h),
]

_SID_RE = re.compile(r"^[0-9A-Z]{4,6}$")


class _TableGrid(HTMLParser):
    """收集所有 <table>，每個 table 為 list[row]，row 為 list[(text, rowspan, colspan, is_th)]"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list = []
        self._stack: list = []      # 巢狀 table
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            def _int(v):
                try:
                    return max(1, int(str(v).strip()))
                except Exception:
                    return 1
            self._cell = {"text": [], "rs": _int(a.get("rowspan", 1)), "cs": _int(a.get("colspan", 1)),
                          "th": tag == "th"}
        elif tag == "br" and self._cell is not None:
            self._cell["text"].append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            txt = re.sub(r"\s+", " ", "".join(self._cell["text"])).strip()
            self._row.append((txt, self._cell["rs"], self._cell["cs"], self._cell["th"]))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._stack:
            if self._row:
                self._stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"].append(data)


def _expand(rows) -> list:
    """把 rowspan/colspan 展開成矩形格子；回傳 list[list[(text, is_th)]]"""
    grid: list = []
    pending: dict = {}          # (r, c) → (text, th) 由上方 rowspan 佔用
    for r, row in enumerate(rows):
        out = []
        c = 0
        cells = list(row)
        while cells or (r, c) in pending:
            if (r, c) in pending:
                out.append(pending.pop((r, c)))
                c += 1
                continue
            text, rs, cs, th = cells.pop(0)
            for k in range(cs):
                out.append((text, th))
                for dr in range(1, rs):
                    pending[(r + dr, c + k)] = (text, th)
            c += cs
        grid.append(out)
    return grid


def _map_headers(headers: list) -> dict:
    """headers：每欄合併後的表頭文字 → {field: col_index}"""
    used, out = set(), {}
    for field, pred in _FIELD_RULES:
        for i, h in enumerate(headers):
            if i in used or not h:
                continue
            if pred(h.replace(" ", "")):
                out[field] = i
                used.add(i)
                break
    return out


def _headers_of(rows: list, width: int) -> list:
    headers = []
    for c in range(width):
        parts = []
        for r in rows:
            t = r[c] if c < len(r) else ""
            if t and (not parts or parts[-1] != t):
                parts.append(t)
        headers.append("".join(parts))
    return headers


def _grid_to_records(grid: list) -> list:
    """grid：list[list[text]]。找含「代號」的表頭列（最多 3 列表頭），之後「公司代號」欄像股票代號的列是資料"""
    h0 = next((i for i, row in enumerate(grid) if any("代號" in x for x in row)), None)
    if h0 is None:
        return []
    width = max(len(r) for r in grid)
    for k in range(h0, min(h0 + 3, len(grid) - 1)):
        cols = _map_headers(_headers_of(grid[h0:k + 1], width))
        sc = cols.get("stock_id")
        if sc is None or "board_date" not in cols:
            continue
        nxt = grid[k + 1]
        if sc < len(nxt) and _SID_RE.match(nxt[sc].strip()):
            break
    else:
        return []
    recs = []
    for row in grid[k + 1:]:
        if sc >= len(row) or not _SID_RE.match(row[sc].strip()):
            continue
        rec = {f: (row[i].strip() if i < len(row) else "") for f, i in cols.items()}
        n = normalize(rec)
        if n:
            recs.append(n)
    return recs


def parse_html(html: str) -> list:
    p = _TableGrid()
    p.feed(html)
    out: list = []
    for t in p.tables:
        grid = [[txt for txt, _ in row] for row in _expand(t)]
        out.extend(_grid_to_records(grid))
    return _dedupe(out)


def parse_csv(text: str) -> list:
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))]
    rows = [r for r in rows if any(r)]
    return _dedupe(_grid_to_records(rows))


def parse_any(raw: bytes) -> list:
    """匯入用：自動判斷編碼（UTF-8 / Big5）與格式（HTML / CSV）"""
    text = None
    for enc in ("utf-8-sig", "cp950", "big5hkscs"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    if text.lstrip().startswith("["):          # treasury_sync.py 推上來的 JSON（已正規化）
        return _from_json(text)
    if "<table" in text.lower():
        return parse_html(text)
    return parse_csv(text)


_JSON_FIELDS = ("stock_id", "name", "market", "board_date", "purpose", "amount_cap", "plan_shares",
                "price_low", "price_high", "period_start", "period_end", "done", "bought_shares",
                "cancelled_shares", "exec_ratio", "bought_amount", "avg_price", "pct_of_capital",
                "not_done_reason")


def _from_json(text: str) -> list:
    import json
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out = []
    for r in data if isinstance(data, list) else []:
        if not isinstance(r, dict):
            continue
        sid, bd = str(r.get("stock_id", "")).strip(), roc_to_iso(str(r.get("board_date", "")))
        if not _SID_RE.match(sid) or not bd:
            continue
        rec = {k: r.get(k) for k in _JSON_FIELDS}
        rec.update(stock_id=sid, board_date=bd,
                   period_start=roc_to_iso(str(r.get("period_start") or "")),
                   period_end=roc_to_iso(str(r.get("period_end") or "")))
        for k in ("amount_cap", "plan_shares", "price_low", "price_high", "bought_shares",
                  "cancelled_shares", "exec_ratio", "bought_amount", "avg_price", "pct_of_capital"):
            rec[k] = to_num(rec[k])
        rec["done"] = r.get("done") if r.get("done") in (0, 1) else None
        for k in ("name", "market", "purpose", "not_done_reason"):
            rec[k] = str(rec[k] or "").strip()
        rec["purpose"] = purpose_text(rec["purpose"])
        out.append(rec)
    return _dedupe(out)


# ── 正規化 ────────────────────────────────────────────────────────────────────

def roc_to_iso(s: str) -> Optional[str]:
    """'113/05/10'、'1130510'、'2024/05/10'、'2024-05-10' → '2024-05-10'"""
    if not s:
        return None
    s = s.strip()
    m = re.match(r"^(\d{2,4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{3})(\d{2})(\d{2})$", s) or re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
        if not m:
            return None
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 1911:
        y += 1911
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def to_num(s) -> Optional[float]:
    if s is None:
        return None
    s = str(s).replace(",", "").replace("%", "").replace("元", "").replace("股", "").strip()
    if s in ("", "-", "--", "—", "NA", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _split_range(s: str):
    parts = re.split(r"\s*(?:~|～|至|－|-(?=\s*\d))\s*", s or "")
    parts = [p for p in parts if p.strip()]
    return (parts[0], parts[-1]) if len(parts) >= 2 else (s, "")


# MOPS 買回目的有時只給代碼（證交法 28-2 條第 1 項各款）
PURPOSE_CODES = {
    "1": "轉讓股份予員工",
    "2": "配合附認股權公司債、可轉換公司債或認股權憑證之發行，作為股權轉換之用",
    "3": "為維護公司信用及股東權益所必要而買回，並辦理銷除股份",
}


def purpose_text(p) -> str:
    p = str(p or "").strip()
    return PURPOSE_CODES.get(p.rstrip(".、 "), p)


def normalize(r: dict) -> Optional[dict]:
    sid = (r.get("stock_id") or "").strip()
    bd = roc_to_iso(r.get("board_date", ""))
    if not sid or not bd:
        return None
    lo, hi = r.get("price_low"), r.get("price_high")
    if (lo is None or hi is None) and r.get("price_range"):
        lo, hi = _split_range(r["price_range"])
    ps, pe = r.get("period_start"), r.get("period_end")
    if (ps is None or pe is None) and r.get("period"):
        ps, pe = _split_range(r["period"])
    done_raw = (r.get("done_flag") or "").strip()
    done = 1 if done_raw in ("是", "Y", "y", "已執行完畢", "完畢") else (0 if done_raw else None)
    return {
        "stock_id":        sid,
        "name":            (r.get("name") or "").strip(),
        "board_date":      bd,
        "purpose":         purpose_text(r.get("purpose")),
        "amount_cap":      to_num(r.get("amount_cap")),
        "plan_shares":     to_num(r.get("plan_shares")),
        "price_low":       to_num(lo),
        "price_high":      to_num(hi),
        "period_start":    roc_to_iso(ps or ""),
        "period_end":      roc_to_iso(pe or ""),
        "done":            done,
        "bought_shares":   to_num(r.get("bought_shares")),
        "cancelled_shares": to_num(r.get("cancelled_shares")),
        "exec_ratio":      to_num(r.get("exec_ratio")),
        "bought_amount":   to_num(r.get("bought_amount")),
        "avg_price":       to_num(r.get("avg_price")),
        "pct_of_capital":  to_num(r.get("pct_of_capital")),
        "not_done_reason": (r.get("not_done_reason") or "").strip(),
    }


def _dedupe(recs: list) -> list:
    seen = {}
    for r in recs:
        seen[(r["stock_id"], r["board_date"])] = r
    return list(seen.values())
