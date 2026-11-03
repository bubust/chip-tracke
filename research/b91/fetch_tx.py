"""PLAN-B91 研究：證交所「每 5 秒指數」MI_5MINS_INDEX → 每天加權指數 1 分 K（09:00～13:30），給 13:15 大盤盤面研究用。
data/tx1315/{d8}.csv.gz（hm,o,h,l,c；hm＝HHMM，那一分鐘內 5 秒點的開高低收；hm 859＝09:00:00 的值＝前一天收盤）；休市／沒資料 → {d8}.closed
可中斷續抓；證交所限速：每次間隔 GAP 秒。用法：python fetch_tx.py [START] [END]"""
import csv, datetime, gzip, os, sys, time
import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'data', 'tx1315')
os.makedirs(OUT, exist_ok=True)
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'}
GAP = float(os.environ.get("FETCH_GAP", "2.2"))         # 11-03 四段同時、間隔 2.2 秒被證交所擋 → 之後用 2 段、6 秒
START = datetime.date(*map(int, (sys.argv[1] if len(sys.argv) > 1 else '2021-01-01').split('-')))
END = datetime.date(*map(int, (sys.argv[2] if len(sys.argv) > 2 else datetime.date.today().isoformat()).split('-')))


def num(v):
    try:
        return float(str(v).replace(',', '').strip())
    except Exception:
        return None


def fetch(cl, d8):
    j = cl.get('https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_INDEX', params={'date': d8, 'response': 'json'}).json()
    rows = j.get('data') or []
    if str(j.get('stat', '')).strip() != 'OK' or not rows:
        return None
    mins = {}
    for r in rows:
        t, v = str(r[0]).strip(), num(r[1])
        if v is None or len(t) < 5:
            continue
        hm = int(t[:2]) * 100 + int(t[3:5])
        if t.startswith('09:00:00'):
            hm = 859                       # 09:00:00＝前一天收盤（還沒有成交），另存成 859 那一列；開盤＝09:00:05
        m = mins.get(hm)
        if m is None:
            mins[hm] = [v, v, v, v]
        else:
            m[1] = max(m[1], v); m[2] = min(m[2], v); m[3] = v
    return [[hm, *mins[hm]] for hm in sorted(mins)]


def main():
    d = START
    n_ok = n_closed = n_skip = 0
    with httpx.Client(headers=H, timeout=30, verify=False) as cl:
        while d <= END:
            if d.weekday() < 5:
                d8 = d.strftime('%Y%m%d')
                f, fc = os.path.join(OUT, d8 + '.csv.gz'), os.path.join(OUT, d8 + '.closed')
                if os.path.exists(f) or os.path.exists(fc):
                    n_skip += 1
                else:
                    for attempt in range(4):
                        try:
                            rows = fetch(cl, d8)
                            break
                        except Exception as e:
                            print(time.strftime('%H:%M:%S'), d8, 'retry', attempt, type(e).__name__, flush=True)
                            time.sleep(60 * (attempt + 1))                # 被擋（回 HTML）→ 退避久一點
                    else:
                        rows = 'fail'
                    if rows == 'fail':
                        pass
                    elif rows is None:
                        open(fc, 'w').close(); n_closed += 1
                    else:
                        with gzip.open(f + '.tmp', 'wt', newline='', encoding='utf-8') as fh:
                            w = csv.writer(fh); w.writerow(['hm', 'o', 'h', 'l', 'c']); w.writerows(rows)
                        os.replace(f + '.tmp', f); n_ok += 1
                    if (n_ok + n_closed) % 50 == 0:
                        print(time.strftime('%H:%M:%S'), d8, 'ok', n_ok, 'closed', n_closed, flush=True)
                    time.sleep(GAP)
            d += datetime.timedelta(days=1)
    print('done ok', n_ok, 'closed', n_closed, 'skip', n_skip, flush=True)


if __name__ == '__main__':
    main()
