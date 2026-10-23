"""PLAN-B82 研究：R1 籌碼（C1～C8 單一＋兩兩）、R2 月營收（M1～M5 單一＋兩兩）、R3 進場時機（E1～E4）、R4 多策略共振（K1～K3）＋共振名單
每個策略每一族：樣本內 n ≥ 100 且平均 ≥ 原本，挑（樣本內勝率, 平均）最高的一個 → 樣本外驗一次（同 B73）；
通過＝樣本外 n ≥ 50、勝率 ≥ 原本 +5 個百分點、平均每筆 > 原本、月份 block bootstrap 單邊 p 經 **全部檢定一起** BH 校正 < 0.10。
出場、股票池、成本同 run825（停損 8%／停利 25%、盤中觸價、上限 250 天）。
用法：python run_opt.py <data/best> <sig_all.csv.gz> [raw_dir（預設 research/b82/data）]
輸出：research/b82/opt_research.json（網站 /api/opt/research）、research/b82/REPORT.md"""
import itertools, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, os.path.join(ROOT, 'research', 'b72'), os.path.join(ROOT, 'research', 'b73'), os.path.join(ROOT, 'research', 'best'),
          os.path.join(ROOT, 'research', 'best2'), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)
import numpy as np
import pandas as pd
import engine
from run825 import masks, split, random_825
from run_quality import month_boot_p, bh, b1_pass, per_day, RULE_B1
import common as CM
from sim_entry import SimE

IS = ('20211001', '20240630')
OOS_START = '20240701'
SEED = 20261023
BOOT = 2000
YEARS = ('2022', '2023', '2024', '2025', '2026')
OUT = os.path.join(HERE, 'opt_research.json')
FAMS = {'chip': ('💹 籌碼', CM.CHIP, True), 'rev': ('📈 月營收', CM.REV, True), 'res': ('🔗 多策略共振', CM.RES, False)}


def load(data_dir):
    P = engine.load_panel(data_dir)
    F = engine.features(P)
    fac = engine.event_factor(P, data_dir)
    sim = SimE(P, F, fac)
    sim.last_idx_all = sim.T - 1 - 5
    return P, F, sim


def _pick(cands, sb):
    """cands：[(名稱, 交易表, 其他)] → 樣本內合格裡（勝率, 平均）最高的那個"""
    best = None
    for name, tr, extra in cands:
        s_is = split(tr, IS, OOS, YEARS)['is']
        if s_is.get('n', 0) < RULE_B1['is_n'] or s_is['mean'] < sb['is'].get('mean', 9):
            continue
        score = (s_is['win'], s_is['mean'])
        if best is None or score > best[0]:
            best = (score, name, tr, extra)
    return best


def _summ(tr, base, desc, extra=None):
    ss = split(tr, IS, OOS, YEARS)
    p, ci = month_boot_p(tr, base, OOS, reps=BOOT, seed=SEED)
    return {'desc': desc, **{q: ss[q] for q in ('is', 'oos', 'years', 'reasons')}, 'p': p, 'ci': ci, **(extra or {})}


