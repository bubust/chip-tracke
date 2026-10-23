"""PLAN-B82 研究資料（本機，不碰正式站）：5 年官方日行情＋三大法人＋融資券＋月營收。
證交所、櫃買各一條執行緒（不同主機各自限速），每天每來源一個檔，可中斷續抓：
  data/px/{d8}.tw.csv.gz、{d8}.tp.csv.gz（date,stock_id,name,open,high,low,close,volume(張),chg）；休市 {d8}.closed；data/taiex.csv
  data/inst/{d8}.tw.csv.gz、{d8}.tp.csv.gz（stock_id,foreign,trust,dealer；股）— 從 INST_FROM 起
  data/margin/{d8}.tw.csv.gz、{d8}.tp.csv.gz（stock_id,margin,short；張）— 從 INST_FROM 起
  data/rev/{yyyymm}.csv（stock_id,rev,yoy,cum_yoy；千元、%）— 公開資訊觀測站 t21sc03（上市／上櫃 × 國內／國外）
用法：python fetch_all.py [START] [END]（預設 2021-01-01～今天）；之後 python merge.py 轉成 research/best 的格式"""
import csv, datetime, gzip, os, re, sys, threading, time
import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from chip_course import parse_t86_inst, parse_tpex_insti_daily          # noqa: E402
from cb.parser import parse_twse_margin_both, parse_tpex_margin_both     # noqa: E402

D = os.path.join(HERE, 'data')
for sub in ('px', 'inst', 'margin', 'rev'):
    os.makedirs(os.path.join(D, sub), exist_ok=True)
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'}
START = datetime.date(*map(int, (sys.argv[1] if len(sys.argv) > 1 else '2021-01-01').split('-')))
END = datetime.date(*map(int, (sys.argv[2] if len(sys.argv) > 2 else datetime.date.today().isoformat()).split('-')))
INST_FROM = datetime.date(2021, 8, 2)
GAP = {'tw': 2.2, 'tp': 1.3}
LOCK = threading.Lock()


def log(*a):
    with LOCK:
        print(time.strftime('%H:%M:%S'), *a, flush=True)


def num(v):
    try:
        return float(str(v).replace(',', '').strip())
    except Exception:
        return None


