"""PLAN-B82 研究共用：籌碼／月營收資料對齊到 (交易日 × 股票)，條件（C1～C8、M1～M5、K1～K3），進場時機的成交規則

資料時間點（跟網站 18:00 掃描看得到的一致，不偷看）：
- INST_LAG＝0：三大法人上市／上櫃約 15:00～16:00 公布 → 訊號日 t 用 t 當天
- MARGIN_LAG＝1：融資約 21:00 後才公布 → 訊號日 t 只用 t−1 以前的融資
- 月營收：M 月的資料 M+1 月 15 日起才用（1 月營收＝2 月 20 日起；法定 10 日、遇假日順延，取保守）"""
import gzip, os
import numpy as np
import pandas as pd

INST_LAG = 0
MARGIN_LAG = 1
REV_AVAIL_DAY = 15
REV_AVAIL_DAY_JAN = 20

CHIP = {'C1': '外資當天買超', 'C2': '投信當天買超', 'C3': '外資連買 ≥ 3 天', 'C4': '投信連買 ≥ 2 天',
        'C5': '三大法人 5 日合計買超', 'C6': '三大法人當天合計 ≥ 成交量 10%', 'C7': '融資 5 日減少（前一天比 6 天前少）',
        'C8': '土洋同買（外資、投信當天都買超）'}
REV = {'M1': '最新月營收年增 > 0', 'M2': '最新月營收年增 ≥ 20%', 'M3': '累計營收年增 > 0',
       'M4': '最新月營收創 12 個月新高', 'M5': '連 2 個月營收年增 > 0'}
RES = {'K1': '當天至少 2 個做多策略同時選到', 'K2': '5 個交易日內至少 2 個不同策略', 'K3': '5 個交易日內至少 3 個不同策略'}
ENTRY = {'E1': '突破買：隔天站上訊號 K 最高價（+1 檔）才買，沒碰到不買',
         'E2': '回檔買：3 天內碰到訊號收盤 −2%（要穿過 1 檔）才買',
         'E3': '回檔買：3 天內碰到訊號 K 中間價（最多收盤 −1%，要穿過 1 檔）才買',
         'E4': '等確認：隔天收紅且收盤 > 訊號收盤，第 3 天開盤買'}


# ── 對齊 ─────────────────────────────────────────────────────────────────────
def load_daily(raw_dir, kind, cols, dates, sids):
    """data/{kind}/{d8}.tw.csv.gz＋.tp.csv.gz → {col: T×S float（沒有＝NaN）}、have（T bool：兩個市場都有）"""
    si = {s: i for i, s in enumerate(sids)}
    T, S = len(dates), len(sids)
    out = {c: np.full((T, S), np.nan) for c in cols}
    have = np.zeros(T, bool)
    for t, d8 in enumerate(dates):
        n = 0
        for mk in ('tw', 'tp'):
            f = os.path.join(raw_dir, kind, f'{d8}.{mk}.csv.gz')
            if not os.path.exists(f):
                continue
            df = pd.read_csv(f, dtype={'stock_id': str})
            df = df[df.stock_id.isin(si)]
            j = df.stock_id.map(si).to_numpy()
            for c in cols:
                out[c][t, j] = pd.to_numeric(df[c], errors='coerce').to_numpy(float)
            n += 1
        have[t] = n == 2
    return out, have


def shift_rows(a, lag):
    """a[t] ← a[t−lag]（前 lag 列 NaN）：訊號日 t 只看得到 lag 天前的資料"""
    a = np.asarray(a, float)
    if lag <= 0:
        return a
    b = np.full(a.shape, np.nan)
    b[lag:] = a[:-lag]
    return b


def rev_avail_date(ym: str) -> str:
    """M 月營收（'YYYYMM'）從哪一天起算知道：M+1 月 15 日；1 月營收＝2 月 20 日"""
    y, m = int(ym[:4]), int(ym[4:6])
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    day = REV_AVAIL_DAY_JAN if m == 1 else REV_AVAIL_DAY
    return f'{ny:04d}{nm:02d}{day:02d}'


def prev_ym(ym: str, k: int = 1) -> str:
    y, m = int(ym[:4]), int(ym[4:6]) - k
    while m <= 0:
        m += 12
        y -= 1
    return f'{y:04d}{m:02d}'


def load_revenue(raw_dir):
    """data/rev/{YYYYMM}.csv → {ym: DataFrame(index=stock_id, rev, yoy, cum_yoy)}"""
    out = {}
    d = os.path.join(raw_dir, 'rev')
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith('.csv') and len(f) == 10:
            df = pd.read_csv(os.path.join(d, f), dtype={'stock_id': str}).drop_duplicates('stock_id', keep='last').set_index('stock_id')
            out[f[:6]] = df
    return out