def main(data_dir, sig_path, raw_dir):
    global OOS
    t0 = time.time()
    P, F, sim = load(data_dir)
    dates = np.array([str(d) for d in sim.dates])
    last = dates[-2]
    OOS = (OOS_START, last)
    pool = F['liquid'].to_numpy() & (sim.dates >= engine.TRADE_FROM)[:, None] & ~F['gap60'].to_numpy()
    M = masks(sim, sig_path, pool)
    from scanner import STRATEGIES
    print(f'載入 {sim.T} 天 × {sim.S} 檔、{len(M)} 個策略 {time.time() - t0:.0f}s', flush=True)

    # 資料
    inst, have_i = CM.load_daily(raw_dir, 'inst', ['foreign', 'trust', 'dealer'], dates, sim.sids)
    marg, have_m = CM.load_daily(raw_dir, 'margin', ['margin', 'short'], dates, sim.sids)
    vol = P['volume'].to_numpy(float)
    FL = {'chip': CM.chip_flags(inst, marg, vol)}
    R = CM.align_revenue(CM.load_revenue(raw_dir), dates, sim.sids)
    FL['rev'] = CM.rev_flags(R)
    FL['res'] = CM.res_flags(M)
    inst_days = dates[(dates >= '20210802') & (dates <= last)]
    inst_set = set(inst_days)
    cov = {'inst_missing': [d for d, h in zip(dates, have_i) if d in inst_set and not h],
           'margin_missing': [d for d, h in zip(dates, have_m) if d in inst_set and not h],
           'trade_days': int(len(inst_days))}
    print('覆蓋', {k: (len(v) if isinstance(v, list) else v) for k, v in cov.items()},
          {f: {k: round(float(v[pool].mean()), 3) for k, v in FL[f].items()} for f in FL}, f'{time.time() - t0:.0f}s', flush=True)

    # E0 必須跟 run825 一模一樣
    k0 = sorted(M)[0]
    a, b = sim.trades825(M[k0]), sim.trades_v(M[k0], 'E0')
    assert len(a) == len(b) and np.allclose(a['ret'].to_numpy(float), b['ret'].to_numpy(float)), 'E0 跟 trades825 不一致'

    res, pv = {}, {}
    for key, m in sorted(M.items()):
        base = sim.trades825(m)
        sb = split(base, IS, OOS, YEARS)
        r = {'label': STRATEGIES.get(key, key), 'base': {q: sb[q] for q in ('is', 'oos', 'years')}, 'per_day_base': per_day(m, OOS, dates)}
        for fam, (lab, names, pairs) in FAMS.items():
            cbs = [(k,) for k in names] + (list(itertools.combinations(names, 2)) if pairs else [])
            cands = []
            for cb in cbs:
                fm = np.ones_like(m)
                for k in cb:
                    fm &= FL[fam][k]
                cands.append((cb, sim.trades825(m & fm), fm))
            best = _pick(cands, sb)
            if best is None:
                r[fam] = None
                pv[f'{fam}|{key}'] = 1.0
                continue
            _, cb, tr, fm = best
            r[fam] = _summ(tr, base, '＋'.join(names[k] for k in cb),
                           {'combo': list(cb), 'random': random_825(sim, pool & fm, m & fm, OOS, seed=SEED), 'per_day': per_day(m & fm, OOS, dates)})
            pv[f'{fam}|{key}'] = r[fam]['p']
        # R3 進場時機
        cands = [(v, sim.trades_v(m, v), None) for v in ('E1', 'E2', 'E3', 'E4')]
        best = _pick(cands, sb)
        if best is None:
            r['entry'] = None
            pv[f'entry|{key}'] = 1.0
        else:
            _, v, tr, _ = best
            slip = split(sim.trades_v(m, v, slip=0.002), IS, OOS, YEARS)
            r['entry'] = _summ(tr, base, CM.ENTRY[v], {'variant': v, 'fill_rate': sim.fill_rate(m, v),
                               'intra_share': float(tr['intra'].mean()) if len(tr) else None,
                               'slip': {'oos': slip['oos']},
                               'random': random_825(sim, pool, m, OOS, seed=SEED, trades_fn=lambda mm, v=v: sim.trades_v(mm, v))})
            pv[f'entry|{key}'] = r['entry']['p']
        res[key] = r
        print(f'{key}: base oos {sb["oos"].get("n")}/{sb["oos"].get("win")} ' + ' '.join(
            f'{f}={r[f]["desc"][:14]}:{r[f]["oos"].get("n")}/{r[f]["oos"].get("win") and round(r[f]["oos"]["win"], 3)}/p{round(r[f]["p"], 3)}' if r[f] else f'{f}=—'
            for f in ('chip', 'rev', 'entry', 'res')) + f' {time.time() - t0:.0f}s', flush=True)

    # 共振名單（整體）
    union = np.zeros_like(next(iter(M.values())))
    for m in M.values():
        union |= m
    _, five = CM.res_counts(M)
    lst = union & (five >= 2)
    trU, trL = sim.trades825(union), sim.trades825(lst)
    sU, sL = split(trU, IS, OOS, YEARS), split(trL, IS, OOS, YEARS)
    pL, ciL = month_boot_p(trL, trU, OOS, reps=BOOT, seed=SEED)
    rl = {'desc': '任何股票 5 個交易日內被 ≥ 2 個不同做多策略選到（今天是其中一個）', 'base': {q: sU[q] for q in ('is', 'oos')},
          **{q: sL[q] for q in ('is', 'oos', 'years', 'reasons')}, 'p': pL, 'ci': ciL,
          'random': random_825(sim, pool, lst, OOS, seed=SEED), 'per_day': per_day(lst, OOS, dates), 'per_day_base': per_day(union, OOS, dates)}
    pv['res_list|ALL'] = pL

    adj = bh(pv)
    n_pass = 0
    for key, r in res.items():
        for f in ('chip', 'rev', 'entry', 'res'):
            if r[f]:
                r[f]['p_adj'] = adj[f'{f}|{key}']
                r[f]['passed'] = b1_pass(r[f]['oos'], r['base']['oos'], r[f]['p_adj'])
                n_pass += r[f]['passed']
    o, bo, rd = rl['oos'], rl['base']['oos'], rl['random']
    rl['p_adj'] = adj['res_list|ALL']
    rl['beats_random'] = bool(o.get('n') and rd['mean'] is not None and o['mean'] > rd['mean'] and o['win'] > rd['win'])
    rl['passed'] = bool(o.get('n', 0) >= 100 and o['win'] >= bo.get('win', 1) + RULE_B1['win_gap'] and o['mean'] > bo.get('mean', 9)
                        and o['mean'] > 0 and rl['p_adj'] < RULE_B1['bh_q'] and rl['beats_random'])
    n_pass += rl['passed']
    meta = {'periods': {'is': IS, 'oos': OOS}, 'data_end': str(dates[-1]), 'generated': time.strftime('%Y-%m-%d %H:%M'),
            'rules': '每個策略每一族：樣本內 n ≥ 100 且平均 ≥ 原本，挑樣本內（勝率, 平均）最高的一個 → 樣本外驗一次；通過＝樣本外 n ≥ 50、勝率 ≥ 原本 +5 個百分點、平均每筆 > 原本、'
                     f'月份 block bootstrap（{BOOT} 次）p 經全部 {len(pv)} 個檢定一起 BH 校正 < 0.10。',
            'timing': '資料時間點：三大法人用訊號當天（約 16:00 公布）、融資用前一天（約 21:00 才公布，18:00 掃描看不到當天）、月營收 M 月從 M+1 月 15 日起（1 月營收 2 月 20 日）。',
            'exit': '停損 8%／停利 25%（盤中觸價、跳空用開盤價、同一天都碰到算停損）、不限天數（上限 250 交易日）；成本 買 0.2425%、賣 0.5425%',
            'entry_rules': '進場時機：掛單要穿過 1 檔才算買到、突破要過訊號高 1 檔、一價漲停買不到、盤中買進那天碰到停損就停損、停利不算',
            'pool': '4 碼普通股、收盤 ≥ 10、20 日均量 ≥ 500 張、≥ 120 根、60 天內沒有 >10.5% 跳動', 'boot': BOOT, 'seed': SEED,
            'n_tests': len(pv), 'n_passed': int(n_pass), 'expected_false': round(0.10 * n_pass, 2), 'coverage': cov,
            'families': {f: {'label': FAMS[f][0], 'conds': FAMS[f][1]} for f in FAMS} | {'entry': {'label': '🕐 進場時機', 'conds': CM.ENTRY}}}
    out = {'meta': meta, 'strategies': res, 'resonance_list': rl}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    report(out)
    print(f'DONE 通過 {n_pass} 項／{len(pv)} 個檢定 {time.time() - t0:.0f}s', flush=True)
    return out