def wgz(path, header, rows):
    with gzip.open(path + '.tmp', 'wt', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    os.replace(path + '.tmp', path)


def px_tw(cl, d8):
    j = cl.get('https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX',
               params={'date': d8, 'type': 'ALLBUT0999', 'response': 'json'}).json()
    if '沒有符合條件' in str(j.get('stat', '')):
        return 'closed', [], None
    rows, taiex = [], None
    for t in j.get('tables') or []:
        f = [str(x).strip() for x in (t.get('fields') or [])]
        title = str(t.get('title') or '')
        if '價格指數' in title and '臺灣證券交易所' in title:
            for r in t.get('data') or []:
                if str(r[0]).strip() == '發行量加權股價指數':
                    taiex = num(r[1])
        if '證券代號' in f and '收盤價' in f:
            ix = {k: f.index(k) for k in ('證券代號', '證券名稱', '成交股數', '開盤價', '最高價', '最低價', '收盤價', '漲跌(+/-)', '漲跌價差')}
            for r in t.get('data') or []:
                c = num(r[ix['收盤價']])
                if not c:
                    continue
                sign, diff = str(r[ix['漲跌(+/-)']]), num(r[ix['漲跌價差']])
                chg = None if ('X' in sign or diff is None) else (-diff if '-' in sign else diff)
                rows.append([d8, str(r[ix['證券代號']]).strip(), str(r[ix['證券名稱']]).strip(),
                             num(r[ix['開盤價']]) or c, num(r[ix['最高價']]) or c, num(r[ix['最低價']]) or c, c,
                             round((num(r[ix['成交股數']]) or 0) / 1000), chg])
    if not rows:
        return 'closed', [], None          # 颱風假等：stat OK 但沒有個股表
    return 'ok', rows, taiex


def px_tp(cl, d8):
    j = cl.get('https://www.tpex.org.tw/www/zh-tw/afterTrading/otc',
               params={'date': f'{d8[:4]}/{d8[4:6]}/{d8[6:]}', 'type': 'EW', 'response': 'json'}).json()
    rows = []
    for t in j.get('tables') or []:
        f = [str(x).strip() for x in (t.get('fields') or [])]
        if '代號' in f and '收盤' in f:
            ix = {k: f.index(k) for k in ('代號', '名稱', '收盤', '漲跌', '開盤', '最高', '最低', '成交股數')}
            for r in t.get('data') or []:
                c = num(r[ix['收盤']])
                if not c:
                    continue
                rows.append([d8, str(r[ix['代號']]).strip(), str(r[ix['名稱']]).strip(),
                             num(r[ix['開盤']]) or c, num(r[ix['最高']]) or c, num(r[ix['最低']]) or c, c,
                             round((num(r[ix['成交股數']]) or 0) / 1000), num(r[ix['漲跌']])])
    return rows


PX_H = ['date', 'stock_id', 'name', 'open', 'high', 'low', 'close', 'volume', 'chg']


def worker(mkt):
    cl = httpx.Client(headers=H, timeout=60, follow_redirects=True)
    d, n_ok = START, 0
    while d <= END:
        if d.weekday() >= 5:
            d += datetime.timedelta(days=1)
            continue
        d8 = d.strftime('%Y%m%d')
        closed = os.path.join(D, 'px', d8 + '.closed') if mkt == 'tw' else os.path.join(D, 'px', d8 + '.tp.closed')
        if os.path.exists(closed) or os.path.exists(os.path.join(D, 'px', d8 + '.closed')):
            d += datetime.timedelta(days=1)
            continue
        jobs = [('px', os.path.join(D, 'px', f'{d8}.{mkt}.csv.gz'))]
        if d >= INST_FROM:
            jobs += [('inst', os.path.join(D, 'inst', f'{d8}.{mkt}.csv.gz')), ('margin', os.path.join(D, 'margin', f'{d8}.{mkt}.csv.gz'))]
        for kind, path in jobs:
            if os.path.exists(path) or os.path.exists(closed):
                continue
            for attempt in range(4):
                try:
                    if kind == 'px' and mkt == 'tw':
                        st, rows, tx = px_tw(cl, d8)
                        if st == 'closed':
                            open(closed, 'w').close()
                            log(d8, '休市')
                            break
                        wgz(path, PX_H, rows)
                        if tx:
                            with LOCK, open(os.path.join(D, 'taiex.csv'), 'a', encoding='utf-8') as fh:
                                fh.write(f'{d8},{tx}\n')
                    elif kind == 'px':
                        rows = px_tp(cl, d8)
                        if not rows:                 # 櫃買休市回空表（連線錯誤會丟例外、不會走到這裡）
                            open(closed, 'w').close()
                            log(d8, '櫃買休市')
                            break
                        wgz(path, PX_H, rows)
                    elif kind == 'inst' and mkt == 'tw':
                        j = cl.get('https://www.twse.com.tw/rwd/zh/fund/T86',
                                   params={'date': d8, 'selectType': 'ALLBUT0999', 'response': 'json'}).json()
                        m = parse_t86_inst(j)
                        if not m:
                            raise RuntimeError(f"T86 空：{str(j.get('stat'))[:30]}")
                        wgz(path, ['stock_id', 'foreign', 'trust', 'dealer'], [[s, *v] for s, v in m.items()])
                    elif kind == 'inst':
                        dd, m = parse_tpex_insti_daily(cl.get('https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade',
                                                              params={'type': 'Daily', 'sect': 'EW', 'date': f'{d8[:4]}/{d8[4:6]}/{d8[6:]}',
                                                                      'response': 'json'}).json())
                        if not m or dd != f'{d8[:4]}-{d8[4:6]}-{d8[6:]}':
                            raise RuntimeError(f'櫃買法人空／日期不符 {dd}')
                        wgz(path, ['stock_id', 'foreign', 'trust', 'dealer'], [[s, *v] for s, v in m.items()])
                    elif kind == 'margin' and mkt == 'tw':
                        m = parse_twse_margin_both(cl.get('https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN',
                                                          params={'date': d8, 'selectType': 'ALL', 'response': 'json'}).json())
                        if not m:
                            raise RuntimeError('MI_MARGN 空')
                        wgz(path, ['stock_id', 'margin', 'short'], [[s, *v] for s, v in m.items()])
                    else:
                        m = parse_tpex_margin_both(cl.post('https://www.tpex.org.tw/www/zh-tw/margin/balance',
                                                           data={'date': f'{d8[:4]}/{d8[4:6]}/{d8[6:]}', 'response': 'json'}).json())
                        if not m:
                            raise RuntimeError('櫃買融資空')
                        wgz(path, ['stock_id', 'margin', 'short'], [[s, *v] for s, v in m.items()])
                    n_ok += 1
                    time.sleep(GAP[mkt])
                    break
                except Exception as e:      # noqa: BLE001
                    log(mkt, d8, kind, '失敗', attempt, type(e).__name__, str(e)[:80])
                    time.sleep(GAP[mkt] + 15 * (attempt + 1))
        if d.day in (1, 15):
            log(mkt, d8, f'累計 {n_ok} 個檔')
        d += datetime.timedelta(days=1)
    log(mkt, 'DONE', n_ok)


ROW = re.compile(r"<td align=center>(\d{4})</td><td align=left>[^<]*</td>"
                 r"<td nowrap>([^<]*)</td><td nowrap>([^<]*)</td><td nowrap>([^<]*)</td>"
                 r"<td nowrap>([^<]*)</td><Td nowrap>([^<]*)</td><td nowrap>([^<]*)</td>"
                 r"<td nowrap>([^<]*)</td><td nowrap>([^<]*)</td>", re.I)


def revenue():
    """月營收 2020-01 起（創 12 個月新高要前一年）；ROC 年月；上市／上櫃 × 國內(0)／國外(1)"""
    cl = httpx.Client(headers=H, timeout=60, follow_redirects=True)
    y, m = 2020, 1
    last = (END.year, END.month)
    while (y, m) < last:
        path = os.path.join(D, 'rev', f'{y}{m:02d}.csv')
        if not os.path.exists(path):
            rows, ok = {}, 0
            for mkt in ('sii', 'otc'):
                for sub in (0, 1):
                    try:
                        t = cl.get(f'https://mopsov.twse.com.tw/nas/t21/{mkt}/t21sc03_{y - 1911}_{m}_{sub}.html').content.decode('big5', 'ignore')
                        for g in ROW.findall(t.replace('\r', '').replace('\n', '')):
                            rows[g[0]] = (num(g[1]), num(g[5]), num(g[8]))
                        ok += 1
                    except Exception as e:      # noqa: BLE001
                        log('rev', y, m, mkt, sub, type(e).__name__)
                    time.sleep(1.5)
            if ok == 4 and rows:
                with open(path + '.tmp', 'w', newline='', encoding='utf-8') as fh:
                    w = csv.writer(fh)
                    w.writerow(['stock_id', 'rev', 'yoy', 'cum_yoy'])
                    w.writerows([[s, *v] for s, v in sorted(rows.items())])
                os.replace(path + '.tmp', path)
                log('rev', f'{y}{m:02d}', len(rows), '檔')
            else:
                log('rev', f'{y}{m:02d}', '沒抓完（下次再試）', ok, len(rows))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    log('rev DONE')


if __name__ == '__main__':
    ts = [threading.Thread(target=worker, args=('tw',)), threading.Thread(target=worker, args=('tp',)), threading.Thread(target=revenue)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    log('ALL DONE')
