"""把 results/report.json＋grid.csv 寫成中文報告 REPORT.md，並產生網站用的 summary.json。
用法：python report.py（run.py 跑完之後）"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import pandas as pd

OUT = os.path.join(HERE, 'results')


def strat_label(k):
    try:
        import scanner
        return re.sub(r'[（(].*$', '', scanner.STRATEGIES.get(k, k)).strip()
    except Exception:
        return k


def describe_signal(sk):
    m = re.match(r'B1_ma(\d+)_(rsi|dev|drop)([\d.]+)$', sk)
    if m:
        n, kind, k = m.groups()
        cond = {'rsi': f'RSI(2) ≤ {k}（短線超賣）', 'dev': f'收盤 ≤ 20 日線 − {k} 倍 ATR（短線跌深）',
                'drop': f'3 天跌幅 ≥ {k} 倍 ATR（急跌）'}[kind]
        return f'收盤在 {n} 日線上（長線多頭），而且{cond}'
    m = re.match(r'B2_pull_ma(\d+)$', sk)
    if m:
        return f'多頭排列（20 日線 > 60 日線、60 日線上彎）拉回：最低碰到 {m.group(1)} 日線、收盤收在線上'
    m = re.match(r'B3_brk(\d+)_v([\d.]+)$', sk)
    if m:
        return f'收盤突破前 {m.group(1)} 天最高收盤，量 ≥ 前 20 天均量 {m.group(2)} 倍'
    if sk == 'B4_deep_strong':
        return '深度分析技術分第一天到 32 分以上（轉強勢）'
    if sk == 'B5_gap':
        return '開盤跳空高於昨天最高 1% 以上、收紅 K、量 ≥ 前 20 天均量 2 倍'
    m = re.match(r'C4_strong_(rsi|dev)([\d.]+)$', sk)
    if m:
        kind, k = m.groups()
        cond = f'RSI(2) ≤ {k}' if kind == 'rsi' else f'收盤 ≤ 20 日線 − {k} 倍 ATR'
        return f'深度分析技術分 ≥ 32（強勢股），而且{cond}（強勢股短線超賣）'
    m = re.match(r'A_(.+)$', sk)
    if m:
        return f'現有策略「{strat_label(m.group(1))}」'
    m = re.match(r'C1_(.+)\+(.+)$', sk)
    if m:
        return f'「{strat_label(m.group(1))}」和「{strat_label(m.group(2))}」3 天內都出現（今天出現一個、另一個在今天或前 2 天）'
    m = re.match(r'C2_(.+)&(c60|c200|up)$', sk)
    if m:
        t = {'c60': '收盤在 60 日線上', 'c200': '收盤在 200 日線上', 'up': '20 日線 > 60 日線且 60 日線上彎'}[m.group(2)]
        return f'現有策略「{strat_label(m.group(1))}」＋{t}'
    m = re.match(r'C3_consensus(\d)$', sk)
    if m:
        return f'3 天內出現 ≥ {m.group(1)} 個不同的現有策略'
    return sk


def describe_regime(rk):
    return {'none': '不看大盤', 'tx60': '加權指數收盤在 60 日線上才做', 'tx200': '加權指數收盤在 200 日線上才做'}[rk]


def describe_exit(ek):
    m = re.match(r'E1_(\d+)d$', ek)
    if m:
        return f'固定抱 {m.group(1)} 個交易日（第 {int(m.group(1)) + 1} 個交易日開盤賣）'
    m = re.match(r'E2_ma5rsi_(\d+)d$', ek)
    if m:
        return f'收盤站上 5 日線或 RSI(2) > 70 → 隔天開盤賣；最多抱 {m.group(1)} 天'
    m = re.match(r'E3_t([\d.]+)_s([\d.]+)_(\d+)d$', ek)
    if m:
        a, b, d = m.groups()
        return f'停利：收盤 ≥ 買進價 + {a} 倍 ATR；停損：收盤 < 買進價 − {b} 倍 ATR（都是隔天開盤賣）；最多抱 {d} 天'
    m = re.match(r'E4_ma(\d+)$', ek)
    if m:
        return f'收盤跌破 {m.group(1)} 日線 → 隔天開盤賣；最多抱 60 天'
    m = re.match(r'E5_roll_(\d+)d$', ek)
    if m:
        return f'滾動停損（結構低點進場、平台低點上修，只上不下）收盤跌破 → 隔天開盤賣；最多抱 {m.group(1)} 天'
    return ek


def describe(combo):
    sk, rk, ek = combo.split('|')
    return {'signal': describe_signal(sk), 'regime': describe_regime(rk), 'exit': describe_exit(ek)}


P = lambda x: f'{x * 100:.1f}%' if x is not None and x == x else '—'
P2 = lambda x: f'{x * 100:+.2f}%' if x is not None and x == x else '—'


def stat_row(name, st):
    if not st or not st.get('n'):
        return f'| {name} | 0 | — | — | — | — | — |'
    return (f"| {name} | {st['n']:,} | {P(st['win'])} | {P2(st['mean'])} | {st['pf']:.2f} | {P2(st['p5'])} | "
            f"{st['days']:.1f} |" if st.get('days') is not None else
            f"| {name} | {st['n']:,} | {P(st['win'])} | {P2(st['mean'])} | {st['pf']:.2f} | {P2(st['p5'])} | — |")


def candidate_of(rep):
    """沒有主推時：檢查過的裡面最接近過關的（沒過的關卡最少、組合回撤最小）＝網站「研究候選」"""
    if rep.get('main') or not rep.get('checks'):
        return None
    return min(rep['checks'], key=lambda c: (len(c['reasons']), -min(c['port_slots']['mdd'], c['port_risk']['mdd'])))


def why(c, checks):
    """前 20 名的組合差在哪（樣本外標準、賺錢年數、後面三道關卡）"""
    out = []
    if c['oos_win'] is not None and c['oos_win'] < 0.6:
        out.append(f"樣本外勝率 {P(c['oos_win'])} < 60%")
    if c['oos_mean'] is not None and c['oos_mean'] <= 0:
        out.append(f"樣本外平均 {P2(c['oos_mean'])} ≤ 0")
    if c['oos_pf'] is not None and c['oos_pf'] < 1.3:
        out.append(f"樣本外 PF {c['oos_pf']:.2f} < 1.3")
    if c['oos_p5'] is not None and c['oos_p5'] < -0.15:
        out.append(f"樣本外最差 5% {P2(c['oos_p5'])} < −15%")
    if (c['oos_n'] or 0) < 100:
        out.append(f"樣本外只有 {int(c['oos_n'] or 0)} 筆")
    if c['years_pos'] < 4:
        out.append(f"只有 {c['years_pos']} 年賺錢")
    if c['combo'] in checks:
        out += checks[c['combo']]['reasons']
    return '；'.join(out) or '—'


def section(tag, chk, rep):
    if not chk:
        return []
    d = describe(chk['combo'])
    L = [f'### {tag}：`{chk["combo"]}`', '',
         f'- **進場**：{d["signal"]}；{d["regime"]}。第 t 天收盤出訊號 → 第 t+1 天**開盤買**（開盤一價漲停買不到就放棄）。',
         f'- **出場／停損**：{d["exit"]}。', '',
         '| 期間 | 筆數 | 勝率 | 平均每筆（扣成本） | 獲利因子 | 最差 5% | 平均持有天數 |', '|---|---|---|---|---|---|---|',
         stat_row('樣本內 2021-10～2024-06', chk['stats']['is']), stat_row('樣本外 2024-07～2026-08', chk['stats']['oos']),
         stat_row('全期', chk['stats']['all']), '',
         '各年（依訊號日）：' + '、'.join(f"{y} {P(v.get('win'))}／{P2(v.get('mean'))}（{v.get('n', 0)} 筆）" for y, v in chk['years'].items()), '',
         f"- 隨機基準（同樣出場、同月份隨機挑股票池裡的股票進場，20 次平均）：勝率 {P(chk['baseline']['win'])}、平均每筆 {P2(chk['baseline']['mean'])}",
         f"- 樣本外平均每筆 95% 信賴區間（依月份 bootstrap 2,000 次）：{P2(chk['boot_ci'][0])} ～ {P2(chk['boot_ci'][1])}",
         f"- 除權息後 3 天內的訊號比例：{P(chk['exdiv_share'])}" + ('（> 5%，已加「除權息後 3 天內不算」重算）' if chk.get('exdiv_rule') else ''),
         f"- 組合模擬（10 個名額等分資金）：年化 {P2(chk['port_slots']['cagr'])}、最大回撤 {P2(chk['port_slots']['mdd'])}、平均持股 {P(chk['port_slots']['exposure'])}、實際成交 {chk['port_slots']['taken']} 筆",
         f"- 組合模擬（每筆風險 1%）：年化 {P2(chk['port_risk']['cagr'])}、最大回撤 {P2(chk['port_risk']['mdd'])}、平均持股 {P(chk['port_risk']['exposure'])}",
         f"- 同期加權指數（價格指數、不含股利）：年化 {P2(rep['taiex']['cagr'])}、最大回撤 {P2(rep['taiex']['mdd'])}",
         ('- **檢查結果：通過**' if chk['pass'] else '- **檢查結果：沒通過** — ' + '；'.join(chk['reasons'])), '']
    nb = rep.get(f"{'main' if tag.startswith('主推') else 'alt'}_neighbors") or []
    if nb:
        L += ['相鄰參數（同一族訊號、同一類出場，依樣本內勝率）：', '',
              '| 組合 | 樣本內筆數 | 樣本內勝率 | 樣本內平均 | 樣本外筆數 | 樣本外勝率 | 樣本外平均 |', '|---|---|---|---|---|---|---|']
        for r in nb[:15]:
            L.append(f"| `{r['combo']}` | {int(r['is_n'] or 0):,} | {P(r['is_win'])} | {P2(r['is_mean'])} | {int(r['oos_n'] or 0):,} | {P(r['oos_win'])} | {P2(r['oos_mean'])} |")
        L.append('')
    return L


def main():
    rep = json.load(open(os.path.join(OUT, 'report.json'), encoding='utf-8'))
    L = ['# 勝率最高的選股方式 — 研究報告（PLAN-BEST）', '',
         f"- 資料：證交所＋櫃買官方日行情 2021-10-01～2026-10-08（2021-01～09 只當指標暖身），含之後下市的股票；報酬含除權息（官方除權息／減資表）。",
         '- 股票池（每天判斷）：4 碼普通股、收盤 ≥ 10 元、20 日均量 ≥ 500 張、至少 120 根 K 棒。',
         '- 交易：訊號隔天開盤買、出場條件收盤成立隔天開盤賣（用實際開盤價，跳空算在裡面）；成本 手續費 0.1425%×2＋證交稅 0.3%＋滑價每邊 0.1%（來回約 0.785%）；同一檔持有中不重複進場。',
         f"- 測了 **{rep['n_combos']:,} 個組合**（{rep['n_signals']} 個訊號 × {rep['n_regimes']} 種大盤濾網 × {rep['n_exits']} 種出場）。",
         f"- 合格標準（樣本內、樣本外都要）：勝率 ≥ 60%、平均每筆 > 0、獲利因子 ≥ 1.3、最差 5% ≥ −15%、筆數 樣本內 ≥ 200／樣本外 ≥ 100、2022～2026 至少 4 年平均賺錢；再加 隨機基準 +5 個百分點、bootstrap 下限 > 0、組合最大回撤 ≤ 30%。",
         f"- 樣本內合格 {rep['n_is_qualified']:,} 個 → 取前 20 名看樣本外 → **{rep['n_top20_oos_ok']} 個樣本外也合格**。", '']
    L += ['## 樣本內前 20 名', '', '| # | 組合 | 樣本內勝率 | 樣本內平均 | 樣本外勝率 | 樣本外平均 | 樣本外筆數 | 樣本外 PF | 賺錢年數 | 樣本外合格 |',
          '|---|---|---|---|---|---|---|---|---|---|']
    for i, c in enumerate(rep['top20'], 1):
        L.append(f"| {i} | `{c['combo']}` | {P(c['is_win'])} | {P2(c['is_mean'])} | {P(c['oos_win'])} | {P2(c['oos_mean'])} | {int(c['oos_n'] or 0):,} | {c['oos_pf']:.2f} | {c['years_pos']} | {'✅' if c['oos_ok'] else '✗'} |")
    L.append('')
    checks = {c['combo']: c for c in rep.get('checks') or []}
    if rep.get('main'):
        L += ['## 結果', ''] + section('主推（勝率最高、全部關卡通過）', checks[rep['main']], rep)
    else:
        L += ['## 結果：沒有任何組合通過全部關卡', '', '照事先定好的規則不放寬標準。以下是檢查過的候選與沒通過的原因：', '']
        for c in rep.get('checks') or []:
            L.append(f"- `{c['combo']}`：" + '；'.join(c['reasons']))
        L.append('')
    cand = candidate_of(rep)
    if cand:
        L += section('研究候選（最接近過關：只差組合回撤）', cand, rep)
    if rep.get('alt_check') and (not cand or rep['alt_check']['combo'] != cand['combo']):
        L += section('備選（樣本外平均每筆最高）', rep['alt_check'], rep)
    if not rep.get('main'):
        L += ['## 最接近的 5 個（樣本內前 20 名裡，依樣本外勝率）', '', '| 組合 | 樣本外勝率 | 樣本外平均 | 樣本外 PF | 樣本外最差 5% | 賺錢年數 | 差在哪 |', '|---|---|---|---|---|---|---|']
        near = sorted(rep['top20'], key=lambda c: (-c['oos_ok'], -(c['oos_win'] or 0)))[:5]
        for c in near:
            L.append(f"| `{c['combo']}` | {P(c['oos_win'])} | {P2(c['oos_mean'])} | {c['oos_pf']:.2f} | {P2(c['oos_p5'])} | {c['years_pos']} | {why(c, checks)} |")
        L.append('')
        grid = next((p for p in (os.path.join(OUT, 'grid.csv'), os.path.join(OUT, 'grid.csv.gz')) if os.path.exists(p)), None)
        if grid:
            g = pd.read_csv(grid)
            q = lambda p, n: (g[f'{p}_n'] >= n) & (g[f'{p}_win'] >= .6) & (g[f'{p}_mean'] > 0) & (g[f'{p}_pf'] >= 1.3) & (g[f'{p}_p5'] >= -.15)
            yrs = sum(((g[f'y{y}_mean'] > 0) & (g[f'y{y}_n'] > 0)).astype(int) for y in ('2022', '2023', '2024', '2025', '2026'))
            both = g[q('is', 200) & q('oos', 100) & (yrs >= 4)]
            L += [f"- 全部 {len(g):,} 個組合裡，樣本內、樣本外每筆統計都合格的只有 **{len(both)} 個**：" + '、'.join(f'`{c}`' for c in both.combo) + '。', '']
    diag_p = os.path.join(OUT, 'diag.json')
    if os.path.exists(diag_p):
        dg = json.load(open(diag_p, encoding='utf-8'))
        L += ['## 事後分析（不是選方法的依據）：' + f"`{dg['combo']}`", '',
              f"- 訊號很集中：最多的一天 {dg['max_signals_one_day']['date']} 有 {dg['max_signals_one_day']['n']} 個；訊號最多的 5 個月份佔全部 {P(dg['share_top5_months'])}（都是大跌之後）。",
              '- 崩盤第一波 vs 之後（訊號最多的 5 個月份，依進場日分前 1/3 天與其餘）：', '',
              '| 月份 | 訊號 | 第一波筆數 | 第一波勝率 | 第一波平均 | 之後筆數 | 之後勝率 | 之後平均 |', '|---|---|---|---|---|---|---|---|']
        for w in dg['waves']:
            L.append(f"| {w['month']} | {w['n']} | {w['first_n']} | {P(w['first_win'])} | {P2(w['first_mean'])} | {w['rest_n']} | {P(w['rest_win'])} | {P2(w['rest_mean'])} |")
        L += ['', '- 不同部位大小（每筆固定佔總資金、最多幾檔）：', '', '| 最多檔數 | 每筆佔資金 | 最多投入 | 年化 | 最大回撤 | 平均持股 | 成交筆數 |', '|---|---|---|---|---|---|---|']
        for z in dg['sizing']:
            L.append(f"| {z['slots']} | {P(z['weight'])} | {P(z['max_exposure'])} | {P2(z['cagr'])} | {P2(z['mdd'])} | {P(z['exposure'])} | {z['taken']} |")
        L.append('')
    L += ['## 限制', '',
          '- 5 年裡 2023～2026 以多頭為主，空頭只有 2022 一段；過去的勝率不代表未來。',
          '- 官方資料只有日線，停損用收盤判斷、隔天開盤出場，盤中觸價不算；跳空開低的損失已算在報酬裡。',
          '- 滑價用每邊 0.1% 估，冷門股或大部位實際可能更高；漲停開盤買不到的訊號直接放棄（研究也這樣算）。',
          f"- 測了 {rep['n_combos']:,} 個組合，有挑到運氣的風險；用樣本外、隨機基準、bootstrap 三道關卡降低，但不能完全排除。", '']
    open(os.path.join(OUT, 'REPORT.md'), 'w', encoding='utf-8').write('\n'.join(L))
    summ = {'n_combos': rep['n_combos'], 'n_is_qualified': rep['n_is_qualified'], 'n_top20_oos_ok': rep['n_top20_oos_ok'],
            'taiex': rep['taiex'], 'main': None, 'alt': None, 'candidate': None}
    if os.path.exists(diag_p):
        summ['diag'] = json.load(open(diag_p, encoding='utf-8'))
    for tag in ('main', 'alt', 'candidate'):
        chk = checks.get(rep.get(tag)) if tag == 'main' else rep.get('alt_check') if tag == 'alt' else candidate_of(rep)
        if chk:
            summ[tag] = {'combo': chk['combo'], 'desc': describe(chk['combo']), 'stats': chk['stats'], 'years': chk['years'],
                         'baseline': chk['baseline'], 'boot_ci': chk['boot_ci'], 'port_slots': chk['port_slots'],
                         'port_risk': chk['port_risk'], 'exdiv_share': chk['exdiv_share'], 'pass': chk['pass'], 'reasons': chk['reasons']}
    json.dump(summ, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n'.join(L[:60]))


if __name__ == '__main__':
    main()
