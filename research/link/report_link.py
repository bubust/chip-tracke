"""PLAN-LINK 報告：results/*_summary.json → results/REPORT.md（中文）＋ link_conclusions.json（網站讀）
「有效」＝主要假設樣本內外都 > 0、事件 ≥ 30、BH 校正後 p < 0.05；其他一律標「沒有優勢／探索性」"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, 'results')
P = lambda x: '—' if x is None else f'{x * 100:+.2f}%'
W = lambda x: '—' if x is None else f'{x * 100:.0f}%'


def load(n):
    return json.load(open(os.path.join(RES, n), encoding='utf-8'))


def useful(r):
    return bool(r and r.get('sufficient') and (r.get('is_mean') or 0) > 0 and (r.get('oos_mean') or 0) > 0 and (r.get('p_bh') or 1) < 0.05)


def main():
    sec, fol, dis = load('sector_summary.json'), load('follow_summary.json'), load('disposal_summary.json')
    L = ['# 產業輪動規律、股票連動、處置股雙刀 — 研究報告（PLAN-LINK）', '',
         '- 資料：證交所＋櫃買官方日行情 2021-10～2026-10（含下市股、官方除權息表）；處置／注意：證交所 punish／notice、櫃買 disposal／attention（2021-01 起）。',
         '- 樣本內 2021-10～2024-06、樣本外 2024-07～2026-08；成本 來回約 0.785%（含滑價）；股票池 20 日均量 ≥ 500 張、股價 ≥ 10 元。',
         '- 「有效」＝事先定好的主要假設，樣本內外都賺、事件 ≥ 30 次、多重比較（Benjamini-Hochberg）校正後 p < 0.05。', '']
    # 產業輪動
    s_all = {r['event']: r for r in sec['summary'] if r['subset'] == 'all'}
    s_st = {r['event']: r for r in sec['summary'] if r['subset'] == 'stable'}
    L += ['## 1. 產業輪動狀態有沒有預測力（產業指數之後 20 天比全部產業平均多賺多少）', '',
          '| 事件 | 次數 | 樣本內 | 樣本外 | 全期勝率 | 隨機基準 | 校正後 p（全部／排除新分類） |', '|---|---|---|---|---|---|---|']
    names = {'H1_range_to_bull': '盤整轉多頭（主要假設）', 'H2_emerging_leader': '新興領頭（主要假設）', 'X_bear_to_range': '空頭轉盤整',
             'X_regime_bull_strong': '變成多頭強勢', 'X_false_breakdown_turn': '假跌破翻轉', 'X_strong_leader': '強勢領頭',
             'X_leader_failure': '領頭失敗', 'X_strengthening_top3rd': '排名轉強（前 1/3）', 'X_ev_breakout': '產業指數突破前高',
             'X_ev_reclaim': '跌破後站回', 'X_ev_false_breakdown': '假跌破（結構事件）'}
    for k, r in s_all.items():
        st = s_st.get(k, {})
        L.append(f"| {names.get(k, k)} | {r['n']} | {P(r.get('is_mean20'))} | {P(r.get('oos_mean20'))} | {W(r.get('all_win20'))} | {P(r.get('rand_mean20'))}／{W(r.get('rand_win20'))} | {r.get('p20_bh', 1):.2f}／{st.get('p20_bh', 1):.2f} |")
    sec_useful = [k for k in ('H1_range_to_bull', 'H2_emerging_leader') if s_all.get(k) and (s_all[k].get('p20_bh') or 1) < 0.05
                  and (s_all[k].get('is_mean20') or 0) > 0 and (s_all[k].get('oos_mean20') or 0) > 0]
    h1 = s_all['H1_range_to_bull']
    sec_text = (f"盤整轉多頭之後 20 天，產業只比全部產業平均多 {P(h1['all_mean20'])}、勝率 {W(h1['all_win20'])}"
                f"（隨機產業日 {P(h1['rand_mean20'])}／{W(h1['rand_win20'])}），校正後不顯著；其他狀態也都沒有可用的優勢。"
                "產業輪動適合看「現在誰強」，不適合當進場訊號。")
    L += ['', '**結論**：' + sec_text, '']
    # 跟進第二名
    fs = {(r['variant'], r['rule']): r for r in fol['summary']}
    f1 = fs.get(('F1', 'H5'))
    L += ['## 2. 龍頭先發動 → 跟進第二名', '', f"- 先發動事件 {fol['n_events']} 次（漲 ≥ 5%、創 20 日新高、量 ≥ 2 倍、同產業 10 天內第一個）", '',
          '| 做法 | 持有 | 次數 | 樣本內 平均／勝率 | 樣本外 平均／勝率 | 校正後 p |', '|---|---|---|---|---|---|']
    vn = {'F1': '買相關最高、還沒漲的那檔（主要）', 'F2': '買同產業今天漲幅第二名', 'F3': '候選全部等權', 'RAND_SECTOR': '同產業隨便一檔（對照）'}
    for (v, rk), r in sorted(fs.items()):
        if v == 'RAND_DAY':
            continue
        L.append(f"| {vn.get(v, v)} | {rk} | {r['n']} | {P(r.get('is_mean'))}／{W(r.get('is_win'))} | {P(r.get('oos_mean'))}／{W(r.get('oos_win'))} | {r.get('p_bh', float('nan')):.2f} |")
    fol_text = (f"龍頭先發動後隔天開盤買跟它相關最高、還沒漲的同產業股抱 5 天：樣本內 {P(f1['is_mean'])}、樣本外 {P(f1['oos_mean'])}（扣成本），"
                "勝率約 3 成，跟同產業隨便挑一檔差不多 → 跟進第二名沒有優勢，不建議照做；清單只當資訊看。")
    L += ['', '**結論**：' + fol_text, '']
    # 處置股
    fam = {r['name']: r for r in dis['family']}
    prim = fam.get('peer_posdev_to_release（主要）')
    L += ['## 3. 處置股（雙刀）', '', f"- 處置事件 {dis['n_events']} 次（有價格、在期間內的 {dis['n_used']} 次）", '',
          '### 處置前後每天（平均漲跌／紅 K 比例；樣本內外都很接近）', '', '| 相對日 | 第一次處置 | 再次／第二次處置 |', '|---|---|---|']
    order = ['處置前3', '處置前2', '處置前1', '處置第1天', '處置第2天', '處置第3天', '處置第4天', '處置第5天', '出關前3', '出關前2', '處置最後一天',
             '出關後1', '出關後2', '出關後3', '出關後4', '出關後5']
    rd = {(r['rel'], r['first']): r for r in dis['relative_days']}
    rel_tbl = []
    for k in order:
        a, b = rd.get((k, True)), rd.get((k, False))
        L.append(f"| {k} | {P(a and a['mean'])}／{W(a and a['red'])} | {P(b and b['mean'])}／{W(b and b['red'])} |")
        rel_tbl.append({'rel': k, 'first_mean': a and a['mean'], 'first_red': a and a['red'], 'repeat_mean': b and b['mean'], 'repeat_red': b and b['red']})
    L += ['', '### 做法', '', '| 做法 | 次數 | 樣本內 平均／勝率 | 樣本外 平均／勝率 | 校正後 p |', '|---|---|---|---|---|']
    dn = {'peer_posdev_to_release（主要）': '處置第 1 天買高相關配對股（處置股正偏差）抱到出關，比同產業平均（主要）',
          'short_pair_cost0.002': '雙刀：空處置股＋多配對股（第一次處置、放空成本 0.2%）',
          'release_buy_H20': '出關後買（處置期間有跌）抱 20 天', 'release_buy_H20_negdev': '出關後買＋負偏差率 抱 20 天',
          'release_buy_S7_negdev': '出關後買＋負偏差率、7% 停損', 'release_buy_H20_ma20up_bb04': '出關後買＋月線上彎＋布林 %b < 0.4 抱 20 天'}
    for k, lab in dn.items():
        r = fam.get(k)
        if r:
            L.append(f"| {lab} | {r['n']} | {P(r.get('is_mean'))}／{W(r.get('is_win'))} | {P(r.get('oos_mean'))}／{W(r.get('oos_win'))} | {r.get('p_bh', 1):.2f} |")
    sp = fam.get('short_pair_cost0.002')
    rb = fam.get('release_buy_H20_negdev')
    dis_text = (f"主要假設（處置時買高相關配對股）比同產業平均多 {P(prim['mean'])}，校正後不顯著；"
                f"講義的雙刀（空處置股＋多配對股）平均每組 {P(sp['mean'])}，處置期間處置股常常不跌反漲，散戶也很難空到 → 不建議。"
                f"最有希望的是「出關後買、處置股比配對股便宜（負偏差）」：抱 20 天 {P(rb['mean'])}（{rb['n']} 次，樣本內外都正），"
                "但次數少、校正後還不顯著 → 標探索性。處置前後每天的統計（出關前 2 天偏強、第一次處置出關第一天偏弱）跟講義一致，可以參考。")
    L += ['', '**結論**：' + dis_text, '', '## 限制', '',
          '- 產業分類用現在的回推 5 年（排除 2023 新分類的結果一致）；處置期間流動性差、滑價可能更大；放空版假設能融券；事件數有限。', '']
    open(os.path.join(RES, 'REPORT.md'), 'w', encoding='utf-8').write('\n'.join(L))
    concl = {
        'sector': {'useful': bool(sec_useful), 'text': sec_text, 'detail': '產業指數＝成員等權；事件第 t 天成立、從 t+1 收盤起算 20 天，減全部產業平均；月份 bootstrap＋BH 校正；排除 2023 新設分類結果一致。'},
        'follow': {'useful': useful(f1), 'text': fol_text,
                   'detail': f"5 年 {fol['n_events']} 次先發動；主要假設 F1 抱 5 天 n={f1['n']}，樣本內 {P(f1['is_mean'])}、樣本外 {P(f1['oos_mean'])}；同產業隨機一檔對照差不多；BH 校正後 p={f1.get('p_bh', 1):.2f}。"},
        'disposal': {'useful': useful(prim), 'text': dis_text, 'relative_days': rel_tbl,
                     'detail': f"處置事件 {dis['n_events']} 次；主要假設 n={prim['n']}，樣本內 {P(prim.get('is_mean'))}、樣本外 {P(prim.get('oos_mean'))}，BH p={prim.get('p_bh', 1):.2f}；出關買＋負偏差 n={rb['n']}，BH p={rb.get('p_bh', 1):.2f}。"},
    }
    json.dump(concl, open(os.path.join(RES, 'link_conclusions.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    print('\n'.join(L[:12]))
    print({k: v['useful'] for k, v in concl.items()})


if __name__ == '__main__':
    main()
