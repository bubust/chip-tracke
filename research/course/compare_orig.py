"""合併類（項目 1、2）的公平比較：原本策略的訊號 vs 新版訊號，用「同一個濾網＋出場」比樣本外（避免出場不同造成的差異）。
用法：python compare_orig.py <best_data_dir> <course_data_dir>  → results/merge_compare.json"""
import json, os, pickle, sys
import numpy as np
import run_course as R
import run2

EXITS = ['E1_20d', 'E3_t2_s2_40d', 'E6_s10_t0_60d', 'E7c_s20', 'S_struct60']


def main(best_dir, course_dir):
    P, F, fac, sim, pool, lite = R.load(best_dir)
    sigs = pickle.load(open(os.path.join(os.path.dirname(os.path.abspath(course_dir)), 'signals.pkl'), 'rb'))
    shape = (sim.T, sim.S)
    flt = R._filters(P, F)
    exits = R.long_exits()
    summ = json.load(open(os.path.join(R.OUT, 'long_summary.json'), encoding='utf-8'))
    orig = R.load_sig_a(P, best_dir, ['S_NBREAK', 'S_THUNDER', 'S_VOLROLL'])
    orig = {k: v & pool for k, v in orig.items()}
    out = {}
    for pre, okeys in (('NB', ['S_NBREAK']), ('BR', ['S_THUNDER', 'S_VOLROLL'])):
        pk = summ[pre].get('pick') or summ[pre].get('best_any')
        nm, fk = pk['variant'], pk['filter']
        new = R.dense(sigs[nm], shape) & pool
        stop_new = R.dense(sigs[nm], shape, info=True)
        groups = {'new:' + nm: new}
        for k in okeys:
            groups['orig:' + k] = orig[k]
        if pre == 'BR':                                   # 合併版＝原平地一聲雷 ∪ 底部起漲 ∪ 原量滾量
            groups['merged'] = orig['S_THUNDER'] | orig['S_VOLROLL'] | new
        res = {}
        for ek in EXITS + ([pk['exit']] if pk['exit'] not in EXITS else []):
            for fkk in sorted({fk, 'none'}):
                trs = {}
                for g, m in groups.items():
                    mm = m if flt[fkk] is None else (m & flt[fkk])
                    if ek == 'S_struct60':
                        if not g.startswith('new'):
                            continue
                        sim.stop_mat = stop_new
                    tr = sim.trades2(mm, exits[ek])
                    trs[g] = tr
                    ss = R.run.split_stats(tr)
                    res.setdefault(f'{fkk}|{ek}', {})[g] = {'is': ss['is'], 'oos': ss['oos']}
                base = trs.get('orig:' + okeys[0])
                for g, tr in trs.items():
                    if base is not None and g != 'orig:' + okeys[0]:
                        res[f'{fkk}|{ek}'][g]['boot_vs_orig_lo95'] = R._boot_lo(tr, base)
        out[pre] = {'pick': pk.get('combo'), 'compare': res}
        print(pre, 'done', flush=True)
    R._save('merge_compare.json', out)
    for pre, v in out.items():
        for key, gs in v['compare'].items():
            print(pre, key, {g: (x['oos'].get('n'), round(x['oos'].get('win', 0), 3), round(x['oos'].get('mean', 0), 4), x.get('boot_vs_orig_lo95')) for g, x in gs.items()})


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
