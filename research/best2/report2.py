"""PLAN-BEST2 報告：results/ → REPORT.md（中文）、strategy_site.json（策略篩選每個策略的回測建議）、crash_site.json（大跌買點卡片）"""
import hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research', 'best'))
import pandas as pd
from report import describe_exit, describe_regime, strat_label

RES = os.path.join(HERE, 'results')
P = lambda x: '—' if x is None or x != x else f'{x * 100:+.2f}%'
W = lambda x: '—' if x is None or x != x else f'{x * 100:.0f}%'
FLT = {'none': '不加濾網', 'tx60': '加權在 60 日線上才做', 'tx200': '加權在 200 日線上才做', 'c60': '個股在 60 日線上才做', 'c200': '個股在 200 日線上才做'}


def ex_desc(ek):
    if ek == 'E0_site':
        return '網站 K 線回測預設：2 倍 ATR 停損＋2.5 倍 ATR 移動停損（盤中觸價）、最多 60 天'
    m = re.match(r'E6_s(\d+)_t(\d+)_(\d+)d$', ek)
    if m:
        s, t, d = m.groups()
        return f"固定停損 {s}%{'、停利 ' + t + '%' if t != '0' else ''}（收盤判斷、隔天開盤賣）、最多 {d} 天"
    m = re.match(r'E7([ci])_s(\d+)$', ek)
    if m:
        return f"固定停損 {m.group(2)}%、沒跌破一直抱（{'收盤判斷' if m.group(1) == 'c' else '盤中觸價'}、最多 250 天）"
    return describe_exit(ek)


