"""PLAN-B82：fetch_all.py 抓的原始檔 → research/b82/data/best（research/best/engine.load_panel 的格式），並列出缺漏
用法：python merge.py（之後把 research/best/fetch_events.py 產生的 events.csv 放進 data/best/）"""
import datetime, glob, os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, 'data')
OUT = os.path.join(D, 'best')
os.makedirs(OUT, exist_ok=True)
INST_FROM = '20210802'


def main():
    tw = sorted(os.path.basename(f)[:8] for f in glob.glob(os.path.join(D, 'px', '*.tw.csv.gz')))
    n_ok, tp_missing = 0, []
    for d8 in tw:
        out = os.path.join(OUT, d8 + '.csv.gz')
        tpf = os.path.join(D, 'px', d8 + '.tp.csv.gz')
        if not os.path.exists(tpf):
            tp_missing.append(d8)
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(os.path.join(D, 'px', d8 + '.tw.csv.gz')) \
                and (not os.path.exists(tpf) or os.path.getmtime(out) >= os.path.getmtime(tpf)):
            n_ok += 1
            continue
        parts = [pd.read_csv(os.path.join(D, 'px', d8 + '.tw.csv.gz'), dtype={'date': str, 'stock_id': str})]
        if os.path.exists(tpf):
            parts.append(pd.read_csv(tpf, dtype={'date': str, 'stock_id': str}))
        pd.concat(parts, ignore_index=True).to_csv(out, index=False, compression='gzip')
        n_ok += 1
    tx = pd.read_csv(os.path.join(D, 'taiex.csv'), header=None, names=['date', 'taiex'], dtype={'date': str})
    tx = tx.drop_duplicates('date', keep='last').sort_values('date')
    tx.to_csv(os.path.join(OUT, 'taiex.csv'), header=False, index=False)
    inst_days = [d for d in tw if d >= INST_FROM]
    miss = {k: [d for d in inst_days if not (os.path.exists(os.path.join(D, k, d + '.tw.csv.gz')) and os.path.exists(os.path.join(D, k, d + '.tp.csv.gz')))]
            for k in ('inst', 'margin')}
    rev = sorted(os.path.basename(f)[:6] for f in glob.glob(os.path.join(D, 'rev', '*.csv')))
    print(f'交易日 {len(tw)}（{tw[0] if tw else "—"}～{tw[-1] if tw else "—"}）合併 {n_ok}；櫃買缺 {len(tp_missing)} 天 {tp_missing[:10]}')
    print(f'加權 {len(tx)} 天；法人缺 {len(miss["inst"])}／{len(inst_days)} 天 {miss["inst"][:10]}；融資缺 {len(miss["margin"])} 天 {miss["margin"][:10]}')
    print(f'月營收 {len(rev)} 個月（{rev[0] if rev else "—"}～{rev[-1] if rev else "—"}）')
    return {'days': len(tw), 'tp_missing': tp_missing, 'inst_missing': miss['inst'], 'margin_missing': miss['margin'], 'rev_months': rev}


if __name__ == '__main__':
    main()