def _w(x):
    return '—' if x is None else f'{x * 100:.1f}%'


def _m(x):
    return '—' if x is None else f'{x * 100:+.2f}%'


def report(out):
    meta, S, rl = out['meta'], out['strategies'], out['resonance_list']
    L = ['# PLAN-B82 研究：籌碼／月營收／進場時機／多策略共振能不能提高現行策略的勝率（出場固定 停損 8%／停利 25%）', '',
         f"- 資料：官方 MI_INDEX＋櫃買 otc（含下市）、三大法人 T86＋櫃買、融資 MI_MARGN＋櫃買、月營收 t21sc03；資料到 {meta['data_end']}；產生 {meta['generated']}",
         f"- 樣本內 {meta['periods']['is'][0]}～{meta['periods']['is'][1]}、樣本外 {meta['periods']['oos'][0]}～{meta['periods']['oos'][1]}",
         f"- {meta['rules']}", f"- {meta['timing']}", f"- {meta['entry_rules']}",
         f"- 資料缺漏：法人 {len(meta['coverage']['inst_missing'])}／{meta['coverage']['trade_days']} 天、融資 {len(meta['coverage']['margin_missing'])} 天（缺的那天＝不符合）",
         '', f"**結果：{meta['n_tests']} 個檢定，通過 {meta['n_passed']} 項**（BH q＝0.10 下預期約 {meta['expected_false']} 項可能是運氣）", '',
         '| 策略 | 原本 樣本外 勝率／平均（筆） | 族 | 樣本內挑出的方法 | 樣本外 勝率／平均（筆） | 隨機（同條件） | 校正後 p | 結果 |', '|---|---|---|---|---|---|---|---|']
    for k, r in sorted(S.items(), key=lambda kv: -((kv[1]['base']['oos'] or {}).get('mean') or -9)):
        bo = r['base']['oos']
        for f, lab in (('chip', '籌碼'), ('rev', '月營收'), ('entry', '進場'), ('res', '共振')):
            x = r[f]
            if not x:
                L.append(f"| {r['label'][:18]} | {_w(bo.get('win'))}／{_m(bo.get('mean'))}（{bo.get('n', 0)}） | {lab} | 樣本內沒有合格 | — | — | — | ✗ |")
                continue
            o, rd = x['oos'], x.get('random') or {}
            L.append(f"| {r['label'][:18]} | {_w(bo.get('win'))}／{_m(bo.get('mean'))}（{bo.get('n', 0)}） | {lab} | {x['desc']} | {_w(o.get('win'))}／{_m(o.get('mean'))}（{o.get('n', 0)}） | "
                     f"{_w(rd.get('win'))}／{_m(rd.get('mean'))} | {x['p_adj']:.3f} | {'✅' if x['passed'] else '✗'} |")
    o, bo = rl['oos'], rl['base']['oos']
    L += ['', '## 🎯 共振名單（整體）', f"- {rl['desc']}",
          f"- 樣本外 {_w(o.get('win'))}／{_m(o.get('mean'))}（{o.get('n', 0)} 筆，每天 {rl['per_day']:.1f} 檔）；全部做多訊號合併 {_w(bo.get('win'))}／{_m(bo.get('mean'))}（每天 {rl['per_day_base']:.1f} 檔）；"
          f"隨機 {_w(rl['random'].get('win'))}／{_m(rl['random'].get('mean'))}；校正後 p {rl['p_adj']:.3f} → {'✅ 通過' if rl['passed'] else '✗ 沒通過'}"]
    passed = [(k, f) for k, r in S.items() for f in ('chip', 'rev', 'entry', 'res') if r[f] and r[f]['passed']]
    L += ['', '## 通過的項目（各年勝率：加條件 vs 原本）']
    if not passed and not rl['passed']:
        L.append('- 沒有。網站不改任何策略，只顯示這份結果。')
    for k, f in passed:
        x, b = S[k][f], S[k]['base']
        yrs = '　'.join(f"{y}：{_w((x['years'].get(y) or {}).get('win'))} vs {_w((b['years'].get(y) or {}).get('win'))}" for y in YEARS if (x['years'].get(y) or {}).get('n'))
        L.append(f"- {S[k]['label']}（{f}）：{x['desc']}；{yrs}")
    L += ['', '## 進場時機補充（挑出的方法）', '| 策略 | 方法 | 買得到的比例 | 盤中買進比例 | 樣本外（多扣 0.2% 滑價） |', '|---|---|---|---|---|']
    for k, r in S.items():
        x = r['entry']
        if x:
            L.append(f"| {r['label'][:18]} | {x['variant']} | {_w(x.get('fill_rate'))} | {_w(x.get('intra_share'))} | {_w(x['slip']['oos'].get('win'))}／{_m(x['slip']['oos'].get('mean'))} |")
    open(os.path.join(HERE, 'REPORT.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')


OOS = None
if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else os.path.join(HERE, 'data'))
