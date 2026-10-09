"""PLAN-COURSE 報告：results/*.json → results/REPORT.md（給人看）＋ results/course_site.json（網站說明框用）。
用法：python report_course.py"""
import json, os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'results')


def J(name):
    with open(os.path.join(OUT, name), encoding='utf-8') as fh:
        return json.load(fh)


def pct(x, nd=1, sign=True):
    if x is None or (isinstance(x, float) and x != x):
        return '—'
    return f'{x * 100:+.{nd}f}%' if sign else f'{x * 100:.{nd}f}%'


def pw(x):
    return '—' if x is None or x != x else f'{x * 100:.0f}%'


def exit_desc(e):
    if e.startswith('E1_'):
        return f'固定抱 {e[3:-1]} 個交易日'
    if e.startswith('E2_'):
        return '收盤站上 5 日線或 RSI2 > 70 出場（最多 10 天）'
    if e.startswith('E3_'):
        _, t, s, m = e.split('_')
        return f'停利 +{t[1:]} 倍 ATR、停損 −{s[1:]} 倍 ATR（收盤判斷，最多 {m[:-1]} 天）'
    if e.startswith('E4_'):
        return '收盤跌破 20 日線出場（最多 60 天）'
    if e.startswith('E6_'):
        _, s, t, m = e.split('_')
        return f'固定停損 {s[1:]}%' + (f'、停利 {t[1:]}%' if t != 't0' else '') + f'（收盤判斷，最多 {m[:-1]} 天）'
    if e.startswith('E7c_'):
        return f'固定停損 {e.split("_s")[1]}%、沒跌破一直抱（收盤判斷，最多 250 天）'
    if e == 'S_struct60':
        return '結構停損（波段低點／平台低點／0.618 線），收盤跌破就出（最多 60 天）'
    if e.startswith('X1_'):
        return f'放空固定 {e[3:-1]} 天回補'
    if e.startswith('X2_'):
        _, s, m = e.split('_')
        return f'收盤漲過進場價 {s[1:]}% 停損回補（最多 {m[:-1]} 天）'
    if e.startswith('X3_'):
        return f'收盤站回 {e[5:]} 日線回補（最多 40 天）'
    return e


FILTER = {'none': '不加濾網', 'tx60': '加權在 60 日線上才做', 'c60': '個股在 60 日線上才做',
          'c60dn': '個股在季線下才空', 'tx60dn': '加權在季線下才空'}


def var_desc(v):
    p = v.split('_')
    if p[0] == 'NB':
        k, vm, pull, ra = int(p[1][1:]), float(p[2][1:]), float(p[3][1:]), float(p[4][1:])
        return (f'突破前高（{"a 點：短波段 k=3" if k == 3 else "A 點：大波段 k=8"}）、回檔 ≥ {pull * 100:.0f}%'
                + ('、量 ≥ 前 20 日均量 1.5 倍' if vm else '') + ('、前一段漲 ≥ 20%（N 字）' if ra else ''))
    if p[0] == 'BR':
        return f'底部起漲：爆量 ≥ {p[1][1:]} 倍、平台寬 ≤ {float(p[2][1:]) * 100:.0f}%、平台均量 ≤ 爆量 × {p[3][1:]}、突破量 ≥ 平台均量 × {p[4][1:]}'
    if p[0] == 'ST':
        return f'最近 {p[2][1:]} 個波段低點都高於前高（k={p[1][1:]}）、' + ('低點確認那天' if p[3] == 'confirm' else '收盤突破最近高點')
    if p[0] == 'FB':
        return f'上漲 ≥ {float(p[1][1:]) * 100:.0f}% 後回檔到 {p[2][1:]}、' + ('紅 K' if p[3] == 'red' else '紅 K 且收盤 > 前一天最高')
    if p[0] == 'DB':
        return f'跌破前低（{"d 點 k=3" if p[1] == "k3" else "D 點 k=8"}）' + ('、量 ≥ 1.5 倍' if p[2] != 'v0' else '')
    return v


SITE_KEY = {'NB': 'S_NBREAK', 'BR': 'S_THUNDER', 'ST': 'S_STRONG', 'FB': 'S_FIB'}


