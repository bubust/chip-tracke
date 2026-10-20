// 🌊 大盤解析（PLAN-B74）：/api/wave/snapshot、/api/wave/panel
// 顏色：漲／壓力＝紅 var(--up)、跌／支撐＝綠 var(--down)、劇本目標／失效＝橘、費波那契＝紫
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = v => (v == null || v === '' || !isFinite(Number(v))) ? null : Number(v);
  const fmt = (v, nd = 0) => num(v) == null ? '—' : Number(v).toLocaleString('zh-TW', { minimumFractionDigits: nd, maximumFractionDigits: nd });
  const pctS = (v, nd = 2) => num(v) == null ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(nd) + '%';
  const rateS = v => num(v) == null ? '—' : (v * 100).toFixed(0) + '%';
  const md = d => d && d.length >= 10 ? `${+d.slice(5, 7)}/${+d.slice(8, 10)}` : (d || '');
  const cssVar = (k, d) => (getComputedStyle(document.documentElement).getPropertyValue(k) || '').trim() || d;
  const C = { up: cssVar('--up', '#f04848'), down: cssVar('--down', '#22c55e'), warn: '#fb923c', muted: '#94a3b8', accent: '#5b8cff', fib: '#a78bfa', grid: 'rgba(148,163,184,.08)' };
  const lsGet = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* 私密模式 */ } };
  const colorOf = v => num(v) == null ? 'var(--muted)' : v > 0 ? 'var(--up)' : v < 0 ? 'var(--down)' : 'var(--muted)';
  const tag = ok => ok ? '<span class="wv-tag ok">✅ 回測有效</span>' : '<span class="wv-tag ref">△ 回測沒比隨機好</span>';

  let S = null;
  const st = { mode: lsGet('wv_mode', 'short'), iv: lsGet('wv_iv', '1d'), deg: lsGet('wv_deg', 'mid'), alt: false,
               show: { lv: true, fib: true, tg: true } };
  let chart = null, candle = null, ma = {}, zz = null, cone = [], pls = [], ro = null, timer = null, panelPoll = null;

  // ── LightweightCharts（同 dashboard 兩段 CDN 備援）──
  async function loadLWC() {
    if (window.LightweightCharts) return true;
    for (const u of ['https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js',
                     'https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js']) {
      try {
        await new Promise((ok, bad) => {
          const t = setTimeout(() => bad(new Error('timeout')), 8000);
          const s = document.createElement('script');
          s.src = u; s.onload = () => { clearTimeout(t); ok(); }; s.onerror = () => { clearTimeout(t); bad(new Error('load')); };
          document.head.appendChild(s);
        });
        if (window.LightweightCharts) return true;
      } catch (e) { console.warn('[wave] LWC CDN 失敗', u); }
    }
    return false;
  }

  // ── 載入 ──
  async function load(force) {
    const box = $('wv-root');
    if (!box) return;
    try {
      const r = await fetch('/api/wave/snapshot' + (force ? '?force=1' : ''));
      const d = await r.json();
      if (!d.ok) {   // 第一次啟動還在下載歷史 → 20 秒後自己再試
        $('wv-msg').innerHTML = `⏳ ${esc(d.error || '大盤資料準備中')}（20 秒後自動重試）`; $('wv-msg').style.display = 'block';
        setTimeout(() => load(false), 20000);
        return;
      }
      S = d;
      $('wv-msg').style.display = 'none';
      render();
    } catch (e) {
      $('wv-msg').innerHTML = `⚠️ 大盤解析載入失敗：${esc(e.message)}`; $('wv-msg').style.display = 'block';
    }
  }

  function render() {
    renderHead();
    renderScenario();
    renderLevels();
    renderChips();
    renderGlobal();
    renderForecast();
    renderContext();
    renderResearch();
    drawChart();
  }

  function renderHead() {
    const live = S.asof.live;
    $('wv-price').innerHTML = `<b>${fmt(S.price, 2)}</b> <span style="color:${colorOf(S.chg)}">${S.chg > 0 ? '▲' : S.chg < 0 ? '▼' : ''} ${fmt(Math.abs(S.chg ?? 0), 2)}（${pctS(S.chg_pct)}）</span>`;
    let asof = live ? `盤中 ${esc(live.time || '')}（轉折只用收完的 K 棒，最新收盤 ${md(S.asof.date)}）` : `${md(S.asof.date)} 收盤`;
    if (S.asof.stale) asof += ` <span class="wv-badge warn">⚠ 資料過期：${esc(S.asof.stale_reason || '')}</span>`;
    if ((S.problems || []).length) asof += ` <span class="wv-badge warn" title="${esc(S.problems.map(p => p.src + ' 連續失敗 ' + p.fails + ' 次').join('、'))}">⚠ ${S.problems.length} 個資料來源有問題</span>`;
    $('wv-asof').innerHTML = asof + `<span class="wv-dim">　更新 ${esc((S.generated || '').slice(11, 16))}</span>`;
    document.querySelectorAll('[data-wv-mode]').forEach(b => b.classList.toggle('on', b.dataset.wvMode === st.mode));
    document.querySelectorAll('[data-wv-iv]').forEach(b => b.classList.toggle('on', b.dataset.wvIv === st.iv));
    document.querySelectorAll('[data-wv-deg]').forEach(b => b.classList.toggle('on', b.dataset.wvDeg === st.deg));
    $('wv-alt').classList.toggle('on', st.alt);
  }

  function countBlock(c, title, cls) {
    if (!c) return `<div class="wv-count ${cls}"><div class="wv-ct">${title}</div><div class="wv-dim">結構不清楚，無法數浪</div></div>`;
    const ends = (c.targets || []).filter(t => t.kind === 'end').slice(0, 3);
    const nexts = (c.targets || []).filter(t => t.kind === 'next').slice(0, 2);
    const inv = num(c.invalid) == null ? '' : `<div class="wv-inv">${c.invalid_side === 'below' ? '跌破' : '漲過'} <b>${fmt(c.invalid)}</b> 這個劇本失效</div>`;
    return `<div class="wv-count ${cls}"><div class="wv-ct">${title}</div><div class="wv-ctext">${esc(c.text)}</div>
      ${ends.length ? `<div class="wv-tg">這一浪目標：${ends.map(t => `<b>${fmt(t.price)}</b><span class="wv-dim">（${esc(t.label)}）</span>`).join('、')}</div>` : ''}
      ${nexts.length ? `<div class="wv-tg wv-dim">下一浪：${nexts.map(t => `${fmt(t.price)}（${esc(t.label)}）`).join('、')}</div>` : ''}
      ${inv}</div>`;
  }

  function renderScenario() {
    const w = S.waves[st.deg] || {};
    const sm = S.waves.small || {};
    const big = S.waves.big || {};
    const mp = Object.entries(S.waves).map(([k, v]) => v.maybe_pivot ? `<div class="wv-note">📍 ${esc(v.label)}：${esc(v.maybe_pivot)}</div>` : '').join('');
    $('wv-scen').innerHTML = `
      <div class="wv-h3">📜 劇本 <span class="wv-dim">（${esc(w.label || '')}；可在上方切換級數）</span></div>
      ${countBlock(w.primary, '主要劇本', 'prim')}
      ${countBlock(w.alternate, '替代劇本', 'alt')}
      <div class="wv-mini">短線（小級）：${esc((sm.primary || {}).text || '結構不清楚')}<br>
        背景（大級）：${esc((big.primary || {}).text || '結構不清楚')}</div>
      ${mp}
      <div class="wv-disc">${esc(S.disclaimer)}。艾略特波浪很主觀：這裡是固定規則數出來的「一種」數法；26 年回測每種浪別之後的表現都跟平常差不多。</div>`;
  }

  function lvRow(z, side) {
    const h = z.hold || {};
    const hold = num(h.rate) == null ? '—' : `${rateS(h.rate)}<span class="wv-dim">／隨機 ${rateS(h.placebo)}</span> ${h.pass ? '✅' : '△'}`;
    const src = (z.sources || []).slice(0, 4).map(s => esc(s.label)).join('、') + ((z.sources || []).length > 4 ? `…等 ${z.sources.length} 個` : '');
    return `<tr><td style="color:${side === 'S' ? 'var(--down)' : 'var(--up)'};font-weight:700">${fmt(z.price)}</td>
      <td style="color:var(--muted)">${pctS(z.dist_pct, 1)}</td><td>${esc(z.type_name)}</td><td class="wv-src">${src}</td><td>${hold}</td></tr>`;
  }

  function renderLevels() {
    const lv = (S.levels || {})[st.mode] || {};
    const res = (lv.resistance || []).slice().reverse();
    const sup = lv.support || [];
    const head = '<tr><th>價位</th><th>距離</th><th>類型</th><th>來源</th><th>歷史守住率</th></tr>';
    $('wv-levels').innerHTML = `
      <div class="wv-h3">🎯 ${st.mode === 'short' ? '短線（1～2 週，±6% 內）' : '波段（1～3 個月，±15% 內）'}支撐壓力</div>
      <table class="wv-tbl">${head}
        ${res.map(z => lvRow(z, 'R')).join('') || '<tr><td colspan="5" class="wv-dim">上方沒有壓力區</td></tr>'}
        <tr class="wv-now"><td colspan="5">現價 ${fmt(S.price, 0)}</td></tr>
        ${sup.map(z => lvRow(z, 'S')).join('') || '<tr><td colspan="5" class="wv-dim">下方沒有支撐區</td></tr>'}
      </table>
      ${(lv.note || []).map(n => `<div class="wv-note">${esc(n)}</div>`).join('')}
      <div class="wv-disc">守住＝碰到後先反彈 1 個 ATR（約 ${fmt(S.atr)} 點）；跌破＝先收盤穿過 0.5 個 ATR。數字是 2016～2026 樣本外；跟「隨便挑同樣距離的價位」比，沒有一種價位明顯比較好（多種來源重疊的區略好 +3 點，沒到門檻）。</div>`;
  }

  function renderChips() {
    const ch = S.chips || {};
    if (!ch.ok) { $('wv-chips').innerHTML = `<div class="wv-h3">🏦 籌碼</div><div class="wv-dim">${esc(ch.note || '籌碼資料暫缺')}</div>`; return; }
    const st5 = ch.f_streak > 0 ? `連買 ${ch.f_streak} 天` : ch.f_streak < 0 ? `連賣 ${-ch.f_streak} 天` : '';
    const row = (k, v, extra = '') => `<tr><td>${k}</td><td style="text-align:right">${v}</td><td class="wv-dim">${extra}</td></tr>`;
    const yi = v => `<span style="color:${colorOf(v)}">${fmt(v, 1)} 億</span>`;
    const facs = (ch.factors || []).map(f => `<div class="wv-fac"><span>${esc(f.name)}</span><b>${esc(f.state || '—')}</b>${tag(f.pass)}</div>`).join('');
    $('wv-chips').innerHTML = `<div class="wv-h3">🏦 大盤籌碼 <span class="wv-dim">${md(ch.date)}</span></div>
      <table class="wv-tbl2">
        ${row('外資現貨', yi(ch.f_net), st5)}${row('外資 5 日／20 日', `${yi(ch.f5)}／${yi(ch.f20)}`)}
        ${row('投信 今天／5 日', `${yi(ch.t_net)}／${yi(ch.t5)}`)}${row('自營商', yi(ch.d_net))}
        ${row('外資台指期淨未平倉', `<span style="color:${colorOf(ch.fut_f_oi)}">${fmt(ch.fut_f_oi)} 口</span>`, `5 日 ${ch.fut_chg5 > 0 ? '+' : ''}${fmt(ch.fut_chg5)}；近一年 ${num(ch.fut_pct) == null ? '—' : Math.round(ch.fut_pct * 100) + ' 百分位'}`)}
        ${row('融資餘額', `${fmt(ch.margin_amt, 0)} 億`, `20 日 ${pctS(num(ch.margin_chg20) == null ? null : ch.margin_chg20 * 100, 1)}`)}
      </table>${facs}
      <div class="wv-disc">回測（2022～2026 樣本外）：這些大盤籌碼對之後 5／20 天加權都沒有預測力，只當描述。</div>`;
  }

  function renderGlobal() {
    const g = S.global || {};
    const rows = (g.items || []).filter(i => i.ok).map(i => `<tr><td>${esc(i.name)}<span class="wv-dim"> ${md(i.date)}</span></td>
      <td style="text-align:right">${fmt(i.close, 2)}</td><td style="color:${colorOf(i.chg1)}">${pctS(i.chg1)}</td>
      <td style="color:${colorOf(i.chg20)}">${pctS(i.chg20, 1)}</td><td>${i.above_ma60 ? '<span style="color:var(--up)">線上</span>' : '<span style="color:var(--down)">線下</span>'}</td>
      <td>${num(i.corr60) == null ? '—' : Number(i.corr60).toFixed(2)}</td></tr>`).join('');
    const so = g.sox_overnight;
    const sw = g.sox_wave;
    $('wv-global').innerHTML = `<div class="wv-h3">🌏 國際對照</div>
      ${so ? `<div class="wv-hi">費半 ${md(so.date)} <b style="color:${colorOf(so.sox_ret)}">${pctS(so.sox_ret)}</b> → 加權下一個交易日歷史平均 <b style="color:${colorOf(so.tw_expect)}">${pctS(so.tw_expect)}</b>（±${fmt(so.sd, 1)}%）${tag(true)}
        <div class="wv-dim">2000～2015 估的關係拿到 2016 年後驗證 R² ${fmt(so.oos_r2, 2)}；只對「隔天」有效，對之後 5／20 天沒有</div></div>` : ''}
      <table class="wv-tbl"><tr><th>指數</th><th>收盤</th><th>1 日</th><th>20 日</th><th>60 日線</th><th>與加權相關</th></tr>${rows}</table>
      ${sw ? `<div class="wv-mini">費半數浪（中級）：${esc(sw.text)}；支撐 ${sw.support.map(v => fmt(v)).join('、') || '—'}；壓力 ${sw.resistance.map(v => fmt(v)).join('、') || '—'}</div>` : ''}
      <div class="wv-disc">相關＝近 60 天每日報酬（美股對台股隔天、日韓同一天）。</div>`;
  }

  function renderForecast() {
    const fc = S.forecast || {};
    const r = hz => {
      const x = fc[hz];
      if (!x) return '';
      return `<tr><td>${hz.slice(1)} 個交易日</td><td>${rateS(x.p_up)}</td><td>${fmt(x.lo_px)}～${fmt(x.hi_px)}</td><td style="color:${colorOf(x.median)}">${pctS(x.median * 100, 1)}</td></tr>`;
    };
    const an = (fc.analog || {}).h20 || {};
    const anTxt = an.n ? `相似狀態（${(an.used || []).map(u => ({ above_ma60: '在季線上下', dd_b: '離 60 日高點跌幅', wstate: '浪別' }[u] || u)).join('＋') || '全部'}，${an.n} 天）：20 天上漲 ${rateS(an.p_up)}、八成 ${fmt(an.lo_px)}～${fmt(an.hi_px)} △`
      : '相似狀態：樣本不足';
    $('wv-fc').innerHTML = `<div class="wv-h3">📈 之後會走多遠（歷史分布）</div>
      <table class="wv-tbl"><tr><th>期間</th><th>上漲機率</th><th>八成落在</th><th>中位數</th></tr>${r('h5')}${r('h20')}${r('h60')}</table>
      <div class="wv-mini">${esc(anTxt)}</div>
      <div class="wv-disc">用 2001 年以來每一天之後的漲跌換算成現在的點數（圖上的灰色錐形）。回測：用「相似狀態」挑日子算機率，反而比直接看全部歷史差一點，所以主要用全部歷史；這不是預測方向。</div>`;
  }

  function renderContext() {
    const c = S.context || {};
    const L = [];
    if (c.regime) L.push(`總經狀態：${esc(c.regime.label)}（${md(c.regime.date)}）`);
    if (c.box) L.push(`格局（宏爺 MA20／MA100）：<b>${esc(c.box)}</b>${c.mslope ? `；月線斜率 ${pctS(c.mslope.slope)}（${esc(c.mslope.tier || '')}）` : ''}<span class="wv-dim">（數字是個股研究，大盤只當參考）</span>`);
    if (c.crash) L.push(`大跌買點：比 60 日高點 ${pctS(c.crash.dd * 100, 1)}、比季線 ${pctS(c.crash.bias * 100, 1)}；${(c.crash.deep || []).length ? '<b style="color:var(--warn)">深跌訊號出現</b>（過去 5 波有 4 波之後 60～120 天賺）' : '沒有深跌訊號（比 60 日高點跌 15% 才算）'}`);
    if (c.dist_day) L.push(`大盤出貨日：${c.dist_day.dist_day ? '<b style="color:var(--warn)">今天是</b>' : '沒有'}<span class="wv-dim">（5 年 6 次、之後 10 天都漲，不是賣訊）</span>`);
    $('wv-ctx').innerHTML = `<div class="wv-h3">🧭 之前研究的訊號</div>${L.map(x => `<div class="wv-li">${x}</div>`).join('') || '<div class="wv-dim">—</div>'}`;
  }

  function renderResearch() {
    const r = S.research || {};
    const hold = r.hold || {};
    const NAME = { pivot: '前高前低', pivot_k3: '近期高低點', fib: '費波那契回檔', target: '波浪目標價', ma20: '月線', ma60: '季線', ma120: '半年線', ma240: '年線', round: '整數關卡', multi: '≥2 種來源重疊' };
    const rows = Object.entries(hold).map(([k, v]) => `<tr><td>${esc(NAME[k] || k)}</td><td>${fmt(v.n)}</td><td>${rateS(v.rate)}</td><td>${rateS(v.placebo)}</td>
      <td style="color:${colorOf(v.diff)}">${num(v.diff) == null ? '—' : (v.diff > 0 ? '+' : '') + (v.diff * 100).toFixed(1) + ' 點'}</td><td>${v.pass ? '✅' : '△'}</td></tr>`).join('');
    $('wv-research').innerHTML = `<summary>🔬 研究說明：加權 26 年回測（${esc(r.data_end || '')} 為止，${esc(r.n_tests || '')} 個假設一起 BH 校正）</summary>
      <ul>${(r.summary || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
      <table class="wv-tbl"><tr><th>價位類型</th><th>次數</th><th>守住率</th><th>隨機價位</th><th>差</th><th></th></tr>${rows}</table>
      <div class="wv-disc">✅ 要：樣本外比隨機高 ≥5 點、區間不含 0、BH 校正後顯著、4 個時期至少 3 個同方向。<a href="/api/wave/report" target="_blank" rel="noopener">完整研究報告</a></div>`;
  }

  // ── K 線圖 ──
  function futureDays(last, n) {   // 全部用 UTC 算（本地時區 +8 時 toISOString 會少一天）
    const out = [];
    const [y, m, day] = last.split('-').map(Number);
    const d = new Date(Date.UTC(y, m - 1, day));
    while (out.length < n) {
      d.setUTCDate(d.getUTCDate() + 1);
      if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) out.push(d.toISOString().slice(0, 10));
    }
    return out;
  }

  function weekTime(bars, date) {
    for (const b of bars) if (b.time >= date) return b.time;
    return bars.length ? bars[bars.length - 1].time : date;
  }

  async function drawChart() {
    if (!(await loadLWC())) { $('wv-chart').innerHTML = '<div class="wv-dim" style="padding:20px">K 線圖載入失敗（CDN 連不上）</div>'; return; }
    const el = $('wv-chart');
    const LW = window.LightweightCharts;
    if (!chart) {
      chart = LW.createChart(el, {
        height: el.clientHeight || 420, layout: { background: { type: 'solid', color: 'transparent' }, textColor: C.muted, fontSize: 12 },
        grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
        rightPriceScale: { borderColor: 'rgba(148,163,184,.2)', scaleMargins: { top: 0.08, bottom: 0.08 } },
        timeScale: { borderColor: 'rgba(148,163,184,.2)', rightOffset: 6 },
        crosshair: { mode: 0 }, localization: { priceFormatter: p => Math.round(p).toLocaleString('zh-TW') },
      });
      candle = chart.addCandlestickSeries({ upColor: C.up, downColor: C.down, wickUpColor: C.up, wickDownColor: C.down, borderVisible: false, priceLineVisible: false });
      // 均線不參與縮放（年線離現價很遠，會把 K 棒壓扁）
      const noScale = { autoscaleInfoProvider: () => null };
      ma['20'] = chart.addLineSeries({ color: '#facc15', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...noScale });
      ma['60'] = chart.addLineSeries({ color: '#38bdf8', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...noScale });
      ma['240'] = chart.addLineSeries({ color: '#c084fc', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...noScale });
      zz = chart.addLineSeries({ color: 'rgba(91,140,255,.85)', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      for (let k = 0; k < 3; k++) cone.push(chart.addLineSeries({ color: 'rgba(148,163,184,.65)', lineWidth: 1, lineStyle: k === 1 ? 0 : 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }));
      if (window.ResizeObserver) { ro = new ResizeObserver(() => chart && chart.applyOptions({ width: el.clientWidth, height: el.clientHeight || 420 })); ro.observe(el); }
    }
    const weekly = st.iv === '1wk';
    const bars = (weekly ? S.chart.weekly : S.chart.bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }))) || [];
    if (!bars.length) { $('wv-legend').textContent = '沒有 K 線資料'; return; }
    candle.setData(bars);
    for (const k of ['20', '60', '240']) ma[k].setData(weekly ? [] : (S.chart.ma[k] || []));
    // 數浪：轉折連線＋浪別標記
    const w = S.waves[st.deg] || {};
    const cnt = st.alt ? w.alternate : w.primary;
    const T = d => weekly ? weekTime(bars, d) : d;
    const pts = [];
    const seen = new Set();
    for (const p of (w.pivots || []).concat(w.tentative ? [w.tentative] : [])) {
      const t = T(p.date);
      if (seen.has(t)) continue;
      seen.add(t); pts.push({ time: t, value: p.p });
    }
    pts.sort((a, b) => a.time < b.time ? -1 : 1);
    zz.setData(pts);
    const marks = [];
    if (cnt) {
      const L = cnt.labels || [];
      L.forEach((x, j) => {
        const nb = L[j + 1] || L[j - 1];
        const high = nb ? x.p > nb.p : true;
        const abc = 'ABC'.includes(x.label);
        marks.push({ time: T(x.date), position: high ? 'aboveBar' : 'belowBar', color: abc ? C.warn : C.accent,
                     shape: high ? 'arrowDown' : 'arrowUp', text: x.sym + (x.tentative ? '?' : '') });
      });
    }
    marks.sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
    candle.setMarkers(marks);
    // 價位線
    pls.forEach(p => { try { candle.removePriceLine(p); } catch (e) { /* 已移除 */ } });
    pls = [];
    const add = (price, color, title, style = 2, width = 1, axis = true) => { if (num(price) != null) pls.push(candle.createPriceLine({ price: Number(price), color, lineWidth: width, lineStyle: style, axisLabelVisible: axis, title })); };
    if (st.show.lv) {
      const lv = (S.levels || {})[st.mode] || {};
      (lv.support || []).forEach(z => add(z.price, C.down, `撐 ${rateS((z.hold || {}).rate)}`));
      (lv.resistance || []).forEach(z => add(z.price, C.up, `壓 ${rateS((z.hold || {}).rate)}`));
    }
    if (st.show.fib && w.fib) (w.fib.levels || []).forEach(f => add(f.price, C.fib, `${f.ratio}`, 1, 1, false));   // 費波那契只在線上標比例，右邊軸不放（太擠）
    if (st.show.tg && cnt) {
      (cnt.targets || []).filter(t => t.kind === 'end').slice(0, 3).forEach(t => add(t.price, C.warn, '目標', 1));
      if (num(cnt.invalid) != null) add(cnt.invalid, C.warn, '失效', 0, 2);
    }
    // 歷史分布錐形（只有日 K）
    const fc = S.forecast || {};
    if (!weekly && fc.h5 && fc.h20 && bars.length) {
      const last = bars[bars.length - 1].time;
      const fd = futureDays(last, 20);
      const p0 = { time: last, value: S.price };
      cone[0].setData([p0, { time: fd[4], value: fc.h5.hi_px }, { time: fd[19], value: fc.h20.hi_px }]);
      cone[1].setData([p0, { time: fd[4], value: fc.h5.mid_px }, { time: fd[19], value: fc.h20.mid_px }]);
      cone[2].setData([p0, { time: fd[4], value: fc.h5.lo_px }, { time: fd[19], value: fc.h20.lo_px }]);
    } else cone.forEach(s => s.setData([]));
    const n = bars.length;
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - (weekly ? 130 : 160)), to: n + (weekly ? 4 : 24) });
    $('wv-legend').innerHTML = `<span style="color:#facc15">━ 月線</span><span style="color:#38bdf8">━ 季線</span><span style="color:#c084fc">━ 年線</span>
      <span style="color:${C.accent}">━ 轉折（${esc(w.label || '')}）</span><span style="color:${C.down}">┅ 支撐</span><span style="color:${C.up}">┅ 壓力</span>
      <span style="color:${C.fib}">┄ 費波那契</span><span style="color:${C.warn}">┄ 劇本目標／━ 失效</span><span style="color:${C.muted}">◁ 灰錐＝歷史 5／20 天八成範圍</span>
      ${S.chart.bars.length && S.chart.bars[S.chart.bars.length - 1].partial ? '<span class="wv-dim">最後一根是盤中</span>' : ''}`;
  }

  // ── 🤖 AI 圓桌 ──
  async function loadPanel() {
    try {
      const d = await (await fetch('/api/wave/panel')).json();
      renderPanel(d);
      if (d.running && !panelPoll) pollJob(d.running);
    } catch (e) { $('wv-ai').innerHTML = `<div class="wv-h3">🤖 AI 圓桌</div><div class="wv-dim">載入失敗：${esc(e.message)}</div>`; }
  }

  function renderPanel(d) {
    const ps = d.providers || [];
    const r = d.result;
    const btn = ps.length ? `<button class="btn" id="wv-ai-run" ${d.running ? 'disabled' : ''}>${d.running ? '⏳ 討論中…（約 2 分鐘）' : `🔄 再討論一次（今天還剩 ${d.manual_left} 次）`}</button>` : '';
    let html = `<div class="wv-h3">🤖 AI 圓桌 <span class="wv-dim">${ps.map(p => esc(p.name)).join('、') || '還沒設定 AI 金鑰'}</span> ${btn}</div>`;
    if (!ps.length) html += '<div class="wv-dim">要先在 Fly 設 GEMINI_API_KEY／GROQ_API_KEY 才會有 AI 討論。</div>';
    if (d.note) html += `<div class="wv-note">${esc(d.note)}</div>`;
    if (!r) { $('wv-ai').innerHTML = html + '<div class="wv-dim">還沒有討論紀錄（每個交易日 16:30 自動討論一次）。</div>'; bindRun(); return; }
    const mo = r.moderator || {};
    const stanceColor = s => /多/.test(s || '') ? 'var(--up)' : /空/.test(s || '') ? 'var(--down)' : 'var(--muted)';
    const mode = { roundtable: '', single: `⚠ 只有 ${esc((r.participants[0] || {}).name || '')} 的看法（其他 AI 沒回應）`, none: '⚠ AI 都沒回應' }[r.mode] || '';
    html += `<div class="wv-dim">${esc(r.finished || r.started || '')}（${r.trigger === 'manual' ? '手動' : '每日自動'}；資料 ${md(r.asof)}、加權 ${fmt(r.price)}）
      參加：${(r.participants || []).map(p => `${esc(p.name)}<span class="wv-dim">・${esc(p.model)}</span>`).join('、')}${mode ? '　' + mode : ''}</div>`;
    if (mo.summary) {
      html += `<div class="wv-ai-sum"><span class="wv-stance" style="background:${stanceColor(mo.stance)}22;color:${stanceColor(mo.stance)}">${esc(mo.stance || '')}</span>
        <b>${esc(mo.summary)}</b> <span class="wv-dim">（${esc(mo.agree_count || '')}；信心 ${esc(mo.confidence || '')}；主持：${esc(mo.name || '')}）</span></div>
        <div class="wv-ai-grid">
          <div><div class="wv-ct">大家都同意</div><ul>${(mo.consensus || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
          <div><div class="wv-ct">意見不同</div><ul>${(mo.disagreements || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
        </div>
        <div class="wv-mini"><b>短線：</b>${esc(mo.short || '')}<br><b>波段：</b>${esc(mo.swing || '')}</div>
        <div class="wv-chips">${(mo.watch_levels || []).map(w => `<span class="wv-chip"><b>${fmt(w.price)}</b> ${esc(w.why || '')}</span>`).join('')}</div>`;
    }
    if ((r.flagged || []).length) html += `<div class="wv-note">⚠ 非系統價位（AI 自己算的，不可靠）：${r.flagged.map(v => fmt(v)).join('、')}</div>`;
    const ids = Object.keys(r.round1 || {});
    html += ids.map(id => {
      const a = r.round1[id] || {}, b = (r.round2 || {})[id];
      return `<details class="wv-who"><summary>${esc(a.name)}：<b style="color:${stanceColor(a.stance)}">${esc(a.stance || '')}</b> ${esc(a.short || '')}</summary>
        <div class="wv-mini"><b>第一輪</b>　短線：${esc(a.short || '')}；波段：${esc(a.swing || '')}<br>理由：${(a.reasons || []).map(esc).join('；')}<br>風險：${(a.risks || []).map(esc).join('；')}</div>
        ${b ? `<div class="wv-mini"><b>第二輪</b>（${esc(b.stance || '')}）${esc(b.view || '')}<br>同意：${(b.agree || []).map(esc).join('；')}<br>不同意：${(b.disagree || []).map(esc).join('；')}</div>` : '<div class="wv-dim">第二輪沒有回應</div>'}
      </details>`;
    }).join('');
    if ((r.failed || []).length) html += `<details class="wv-who"><summary class="wv-dim">沒回應的（${r.failed.length}）</summary>${r.failed.map(f => `<div class="wv-dim">${esc(f.name)} 第 ${esc(f.round)} 輪：${esc(f.error)}</div>`).join('')}</details>`;
    const nw = r.news || {};
    if ((nw.items || []).length) html += `<details class="wv-who"><summary>📰 討論用的新聞（Google 搜尋近 7 天，${nw.items.length} 則）</summary>
      <ul>${nw.items.map(x => `<li>${esc(x.date || '')} ${esc(x.title)}<span class="wv-dim">：${esc(x.why || '')}</span></li>`).join('')}</ul>
      <div class="wv-dim">${(nw.sources || []).slice(0, 8).map(s => `<a href="${esc(s.uri)}" target="_blank" rel="noopener">${esc(s.title || '來源')}</a>`).join('、')}</div></details>`;
    html += `<div class="wv-disc">${esc(r.disclaimer || '')}。價位只允許用系統算的支撐壓力／目標，不是的會標 ⚠。</div>`;
    $('wv-ai').innerHTML = html;
    bindRun();
  }

  function bindRun() {
    const b = $('wv-ai-run');
    if (b) b.onclick = runPanel;
  }

  async function runPanel() {
    const b = $('wv-ai-run');
    if (b) { b.disabled = true; b.textContent = '⏳ 討論中…（約 2 分鐘）'; }
    try {
      const r = await fetch('/api/wave/panel/run', { method: 'POST' });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.status);
      pollJob(d.job);
    } catch (e) {
      alert('AI 圓桌：' + e.message);
      loadPanel();
    }
  }

  function pollJob(jid) {
    clearInterval(panelPoll);
    panelPoll = setInterval(async () => {
      try {
        const j = await (await fetch('/api/wave/panel/job/' + encodeURIComponent(jid))).json();
        if (j.status !== 'running') { clearInterval(panelPoll); panelPoll = null; if (j.status === 'error') alert('AI 圓桌失敗：' + (j.error || '')); loadPanel(); }
      } catch (e) { /* 下一輪再試 */ }
    }, 6000);
  }

  // ── 控制列 ──
  function bind() {
    document.querySelectorAll('[data-wv-mode]').forEach(b => b.onclick = () => { st.mode = b.dataset.wvMode; lsSet('wv_mode', st.mode); if (S) render(); });
    document.querySelectorAll('[data-wv-iv]').forEach(b => b.onclick = () => { st.iv = b.dataset.wvIv; lsSet('wv_iv', st.iv); if (S) { renderHead(); drawChart(); } });
    document.querySelectorAll('[data-wv-deg]').forEach(b => b.onclick = () => { st.deg = b.dataset.wvDeg; lsSet('wv_deg', st.deg); if (S) { renderHead(); renderScenario(); drawChart(); } });
    $('wv-alt').onclick = () => { st.alt = !st.alt; if (S) { renderHead(); drawChart(); } };
    document.querySelectorAll('[data-wv-show]').forEach(cb => cb.onchange = () => { st.show[cb.dataset.wvShow] = cb.checked; if (S) drawChart(); });
    $('wv-refresh').onclick = async () => {
      $('wv-refresh').disabled = true;
      try { await fetch('/api/wave/refresh', { method: 'POST' }); } catch (e) { /* 照樣重新載入 */ }
      setTimeout(async () => { await load(true); $('wv-refresh').disabled = false; }, 15000);
    };
  }

  function isSession() {
    const now = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Taipei' }));
    const m = now.getHours() * 60 + now.getMinutes();
    return now.getDay() >= 1 && now.getDay() <= 5 && m >= 540 && m <= 815;
  }

  window.addEventListener('DOMContentLoaded', () => {
    if (!$('wv-root')) return;
    bind();
    load(false);
    loadPanel();
    timer = setInterval(() => { if (isSession() && document.visibilityState === 'visible') load(false); }, 120000);
  });
})();
