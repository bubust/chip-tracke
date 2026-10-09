"""證交所＋櫃買 處置股、注意股歷史（2021-01～今天）→ data/disposal.csv、data/attention.csv（可重跑，逐月）
處置：date_pub,stock_id,name,start,end,times(第幾次),cond,market；注意：date,stock_id,name,count,reason,market"""
import csv, datetime, os, re, sys, time
import httpx

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(OUT, exist_ok=True)
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}


def roc(s):
    m = re.match(r'(\d+)\D+(\d+)\D+(\d+)', str(s).strip())
    if not m:
        return ''
    y, mo, d = map(int, m.groups())
    return f'{y + 1911 if y < 1911 else y:04d}{mo:02d}{d:02d}'


def months(a, b):
    d = a.replace(day=1)
    while d <= b:
        nxt = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        yield d, min(nxt - datetime.timedelta(days=1), b)
        d = nxt


def get(url, params):
    for k in range(4):
        try:
            r = httpx.get(url, params=params, headers=H, timeout=60, follow_redirects=True)
            return r.json()
        except Exception as e:
            print('  retry', url, params, type(e).__name__, flush=True)
            time.sleep(10 * (k + 1))
    return {}


def main(start='2021-01-01'):
    a = datetime.date(*map(int, start.split('-')))
    b = datetime.date.today()
    disp, att = [], []
    for m0, m1 in months(a, b):
        s8, e8 = m0.strftime('%Y%m%d'), m1.strftime('%Y%m%d')
        j = get('https://www.twse.com.tw/rwd/zh/announcement/punish', {'startDate': s8, 'endDate': e8, 'response': 'json'})
        for r in j.get('data') or []:
            se = str(r[6]).split('～') if '～' in str(r[6]) else str(r[6]).split('~')
            disp.append([roc(r[1]), str(r[2]).strip(), str(r[3]).strip(), roc(se[0]) if se else '', roc(se[1]) if len(se) > 1 else '',
                         r[4], str(r[5]).strip(), str(r[7]).strip(), 'twse'])
        time.sleep(3)
        j = get('https://www.tpex.org.tw/www/zh-tw/bulletin/disposal', {'startDate': m0.strftime('%Y/%m/%d'), 'endDate': m1.strftime('%Y/%m/%d'), 'response': 'json'})
        for t in j.get('tables') or []:
            for r in t.get('data') or []:
                if not str(r[2]).strip():
                    continue
                se = re.split(r'[~～]', str(r[5]))
                disp.append([roc(r[1]), str(r[2]).strip(), re.sub(r'\(.*', '', str(r[3])).strip(), roc(se[0]) if se else '',
                             roc(se[1]) if len(se) > 1 else '', r[4], str(r[6]).strip(), str(r[7]).strip(), 'tpex'])
        time.sleep(3)
        # 注意股（一次一個月）
        j = get('https://www.twse.com.tw/rwd/zh/announcement/notice', {'startDate': s8, 'endDate': e8, 'response': 'json'})
        for r in j.get('data') or []:
            att.append([roc(r[5]), str(r[1]).strip(), str(r[2]).strip(), r[3], re.sub(r'<[^>]+>', '', str(r[4]))[:120], 'twse'])
        time.sleep(3)
        j = get('https://www.tpex.org.tw/www/zh-tw/bulletin/attention', {'startDate': m0.strftime('%Y/%m/%d'), 'endDate': m1.strftime('%Y/%m/%d'), 'response': 'json'})
        for t in j.get('tables') or []:
            for r in t.get('data') or []:
                att.append([roc(r[5]), str(r[1]).strip(), str(r[2]).strip(), r[3], str(r[4])[:120], 'tpex'])
        time.sleep(3)
        print(m0, 'disp', len(disp), 'att', len(att), flush=True)
    with open(os.path.join(OUT, 'disposal.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(['date_pub', 'stock_id', 'name', 'start', 'end', 'times', 'cond', 'measure', 'market']); w.writerows(disp)
    with open(os.path.join(OUT, 'attention.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(['date', 'stock_id', 'name', 'count', 'reason', 'market']); w.writerows(att)
    print('DONE', len(disp), len(att))


if __name__ == '__main__':
    main(*(sys.argv[1:2] or []))