def main():
    L, S = J('long_summary.json'), J('short_summary.json')
    LO, DI, SE, MK, DT, DP = (J(f) for f in ('limit_summary.json', 'dist_summary.json', 'sector_summary.json',
                                              'market_summary.json', 'daytrade_summary.json', 'disp_summary.json'))
    MC = J('merge_compare.json')
    site = {'period': {'is': '2021-10～2024-06', 'oos': '2024-07～2026-08'}, 'strategies': {}, 'items': {}}
    md = ['# 講義策略研究（PLAN-COURSE）', '',
          '- 資料：5 年官方日行情（含下市）、官方除權息表；股票池＝收盤 ≥ 10、20 日均量 ≥ 500 張、≥ 120 根、近 60 根沒有除權息跳動。',
          '- 樣本內 2021-10～2024-06 挑參數，樣本外 2024-07～2026-08 驗證；成本 買 0.2425%、賣 0.5425%（含稅、滑價），放空另加借券費 0.08%。',
          '- 通過＝樣本外平均 > 0、勝率比隨機進場高 5 點、跟隨機比的平均差距（依月份 bootstrap）95% 下限 > 0；合併類另外要比原本好。',
          '- **跟計畫不同的地方**：第一次跑依「樣本內平均每筆」挑參數，四個做多策略都挑到「停損 20% 一直抱」（等於吃大盤多頭）；'
          '改成依「樣本內超額報酬＝平均 − 同月份隨機進場平均（同出場、同濾網）」挑。兩種挑法的結論一樣：都沒通過。', '']
    # ── 總表 ──
    rows = []
    for pre in ('NB', 'BR', 'ST', 'FB'):
        v = L[pre]
        p = v.get('pick') or {}
        rows.append((v['title'], f"{pw(p.get('oos_win'))}／{pct(p.get('oos_mean'))}（{int(p.get('oos_n') or 0)} 筆）",
                     f"{pw((v.get('random') or {}).get('win'))}／{pct((v.get('random') or {}).get('mean'))}",
                     '✅' if v.get('passed') else '✗ ' + '；'.join(v.get('reasons', [])[:2])))
    md += ['## 總表', '', '| 項目 | 樣本外 勝率／平均每筆 | 隨機進場（同出場） | 結果 |', '|---|---|---|---|']
    md += [f'| {a} | {b} | {c} | {d} |' for a, b, c, d in rows]
    sp = S.get('pick') or S.get('best_any') or {}
    md.append(f"| 跌破前低放空 | {pw(sp.get('oos_win'))}／{pct(sp.get('oos_mean'))}（{int(sp.get('oos_n') or 0)} 筆） | — | ✗ {'；'.join(S.get('reasons', []))} |")
    md.append('')
    # ── 做多策略細節 ──
    for pre in ('NB', 'BR', 'ST', 'FB'):
        v = L[pre]
        p = v.get('pick') or {}
        rnd = v.get('random') or {}
        port = v.get('port') or {}
        md += [f"## {v['title']}", '',
               f"- 測了 {v['n_variants']} 組條件 × 3 種濾網 × 20 種出場＝{v['n_tested']} 組。",
               f"- 挑出：{var_desc(p.get('variant', ''))}；{FILTER.get(p.get('filter'), p.get('filter'))}；{exit_desc(p.get('exit', ''))}。",
               f"- 樣本內 {int(p.get('is_n') or 0)} 筆、勝率 {pw(p.get('is_win'))}、平均 {pct(p.get('is_mean'))}（超額 {pct(p.get('is_excess'))}）；"
               f"樣本外 {int(p.get('oos_n') or 0)} 筆、勝率 {pw(p.get('oos_win'))}、平均 {pct(p.get('oos_mean'))}（超額 {pct(p.get('oos_excess'))}）。",
               f"- 隨機進場（同出場、同月份筆數，20 次）樣本外：勝率 {pw(rnd.get('win'))}、平均 {pct(rnd.get('mean'))}；"
               f"跟隨機比的差距 bootstrap 95% 下限 {pct((v.get('boot_vs_random') or {}).get('lo95'))}。",
               f"- 帳戶模擬（10 檔各 10%）：年化 {pct(port.get('cagr'))}、最大回撤 {pct(port.get('mdd'))}（同期加權約 +23%／年）。",
               f"- 同一組訊號用網站 K 線回測預設出場：樣本外勝率 {pw((v.get('pick_e0') or {}).get('win'))}、平均 {pct((v.get('pick_e0') or {}).get('mean'))}。",
               f"- 結果：{'✅ 通過' if v.get('passed') else '✗ ' + '；'.join(v.get('reasons', []))}"]
        tw = v.get('top_win_alt')
        if tw:
            md.append(f"- 只看勝率的話（樣本內勝率最高的合格組合）：{var_desc(tw['variant'])}；{FILTER.get(tw['filter'])}；{exit_desc(tw['exit'])} → "
                      f"樣本內勝率 {pw(tw['is_win'])}、樣本外勝率 {pw(tw['oos_win'])}、平均 {pct(tw['oos_mean'])}。")
        md.append('')
        site['strategies'][SITE_KEY[pre]] = {
            'title': v['title'], 'useful': bool(v.get('passed')),
            'pick': {'desc': var_desc(p.get('variant', '')), 'filter': FILTER.get(p.get('filter')), 'exit': exit_desc(p.get('exit', '')),
                     'is_n': p.get('is_n'), 'is_win': p.get('is_win'), 'is_mean': p.get('is_mean'),
                     'oos_n': p.get('oos_n'), 'oos_win': p.get('oos_win'), 'oos_mean': p.get('oos_mean'), 'oos_excess': p.get('oos_excess')},
            'random': rnd, 'boot_lo95': (v.get('boot_vs_random') or {}).get('lo95'), 'port': {'cagr': port.get('cagr'), 'mdd': port.get('mdd')},
            'reasons': v.get('reasons', []), 'n_tested': v['n_tested'],
            'top_win': ({'desc': var_desc(tw['variant']), 'filter': FILTER.get(tw['filter']), 'exit': exit_desc(tw['exit']),
                         'oos_win': tw['oos_win'], 'oos_mean': tw['oos_mean']} if tw else None)}
    # ── 合併：原本 vs 新版（同出場）──
    md += ['## 合併類：原本 vs 新版（同一個濾網＋出場比）', '']
    for pre, title in (('NB', 'N 字突破 vs 突破前高'), ('BR', '平地一聲雷 vs 底部起漲 vs 量滾量')):
        md += [f'### {title}', '', '| 濾網｜出場 | ' + ' | '.join(MC[pre]['compare'][next(iter(MC[pre]['compare']))].keys()) + ' |',
               '|---|' + '---|' * len(MC[pre]['compare'][next(iter(MC[pre]['compare']))])]
        comp_rows = []
        for key, gs in MC[pre]['compare'].items():
            if 'S_struct60' in key:
                continue
            fk, ek = key.split('|')
            cells = []
            for g, x in gs.items():
                o = x['oos']
                lo = x.get('boot_vs_orig_lo95')
                cells.append(f"{pw(o.get('win'))}／{pct(o.get('mean'))}（{o.get('n', 0)}）" + (f"<br>vs 原本下限 {pct(lo)}" if lo is not None else ''))
            md.append(f"| {FILTER.get(fk)}｜{exit_desc(ek)} | " + ' | '.join(cells) + ' |')
            comp_rows.append({'filter': FILTER.get(fk), 'exit': exit_desc(ek),
                              'groups': {g: {'n': x['oos'].get('n'), 'win': x['oos'].get('win'), 'mean': x['oos'].get('mean'),
                                             'lo_vs_orig': x.get('boot_vs_orig_lo95')} for g, x in gs.items()}})
        md.append('')
        site['strategies'][SITE_KEY[pre]]['merge'] = comp_rows
    site['strategies']['S_NBREAK']['decision'] = ('突破前高版跟原本同出場比，平均略好但差距不顯著（bootstrap 下限 < 0），也沒勝過隨機進場 → '
                                                  '網站的 N 字突破維持原本條件。')
    site['strategies']['S_THUNDER']['decision'] = ('底部起漲子型比原本平地一聲雷差 → 沒併入；底部量滾量跟平地一聲雷差不多（點估計略好、不顯著）→ '
                                                   '照你的要求併進平地一聲雷（結果標「盤整突破／底部量滾量」）。三個都沒勝過隨機進場。')
    site['strategies']['S_STRONG']['decision'] = '新增策略；5 年回測沒通過（樣本外勝率、跟隨機比都不顯著），照實標示。'
    site['strategies']['S_FIB']['decision'] = '新增策略；5 年回測沒通過，照實標示。'
    # ── 放空 ──
    md += ['## 跌破前低（d／D 點）放空', '', f"- 測了 {S['n_tested']} 組；樣本內沒有任何組合是賺的（多頭年放空，平均每筆都 < 0）。",
           f"- 樣本內超額最高的一組：{var_desc(sp.get('variant', ''))}；{FILTER.get(sp.get('filter'))}；{exit_desc(sp.get('exit', ''))} → "
           f"樣本外 {int(sp.get('oos_n') or 0)} 筆、勝率 {pw(sp.get('oos_win'))}、平均 {pct(sp.get('oos_mean'))}。", '']
    site['strategies']['S_DBREAK'] = {'title': '跌破前低（d／D 點）放空', 'useful': False, 'n_tested': S['n_tested'],
                                      'pick': {'desc': var_desc(sp.get('variant', '')), 'filter': FILTER.get(sp.get('filter')), 'exit': exit_desc(sp.get('exit', '')),
                                               'oos_n': sp.get('oos_n'), 'oos_win': sp.get('oos_win'), 'oos_mean': sp.get('oos_mean'),
                                               'is_n': sp.get('is_n'), 'is_win': sp.get('is_win'), 'is_mean': sp.get('is_mean')},
                                      'reasons': S.get('reasons', []), 'decision': '新增策略（放空區）；5 年回測放空不賺，照實標示。'}
    # ── 漲停打開 ──
    g = pd.read_csv(os.path.join(OUT, 'grid_LO.csv'))
    md += ['## 連續跳空漲停後爆量打開（短線爆擊）', '',
           '- 事件：前面連續 n 天「開盤跳空 ≥ 5% 且收漲停」，今天爆量（≥ 昨量 m 倍）打開。業績前提＝當天已公布的最近月營收年增 ≥ 20%（次月 13 日起才算公布）。',
           '- 出場「停損＝打開當天最低」：打開當天收盤買，之後收盤跌破當天最低就賣，最多 10 天。', '',
           '| 條件 | 不看業績 樣本外 筆數／平均 | 月營收年增 ≥ 20% | 累計營收年增 ≥ 20% |', '|---|---|---|---|']
    for vname in sorted(g.variant.unique()):
        s = g[(g.variant == vname) & (g.exit == 'c_stop10')].set_index('fund')
        cell = lambda f: f"{int(s.at[f, 'oos_n'])} 筆／{pct(s.at[f, 'oos_mean'])}" if f in s.index else '—'
        n, m, op = vname.split('_')[1:]
        md.append(f"| 連 {n[1:]} 天、量 ≥ {m[1:]} 倍、{'盤中打開也算' if op == 'touch' else '收盤沒鎖'} | {cell('none')} | {cell('yoy20')} | {cell('cum20')} |")
    lo_rec = g[(g.variant == 'LO_n2_m3_touch') & (g.exit == 'c_stop10')].set_index('fund')
    lo3 = g[(g.variant == 'LO_n3_m3_touch') & (g.exit == 'c_stop10')].set_index('fund')
    md += ['', '- 讀法：幾乎每一組「加業績前提」都比不看業績好（樣本外每筆多 1～2 個百分點）；連 3 天以上的比連 2 天好。勝率只有 3～4 成，'
           '賺的時候大（p95 約 +30%），中位數是虧的 → 適合小金額、嚴守停損。樣本數少（幾十～兩百筆），屬於探索性結果。', '']
    site['strategies']['S_LIMIT_OPEN'] = {
        'title': '連續跳空漲停後爆量打開', 'useful': False, 'explore': True,
        'text': (f"打開當天收盤買、收盤跌破當天最低就賣（最多 10 天）：連 2 天＋月營收年增 ≥ 20% 樣本外 {int(lo_rec.at['yoy20', 'oos_n'])} 筆、"
                 f"平均 {pct(lo_rec.at['yoy20', 'oos_mean'])}（不看業績 {pct(lo_rec.at['none', 'oos_mean'])}）；連 3 天＋營收年增 {int(lo3.at['yoy20', 'oos_n'])} 筆、"
                 f"平均 {pct(lo3.at['yoy20', 'oos_mean'])}。業績前提每一組都有幫助，但樣本少、勝率 3～4 成（賺的時候大），屬探索性結果。"),
        'table': [{'variant': r.variant, 'fund': r.fund, 'oos_n': r.oos_n, 'oos_mean': r.oos_mean, 'oos_win': r.oos_win}
                  for r in g[g.exit == 'c_stop10'].itertuples()]}
    # ── 出貨日 ──
    o, i_ = DI['oos'], DI['is']
    md += ['## 出貨日（下跌出量／量大不漲）', '',
           '| 期間 | 種類 | 次數 | 之後 10 天平均 | 之後 20 天平均 | 20 天內跌 ≥ 10% 的比例 |', '|---|---|---|---|---|---|']
    for per, d in (('樣本內', i_), ('樣本外', o)):
        for k, lab in (('downvol', '下跌出量'), ('stall', '量大不漲'), ('control', '同樣高檔、沒出貨日（對照）')):
            x = d[k]
            md.append(f"| {per} | {lab} | {x['n']} | {pct(x['f10'], 2)} | {pct(x['f20'], 2)} | {pw(x['dd10'])} |")
    md += ['', f"- 出貨日之後 10 天平均比對照少一點（樣本外差距 95% 區間 {pct(o['diff_f10_ci'][0], 2)}～{pct(o['diff_f10_ci'][1], 2)}，包含 0），"
           '20 天內大跌的比例高約 5 個百分點 → 有一點點「風險變高」的味道，但不是可靠的賣出訊號。', '']
    site['items']['dist'] = {'useful': False, 'text': (f"出貨日之後 10 天平均 {pct(o['any']['f10'], 2)}，同樣高檔沒出貨日 {pct(o['control']['f10'], 2)}（差距不顯著）；"
                                                       f"20 天內跌 ≥ 10% 的比例 {pw(o['any']['dd10'])} vs {pw(o['control']['dd10'])}。當提醒用，不是賣出訊號。")}
    # ── 族群 ──
    md += ['## 主流族群同步大跌', '', '| 期間 | 情況 | 次數 | 之後 5 天族群平均 | 10 天 | 20 天 |', '|---|---|---|---|---|---|']
    for per, lab in (('is', '樣本內'), ('oos', '樣本外')):
        for k, nm in (('main_crash', '主流族群同步大跌'), ('main_normal', '主流族群平常日'), ('any_crash', '非主流族群同步大跌')):
            x = SE[per][k]
            md.append(f"| {lab} | {nm} | {x['n']} | {pct(x['f5'])} | {pct(x['f10'])} | {pct(x['f20'])} |")
    md += ['', '- 樣本內大跌後 10 天略差（−0.6%），樣本外反而大漲（+8.4%，20 次裡 19 次漲）→ 兩段方向相反、次數少，沒有穩定的預測力；'
           '「主流股一起大跌」比較像短線恐慌，不代表之後會續跌。', '']
    site['items']['sector'] = {'useful': False, 'text': (f"主流族群同步大跌後 10 天：樣本內 {pct(SE['is']['main_crash']['f10'])}（{SE['is']['main_crash']['n']} 次）、"
                                                         f"樣本外 {pct(SE['oos']['main_crash']['f10'])}（{SE['oos']['main_crash']['n']} 次）；兩段方向相反，沒有穩定的預測力，當提醒用。")}
    # ── 大盤 ──
    k3 = MK['k3']
    md += ['## 大盤出貨日（過熱指數 > 50%＋加權跌破 d 點）', '',
           f"- 過熱指數（收盤累計成交量 ÷ 委買量）5 年中位數 {MK['ratio_quantiles']['50']:.2f}，> 0.5 的日子 {pw(MK['ratio_pct_over_0.5'])}。",
           f"- 出貨日（k=3）5 年只有 {k3['dist_day']['n']} 次：" + '、'.join(f"{e['date'][:4]}/{e['date'][4:6]}/{e['date'][6:]}（10 天後 {pct(e['f10'])}）" for e in k3['events']) + '。',
           f"- 之後 10 天加權平均 {pct(k3['dist_day']['f10'])}（全部日子 {pct(k3['all_days']['f10'])}）、20 天內最大跌幅平均 {pct(k3['dist_day']['dd20'])}"
           f"（全部 {pct(k3['all_days']['dd20'])}）→ 這 5 年多頭裡沒有警示效果；次數太少，無法下結論。", '']
    site['items']['market'] = {'useful': False, 'events': k3['events'],
                               'text': f"5 年只有 {k3['dist_day']['n']} 次，之後 10 天加權平均 {pct(k3['dist_day']['f10'])}（全部日子 {pct(k3['all_days']['f10'])}）；多頭期沒有警示效果、次數太少，當參考。"}
    # ── 當沖 ──
    md += ['## 盤前當沖多空名單（日線代理）', '', f"- 成本：手續費兩邊＋當沖稅 0.15%＋滑價＝{DT['cost'] * 100:.2f}%（沒算券商折扣）。",
           '| 名單 | 樣本外 筆數 | 勝率 | 隔天開盤→收盤平均（扣成本） | 開盤後最大有利空間平均 | 隨機（同股票池） |', '|---|---|---|---|---|---|']
    for k, lab, rk in (('long', '多（剛起漲）', 'rand_long'), ('long_mkt', '多＋順大盤', 'rand_long'), ('short', '空（剛起跌）', 'rand_short'), ('short_mkt', '空＋順大盤', 'rand_short')):
        x, r = DT[k]['oos'], DT[rk]['oos']
        md.append(f"| {lab} | {x['n']} | {pw(x['win'])} | {pct(x['mean'], 2)} | {pct(x['mfe_mean'], 2)} | {pw(r['win'])}／{pct(r['mean'], 2)} |")
    md += ['', '- 開盤買、收盤賣的話，名單股比隨機還差（多方 −1.1%／筆）：前一天大漲的隔天開高走低居多。名單只適合當「今天要盯的股票」，'
           '進出點要看盤中 5／15 分 K（日線沒辦法回測）。', '']
    site['items']['daytrade'] = {'useful': False, 'text': (f"隔天開盤買、收盤賣（扣 {DT['cost'] * 100:.2f}% 成本）：多方名單樣本外平均 {pct(DT['long']['oos']['mean'], 2)}、"
                                                           f"空方 {pct(DT['short']['oos']['mean'], 2)}，都比隨機差；開盤後最大有利空間平均 {pct(DT['long']['oos']['mfe_mean'], 1)}。"
                                                           "名單只當盯盤清單，進出點要看盤中分 K。")}
    # ── 二次處置 ──
    ea, eb = DP['Ea_second_disposal'], DP['Eb_up5_after_first']
    md += ['## 二次處置放空', '', '| 事件 | 次數 | 放空 5 天 樣本外 勝率／平均 | 熱門股隨機放空 5 天 | 放空 10 天 樣本外 |', '|---|---|---|---|---|']
    for nm, e in (('第二次（再次）處置公告後隔天空', ea), ('第一次處置後連漲 5 天（門檻附近）', eb)):
        x5, x10 = e['X1_5d'], e['X1_10d']
        md.append(f"| {nm} | {e['events']} | {pw(x5['oos'].get('win'))}／{pct(x5['oos'].get('mean'))} | "
                  f"{pw((x5['random_hot_oos'] or {}).get('win'))}／{pct((x5['random_hot_oos'] or {}).get('mean'))} | "
                  f"{pw(x10['oos'].get('win'))}／{pct(x10['oos'].get('mean'))} |")
    md += ['', '- 兩種放空都是虧的（處置股、熱門股在多頭裡常常續漲）；處置期間還要預收款券，實際更難空。', '']
    site['items']['disp2'] = {'useful': False, 'text': (f"第一次處置後連漲 5 天放空 5 天：樣本外平均 {pct(eb['X1_5d']['oos'].get('mean'))}（熱門股隨機放空 "
                                                        f"{pct((eb['X1_5d']['random_hot_oos'] or {}).get('mean'))}）；二次處置公告後放空 {pct(ea['X1_5d']['oos'].get('mean'))}。放空都不賺，照實標示。")}
    md += ['## 限制', '', '- 產業分類用現在的對照表；放空沒模擬券源、強制回補、平盤下不能空；當沖只能用日線代理；漲停打開用收盤價近似盤中買點。',
           '- 樣本內挑參數一定偏樂觀，所以只看樣本外＋隨機對照；Bonferroni（8 個策略）99.4% 下限全部 < 0。', '']
    with open(os.path.join(OUT, 'REPORT.md'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(md))
    with open(os.path.join(OUT, 'course_site.json'), 'w', encoding='utf-8') as fh:
        json.dump(site, fh, ensure_ascii=False, indent=1, default=lambda o: None if o != o else str(o))
    print('ok', len(md))


if __name__ == '__main__':
    main()