def align_revenue(rev: dict, dates, sids):
    """每個交易日 t：最新「已經可以知道」的月份 M（rev_avail_date(M) ≤ t）的 yoy、cum_yoy、前一個月 yoy、是否創 12 個月新高 → T×S"""
    T, S = len(dates), len(sids)
    yoy, cum, yoy_prev, high12 = (np.full((T, S), np.nan) for _ in range(4))
    months = sorted(rev)
    avail = [(rev_avail_date(m), m) for m in months]
    vec = {}
    for m in months:
        r = rev[m].reindex(sids)
        p = rev.get(prev_ym(m))
        prior = [rev.get(prev_ym(m, k)) for k in range(1, 12)]
        if all(x is not None for x in prior):
            pm = np.vstack([x.reindex(sids)['rev'].to_numpy(float) for x in prior])
            with np.errstate(invalid='ignore'):
                ok = np.isfinite(pm).all(axis=0)
                hi = np.where(ok, r['rev'].to_numpy(float) >= np.nanmax(np.where(np.isfinite(pm), pm, -np.inf), axis=0), np.nan)
        else:
            hi = np.full(S, np.nan)
        vec[m] = (r['yoy'].to_numpy(float), r['cum_yoy'].to_numpy(float),
                  p.reindex(sids)['yoy'].to_numpy(float) if p is not None else np.full(S, np.nan), hi)
    k, cur = 0, None
    for t, d8 in enumerate(dates):
        while k < len(avail) and avail[k][0] <= str(d8):
            cur = avail[k][1]
            k += 1
        if cur is not None:
            yoy[t], cum[t], yoy_prev[t], high12[t] = vec[cur]
    return {'yoy': yoy, 'cum_yoy': cum, 'yoy_prev': yoy_prev, 'high12': high12}


# ── 條件 ─────────────────────────────────────────────────────────────────────
def _gt0(a):
    with np.errstate(invalid='ignore'):
        return np.nan_to_num(a, nan=0.0) > 0


def chip_flags(inst, margin, vol_lots):
    """inst：{foreign, trust, dealer}（股，T×S，已是訊號日能看到的）；margin：{margin}（張，原始，這裡套 MARGIN_LAG）；vol_lots：T×S 張"""
    f, tr, dl = inst['foreign'], inst['trust'], inst['dealer']
    tot = f + tr + dl
    C = {}
    C['C1'] = _gt0(f)
    C['C2'] = _gt0(tr)
    C['C3'] = C['C1'] & _gt0(shift_rows(f, 1)) & _gt0(shift_rows(f, 2))
    C['C4'] = C['C2'] & _gt0(shift_rows(tr, 1))
    s5 = sum(shift_rows(tot, k) for k in range(5))                 # 任一天沒資料 → NaN → 不符合
    C['C5'] = _gt0(s5)
    with np.errstate(invalid='ignore', divide='ignore'):
        C['C6'] = _gt0(tot) & (np.nan_to_num(tot / 1000.0, nan=-1) >= 0.10 * np.nan_to_num(vol_lots, nan=np.inf))
    m = shift_rows(margin['margin'], MARGIN_LAG)
    m6 = shift_rows(m, 5)
    with np.errstate(invalid='ignore'):
        C['C7'] = np.isfinite(m) & np.isfinite(m6) & (m6 > 0) & (np.nan_to_num(m, nan=np.inf) < np.nan_to_num(m6, nan=-np.inf))
    C['C8'] = C['C1'] & C['C2']
    return C


def rev_flags(R):
    with np.errstate(invalid='ignore'):
        y, c, yp, hi = R['yoy'], R['cum_yoy'], R['yoy_prev'], R['high12']
        return {'M1': np.nan_to_num(y, nan=-1e9) > 0, 'M2': np.nan_to_num(y, nan=-1e9) >= 20,
                'M3': np.nan_to_num(c, nan=-1e9) > 0, 'M4': np.nan_to_num(hi, nan=0) == 1,
                'M5': (np.nan_to_num(y, nan=-1e9) > 0) & (np.nan_to_num(yp, nan=-1e9) > 0)}


def res_counts(M: dict):
    """M：{策略: T×S bool}（做多）→ (今天幾個策略, 5 個交易日內幾個不同策略)"""
    today, five = None, None
    for m in M.values():
        r5 = m.copy()
        for k in range(1, 5):
            r5[k:] |= m[:-k]
        today = m.astype(np.int16) if today is None else today + m
        five = r5.astype(np.int16) if five is None else five + r5
    return today, five


def res_flags(M: dict):
    today, five = res_counts(M)
    return {'K1': today >= 2, 'K2': five >= 2, 'K3': five >= 3}


# ── 成交規則（R3）─────────────────────────────────────────────────────────────
def tick(p):
    """台股升降單位"""
    p = np.asarray(p, float)
    return np.select([p < 10, p < 50, p < 100, p < 500, p < 1000], [0.01, 0.05, 0.1, 0.5, 1.0], 5.0)