def main():
    picks = json.load(open(os.path.join(RES, 'strat_pick.json'), encoding='utf-8'))
    e7 = pd.read_csv(os.path.join(RES, 'e7_study.csv'))
    crash = json.load(open(os.path.join(RES, 'crash_summary.json'), encoding='utf-8'))
    tiers = json.load(open(os.path.join(RES, 'tiers.json'), encoding='utf-8')) if os.path.exists(os.path.join(RES, 'tiers.json')) else None
    L = ['# 用研究成果改良現有策略＋固定 % 停損＋大跌買大盤／權值股（PLAN-BEST2）', '',
         '- 資料、成本、股票池同 PLAN-BEST（5 年官方資料、含下市、官方除權息表、來回 0.785%）；樣本內 2021-10～2024-06、樣本外 2024-07～2026-08。',
         '- 「原本」＝網站 K 線回測預設出場（直接呼叫 backtest_engine.simulate，跟網站批量回測同一份程式）。', '']
    # 1. 各策略
    L += ['## 1. 現有策略：原本 vs 改良（樣本內挑、樣本外驗）', '',
          '| 策略 | 原本 樣本外 勝率／平均 | 改良版（濾網＋出場） | 改良 樣本外 勝率／平均 | 帳戶年化／回撤（原本→改良，10 檔） | 結果 |', '|---|---|---|---|---|---|']
    site = {}
    for r in picks:
        k = r['strategy'][2:]
        b, p = r['baseline'], r.get('pick')
        e7k = e7[(e7.src == r['strategy']) & (e7['mode'] == 'close') & (e7.stop == 10)]
        e7r = e7k.iloc[0].to_dict() if len(e7k) else None
        entry = {'label': strat_label(k), 'baseline': {x: b.get(x) for x in ('is_n', 'is_win', 'is_mean', 'oos_n', 'oos_win', 'oos_mean', 'all_win', 'all_mean', 'all_days')},
                 'improved': bool(r.get('improved')), 'reasons': r.get('reasons', []),
                 'e7_10': {x: e7r.get(x) for x in ('win', 'mean', 'days', 'wash60', 'port_cagr', 'port_mdd')} if e7r else None}
        if p:
            _, fk, ek = p['combo'].split('|')
            entry['pick'] = {'filter': FLT.get(fk, fk), 'exit': ex_desc(ek), 'combo': p['combo'],
                             **{x: p.get(x) for x in ('is_n', 'is_win', 'is_mean', 'oos_n', 'oos_win', 'oos_mean', 'all_win', 'all_mean', 'all_days')}}
            pb, pp = r.get('port_base', {}).get('10x10', {}), r.get('port_pick', {}).get('10x10', {})
            entry['port'] = {'base': pb, 'pick': pp}
            L.append(f"| {strat_label(k)} | {W(b.get('oos_win'))}／{P(b.get('oos_mean'))} | {FLT.get(fk, fk)}；{ex_desc(ek)} | {W(p.get('oos_win'))}／{P(p.get('oos_mean'))} | "
                     f"{P(pb.get('cagr'))}／{P(pb.get('mdd'))} → {P(pp.get('cagr'))}／{P(pp.get('mdd'))} | {'✅ 改良成功' if r.get('improved') else '✗ ' + '；'.join(r.get('reasons', []))[:80]} |")
        else:
            L.append(f"| {strat_label(k)} | {W(b.get('oos_win'))}／{P(b.get('oos_mean'))} | — | — | — | 樣本內沒有合格組合 |")
        site[k] = entry
    n_ok = sum(1 for r in picks if r.get('improved'))
    L += ['', f'**結論**：{len(picks)} 個策略裡 {n_ok} 個改良成功（樣本外真的比較好、bootstrap 下限 > 0、勝過隨機）。照「勝率最高」挑的改良版大多是「小停利大停損」，樣本內勝率高但樣本外變虧錢。', '']
    # 2. E7
    L += ['## 2. 固定 % 停損、沒跌破一直抱（收盤判斷、最多 250 天）', '',
          '| 進場 | 停損 | 勝率 | 平均每筆 | 平均抱幾天 | 60 天內被洗出場 | 被停損的平均 | 沒被停損的平均 | 帳戶年化／回撤（10 檔） |', '|---|---|---|---|---|---|---|---|---|']
    for _, x in e7[(e7['mode'] == 'close') & e7.src.isin(['RANDOM', 'A_S_BIAS', 'A_S10', 'A_S1', 'A_S_KDJ_LOW'])].iterrows():
        src = '隨機進場（對照）' if x.src == 'RANDOM' else strat_label(x.src[2:])
        L.append(f"| {src} | {int(x.stop)}% | {W(x.win)} | {P(x['mean'])} | {x.days:.0f} | {W(x.wash60)} | {P(x.mean_stopped)} | {P(x.mean_kept)} | {P(x.port_cagr)}／{P(x.port_mdd)} |")
    rnd = e7[(e7.src == 'RANDOM') & (e7['mode'] == 'close') & (e7.stop == 10)].iloc[0]
    cmp_ci = e7[(e7.stop == 10)].pivot_table(index='src', columns='mode', values='mean')
    e7_text = (f"固定停損、沒跌破一直抱＝低勝率（約 2～4 成）、高賠率：賺的單一直抱，平均每筆 +6%～+29%；但這 5 年大多頭，"
               f"連隨機進場套 10% 停損都有 {P(rnd['mean'])}、勝率 {W(rnd.win)}。停損 5% 有 6～8 成在 60 天內被洗出場，10% 約一半，20% 約 2～3 成；"
               "收盤判斷比盤中觸價平均多約 1 個百分點。整個帳戶照做的年化在不同停損之間跳很大（不穩定）、回撤 −32%～−52%。")
    L += ['', '**結論**：' + e7_text, '']
    # 3. 大跌
    sm = pd.DataFrame(crash['summary'])
    L += ['## 3. 大跌時買 0050／權值股（事件少，只列結果、不做顯著性宣稱）', '',
          '| 訊號 | 次數 | 標的 | 抱 60 天 勝率／平均 | 抱 120 天 勝率／平均 | 隨機日子 抱 120 天 勝率／平均 | 日期 |', '|---|---|---|---|---|---|---|']
    deep = ['T1_dd15', 'T2_ma60_10', 'T3_bias100', 'T1_dd8', 'T2_ma60_5']
    for tk in deep:
        for inst in ('0050', '2330', '2454', 'TOP10'):
            a = sm[(sm.trigger == tk) & (sm.inst == inst) & (sm.exit == 'H60')]
            b = sm[(sm.trigger == tk) & (sm.inst == inst) & (sm.exit == 'H120')]
            if not len(a):
                continue
            a, b = a.iloc[0], b.iloc[0]
            L.append(f"| {tk} | {a.n_events} | {inst} | {W(a.win)}／{P(a['mean'])} | {W(b.win)}／{P(b['mean'])} | {W(b.rand_win)}／{P(b.rand_mean)} | {'、'.join(d[2:4] + '/' + d[4:6] for d in a.dates)} |")
    ev = pd.read_csv(os.path.join(RES, 'crash_events.csv'), dtype={'date': str})
    deep_ev = ev[ev.trigger.isin(['T1_dd15', 'T2_ma60_10', 'T3_bias100']) & ev.exit.isin(['H20', 'H60', 'H120'])]
    deep_ev = deep_ev.assign(ret=deep_ev['ret'].where(~deep_ev['open'].astype(str).eq('True')))   # 還沒抱滿（資料到今天）→ 不算結果
    tab = deep_ev.pivot_table(index=['date', 'inst'], columns='exit', values='ret', aggfunc='first', dropna=False).reset_index()
    events, last = [], None
    for d, g in tab.groupby('date'):            # 同一波（30 天內）只留第一天，觸發條件合併
        if last is not None and (pd.Timestamp(d) - pd.Timestamp(last)).days <= 30:
            events[-1]['triggers'] = sorted(set(events[-1]['triggers']) | set(deep_ev[deep_ev.date == d].trigger))
            continue
        last = d
        events.append({'date': d, 'rows': [{'inst': r['inst'], **{k: (None if pd.isna(r.get(k)) else float(r.get(k))) for k in ('H20', 'H60', 'H120')}}
                                           for _, r in g.iterrows()],
                       'triggers': sorted(deep_ev[deep_ev.date == d].trigger.unique().tolist())})
    crash_text = ("過去 5 年深跌（加權比 60 日最高跌 15%、或低於季線 10%、或負乖離抄底 ≥ 100 檔）只有 5 波（2022-06／2022-10／2024-08／2025-04／2026-07）；"
                  "已經滿 120 天的 4 波裡，隔天買 0050 或台積電抱 60～120 天有 3 波賺（+10%～+66%），2022-06 空頭剛開始那波抱 60 天還虧約 6%（之後還有一段跌）。"
                  "跌 8%～10% 這種中度回檔就跟隨便挑日子買差不多。事件太少，不能保證下次一樣；分批買比一次買滿安全。")
    L += ['', '**結論**：' + crash_text, '']
    json.dump({'text': crash_text, 'events': events, 'summary': sm[sm.trigger.isin(deep) & sm.exit.isin(['H20', 'H60', 'H120'])].to_dict('records')},
              open(os.path.join(RES, 'crash_site.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    # 4. 嚴格／放寬
    if tiers:
        L += ['## 4. 全部組合：嚴格／放寬兩層（含新的固定 % 停損出場）', '', f"- 共 {tiers['n_combos']:,} 個組合（{tiers['n_signals']} 個訊號 × 3 濾網 × {tiers['n_exits']} 種出場）", '']
        for tier, lab in (('strict', '嚴格（原標準）'), ('relaxed', '放寬（用戶要求；**探索性，非獨立驗證**）')):
            t = tiers[tier]
            L += [f"### {lab}", '', f"- 樣本內合格 {t['n_is_ok']} 個；前 20 名樣本外也合格 {t['n_top_oos_ok']} 個；主推：**{t['main'] or '沒有'}**", '']
            for c in t['checks']:
                L.append(f"  - `{c['combo']}`：樣本外 {W(c['oos_win'])}／{P(c['oos_mean'])}；" + ('✅ 全部通過' if c['pass'] else '；'.join(c['reasons'])))
            L.append('')
    L += ['## 限制', '', '- 2023～2026 大多頭（固定停損一直抱特別吃香）；大跌事件少；盤中觸價用日線高低估；籌碼型策略沒測。', '']
    open(os.path.join(RES, 'REPORT.md'), 'w', encoding='utf-8').write('\n'.join(L))
    out = {'strategies': site, 'e7_text': e7_text, 'n_improved': n_ok,
           'tiers': {k: {'main': v['main'], 'n_top_oos_ok': v['n_top_oos_ok']} for k, v in (tiers or {}).items() if k in ('strict', 'relaxed')}}
    p = os.path.join(RES, 'strategy_site.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    print('sha256', hashlib.sha256(open(p, 'rb').read()).hexdigest())
    print('\n'.join(L[:40]))


if __name__ == '__main__':
    main()
