// 🌊 大盤解析（PLAN-B74）：/api/wave/snapshot、/api/wave/panel
// 10-20 用戶：「字太小、太亂、K 線超混亂，要簡單清晰、說明數據的意義」→ 先給白話結論，細節收起來；K 線預設只畫最重要的線
// 顏色：漲／壓力＝紅 var(--up)、跌／支撐＝綠 var(--down)、劇本失效＝橘、費波那契＝紫
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
  const C = { up: cssVar('--up', '#f04848'), down: cssVar('--down', '#22c55e'), warn: '#fb923c', muted: '#94a3b8', accent: '#5b8cff', fib: '#a78bfa', grid: 'rgba(148,163,184,.07)' };
  const lsGet = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* 私密模式 */ } };
  const colorOf = v => num(v) == null ? 'var(--muted)' : v > 0 ? 'var(--up)' : v < 0 ? 'var(--down)' : 'var(--muted)';
  const DEG_NAME = { small: '小級（短線）', mid: '中級（波段）', big: '大級（長期）' };
  // AI 立場的底色（CSS 變數不能直接接透明度字尾，用固定的 rgba）
  const stanceBg = s => /多/.test(s || '') ? 'rgba(240,72,72,.15)' : /空/.test(s || '') ? 'rgba(34,197,94,.15)' : 'rgba(148,163,184,.15)';

  let S = null, panelData = null;
  const st = { mode: lsGet('wv_mode', 'short'), iv: lsGet('wv_iv', '1d'), degSel: lsGet('wv_deg2', 'auto'), alt: false,
               show: { fib: false, tg: false, cone: false } };
  const deg = () => st.degSel !== 'auto' ? st.degSel : (st.mode === 'short' ? 'small' : 'mid');
  const modeName = () => st.mode === 'short' ? '短線（1～2 週）' : '波段（1～3 個月）';
  let chart = null, candle = null, ma = {}, zz = null, cone = [], pls = [], panelPoll = null;

  // ── 波浪 → 白話 ──
  function plain(c) {
    if (!c) return null;
    const cur = c.current, up = c.dir > 0;
    if (c.kind === 'impulse' && '12345'.includes(cur)) {
      const steps = ['1', '2', '3', '4', '5'];
      if ('135'.includes(cur)) {
        const m = { '1': '新一波的第一段，還需要後面走勢確認', '3': '通常是整波裡最強、最長的一段', '5': '這一波的最後一段，走完通常會有比較大的修正' }[cur];
        return { title: up ? `上漲波・第 ${cur} 段上漲中` : `下跌波・第 ${cur} 段下跌中`, meaning: m, steps, cur };
      }
      return { title: up ? `上漲途中的回檔（第 ${cur} 段）` : `下跌途中的反彈（第 ${cur} 段）`,
               meaning: up ? `回檔走完，照規則後面還有第 ${+cur + 1} 段上漲` : `反彈走完，照規則後面還有第 ${+cur + 1} 段下跌`, steps, cur };
    }
    // A-B-C：漲多後的修正（跌－彈－跌）或跌深後的反彈（彈－回－彈）
    const corrDown = (c.kind === 'impulse' && up) || (c.kind === 'correction' && !up);
    const steps = c.kind === 'impulse' ? ['1', '2', '3', '4', '5', 'A', 'B', 'C'] : ['A', 'B', 'C'];
    const T = corrDown
      ? { A: ['漲多後的修正・第一段下跌（A）', '修正通常走「跌－彈－跌」三段，這是第一段'],
          B: ['修正中的反彈（B）', '反彈走完，照規則還有最後一段下跌（C）'],
          C: ['修正的最後一段下跌（C）', '這段跌完，修正可能結束、重新開始上漲'] }
      : { A: ['跌深後的反彈・第一段（A）', '跌深反彈通常走「彈－回－彈」三段，這是第一段'],
          B: ['反彈中的回落（B）', '回落走完，照規則還有最後一段反彈（C）'],
          C: ['反彈的最後一段（C）', '這段反彈走完，可能再往下'] };
    if (!T[cur]) return null;   // 防呆：沒對應的浪別就當「結構不清楚」
    return { title: T[cur][0], meaning: T[cur][1], steps, cur };
  }

  function invText(c) {
    if (!c || num(c.invalid) == null) return '';
    return `${c.invalid_side === 'below' ? '跌破' : '漲過'} ${fmt(c.invalid)} → 這個劇本就不成立`;
  }

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
    if (!$('wv-root')) return;
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
    renderSummary();
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
    let asof = live ? `盤中 ${esc(live.time || '')}` : `${md(S.asof.date)} 收盤`;
    if (S.asof.stale) asof += ` <span class="wv-badge">⚠ ${esc(S.asof.stale_reason || '資料過期')}</span>`;
    if ((S.problems || []).length) asof += ` <span class="wv-badge" title="${esc(S.problems.map(p => p.src + ' 連續失敗 ' + p.fails + ' 次').join('、'))}">⚠ ${S.problems.length} 個資料來源有問題</span>`;
    $('wv-asof').innerHTML = asof;
    document.querySelectorAll('[data-wv-mode]').forEach(b => b.classList.toggle('on', b.dataset.wvMode === st.mode));
    document.querySelectorAll('[data-wv-iv]').forEach(b => b.classList.toggle('on', b.dataset.wvIv === st.iv));
    document.querySelectorAll('[data-wv-deg]').forEach(b => b.classList.toggle('on', b.dataset.wvDeg === st.degSel));
    document.querySelectorAll('[data-wv-show]').forEach(cb => { cb.checked = !!st.show[cb.dataset.wvShow]; });
    $('wv-alt').classList.toggle('on', st.alt);
    $('wv-alt').textContent = st.alt ? '看主要劇本' : '看替代劇本';
  }

  // ── 一眼看懂 ──
  function renderSummary() {
    const w = S.waves[deg()] || {};
    const p = plain(w.primary);
    const lv = (S.levels || {})[st.mode] || {};
    const s1 = (lv.support || [])[0], s2 = (lv.support || [])[1];
    const r1 = (lv.resistance || [])[0], r2 = (lv.resistance || [])[1];
    const so = (S.global || {}).sox_overnight;
    const tile = (k, v, m, color) => `<div class="wv-tile"><div class="k">${k}</div><div class="v" style="color:${color || 'var(--text)'}">${v}</div><div class="m">${m}</div></div>`;
    const inv = w.primary && num(w.primary.invalid) != null ? w.primary : null;
    let ai = '';
    const pr = panelData && panelData.result;
    const mo = pr && pr.moderator;
    if (mo && mo.summary) {
      const sc = /多/.test(mo.stance || '') ? 'var(--up)' : /空/.test(mo.stance || '') ? 'var(--down)' : 'var(--muted)';
      ai = `<div class="wv-ailine">🤖 <b>AI 圓桌</b>（${md(pr.day)}）：<b style="color:${sc}">${esc(mo.stance || '')}</b>・${esc(mo.summary)} <span class="wv-dim">${esc(mo.agree_count || '')}　↓ 下面看討論內容</span></div>`;
    } else if (panelData) {
      ai = `<div class="wv-ailine wv-dim">🤖 AI 圓桌還沒討論（每個交易日 16:30 自動討論，也可以在下面按「開始討論」）</div>`;
    }
    $('wv-sum').innerHTML = `
      <div class="wv-head">${esc(modeName().slice(0, 2))}走勢：${p ? esc(p.title) : '結構不清楚，看支撐壓力就好'}
        <small>${p ? esc(p.meaning) : ''}</small></div>
      <div class="wv-tiles">
        ${tile('最近支撐', s1 ? `${fmt(s1.price)}<small style="color:var(--muted)">${pctS(s1.dist_pct, 1)}</small>` : '—',
               s1 ? `跌到這附近容易止跌；${s2 ? `跌破的話下一個看 ${fmt(s2.price)}` : '再往下附近沒有支撐'}` : '附近沒有支撐區', 'var(--down)')}
        ${tile('最近壓力', r1 ? `${fmt(r1.price)}<small style="color:var(--muted)">${pctS(r1.dist_pct, 1)}</small>` : '—',
               r1 ? `漲到這附近容易遇到賣壓；${r2 ? `站上的話下一個看 ${fmt(r2.price)}` : '再往上附近沒有壓力'}` : '附近沒有壓力區', 'var(--up)')}
        ${tile('劇本失效點', inv ? fmt(inv.invalid) : '—',
               inv ? `${inv.invalid_side === 'below' ? '跌破' : '漲過'}這裡，代表上面的走勢判斷錯了，要換劇本` : '—', 'var(--warn)')}
        ${tile('今天開盤參考', so ? pctS(so.tw_expect) : '—',
               so ? `費半昨晚 ${pctS(so.sox_ret)}，過去平均讓加權隔天 ${pctS(so.tw_expect)}（±${fmt(so.sd, 1)}%）。26 年回測唯一有效的指標` : '美股資料還沒進來', so ? colorOf(so.tw_expect) : '')}
      </div>
      ${ai}
      <div class="wv-what"><b>怎麼用：</b>支撐、壓力是過去高低點、整數關卡、均線、費波那契重疊的位置。回測這些價位「守住」的機率約 4 成，跟隨便畫一條線差不多，
        所以當作<b>參考點＋停損位置</b>，不是一定會在那裡反轉。${esc(S.disclaimer || '')}。</div>`;
  }

  // ── 劇本 ──
  function countBox(c, label) {
    const p = plain(c);
    if (!p) return `<div class="wv-count"><div class="t">${label}：結構不清楚</div><div class="p wv-dim">最近的轉折不符合波浪規則，先看支撐壓力</div></div>`;
    const ends = (c.targets || []).filter(t => t.kind === 'end').slice(0, 2);
    return `<div class="wv-count"${label === '替代劇本' ? ' style="border-left-color:var(--warn);background:rgba(251,146,60,.05)"' : ''}>
      <div class="wv-dim">${label}</div><div class="t">${esc(p.title)}</div>
      <div class="wv-steps">${p.steps.map(s => `<span class="${s === p.cur ? 'on' : ''}">${s}</span>`).join('')}</div>
      <div class="p">${esc(p.meaning)}</div>
      ${ends.length ? `<div class="p">這段可能走到：${ends.map(t => `<b>${fmt(t.price)}</b>`).join('、')}</div>` : ''}
      ${invText(c) ? `<div class="x">${esc(invText(c))}</div>` : ''}</div>`;
  }

  function renderScenario() {
    const d = deg();
    const w = S.waves[d] || {};
    const others = ['small', 'mid', 'big'].filter(k => k !== d).map(k => {
      const p = plain((S.waves[k] || {}).primary);
      return `<div>${DEG_NAME[k]}：${p ? esc(p.title) : '結構不清楚'}</div>`;
    }).join('');
    const mp = Object.values(S.waves).map(v => v.maybe_pivot).filter(Boolean);
    $('wv-scen').innerHTML = `
      <div class="wv-h3">📜 波浪劇本 <span class="wv-dim">${DEG_NAME[d]}</span></div>
      ${countBox(w.primary, '主要劇本')}
      ${w.alternate ? `<details class="wv-alt-box"><summary>另一種數法（替代劇本）</summary>${countBox(w.alternate, '替代劇本')}</details>` : ''}
      ${mp.length ? `<div class="wv-note">📍 ${mp.map(esc).join('<br>📍 ')}</div>` : ''}
      <div class="wv-what"><b>波浪理論是什麼：</b>上漲常走 5 段（1、3、5 往上，2、4 回檔），之後修正走 3 段（A 跌、B 彈、C 跌）。
        程式用固定規則判斷現在走到哪一段。<b>很主觀</b>：26 年回測，各段之後的漲跌跟平常差不多，所以只當「劇本」參考。</div>
      <details class="wv-alt-box"><summary>其他級數怎麼看</summary><div class="p" style="font-size:.92rem">${others}</div></details>`;
  }

  // ── 支撐壓力表 ──
  function srcText(z) {
    const seen = new Set();
    const parts = [];
    for (const s of z.sources || []) {
      let t = s.label || '';
      const dm = t.match(/(\d{4})-(\d{2})-(\d{2})/);
      if (dm) t = t.replace(dm[0], `${+dm[2]}/${+dm[3]}`);
      t = t.replace(/^小級|^中級|^大級/, '').replace('整數關卡', '整數');
      if (seen.has(t)) continue;
      seen.add(t);
      parts.push(t);
      if (parts.length >= 3) break;
    }
    const more = (z.sources || []).length - parts.length;
    return parts.join('＋') + (more > 0 ? ` 等 ${z.sources.length} 個` : '');
  }

  function renderLevels() {
    const lv = (S.levels || {})[st.mode] || {};
    const res = (lv.resistance || []).slice().reverse();
    const sup = lv.support || [];
    const row = (z, side) => `<tr><td class="n" style="color:${side === 'S' ? 'var(--down)' : 'var(--up)'};font-weight:800;font-size:1.05rem">${fmt(z.price)}</td>
      <td class="n" style="color:var(--muted)">${pctS(z.dist_pct, 1)}</td>
      <td>${side === 'S' ? '支撐' : '壓力'}${(z.sources || []).length >= 2 ? '<span class="wv-dim">（多種重疊，較重要）</span>' : ''}</td>
      <td class="wv-why wv-hide-m">${esc(srcText(z))}</td></tr>`;
    const holds = [...sup, ...res].map(z => (z.hold || {})).filter(h => num(h.rate) != null);
    const avgH = holds.length ? holds.reduce((a, h) => a + h.rate, 0) / holds.length : null;
    const avgP = holds.length ? holds.reduce((a, h) => a + (h.placebo || 0), 0) / holds.length : null;
    $('wv-levels').innerHTML = `
      <div class="wv-h3">🎯 ${modeName()}的支撐與壓力 <span class="wv-dim">最上面可以切換短線／波段</span></div>
      <table class="wv-tbl"><tr><th>價位</th><th>離現價</th><th>是什麼</th><th class="wv-hide-m">為什麼是這裡</th></tr>
        ${res.map(z => row(z, 'R')).join('') || '<tr><td colspan="4" class="wv-dim">上方附近沒有壓力</td></tr>'}
        <tr class="wv-now"><td colspan="4">現在 ${fmt(S.price, 0)}</td></tr>
        ${sup.map(z => row(z, 'S')).join('') || '<tr><td colspan="4" class="wv-dim">下方附近沒有支撐</td></tr>'}
      </table>
      ${(lv.note || []).map(n => `<div class="wv-note">${esc(n)}</div>`).join('')}
      <div class="wv-what">${avgH != null ? `歷史上碰到這類價位後，<b>先反彈的機率約 ${rateS(avgH)}</b>（隨便畫一條線約 ${rateS(avgP)}）。` : ''}
        意思是：價位附近值得注意，但不保證會撐住或壓住，<b>跌破支撐就要照停損</b>。</div>`;
  }

  // ── 收起來的區塊（標題直接寫結論）──
  function keepOpen(el, html) {
    const open = el.open;
    el.innerHTML = html;
    el.open = open;
  }

  function renderChips() {
    const ch = S.chips || {};
    const el = $('wv-chips');
    if (!ch.ok) { keepOpen(el, `<summary>🏦 籌碼<span class="s">${esc(ch.note || '籌碼資料暫缺')}</span></summary>`); return; }
    const streak = ch.f_streak > 0 ? `外資連買 ${ch.f_streak} 天` : ch.f_streak < 0 ? `外資連賣 ${-ch.f_streak} 天` : '外資今天沒動';
    const yi = v => `<b style="color:${colorOf(v)}">${fmt(v, 0)} 億</b>`;
    const pos = num(ch.fut_pct) == null ? '' : (ch.fut_pct < 0.2 ? '，在近一年偏空的位置' : ch.fut_pct > 0.8 ? '，在近一年偏多的位置' : '，在近一年中間的位置');
    keepOpen(el, `<summary>🏦 籌碼：${streak}，5 天合計 ${fmt(ch.f5, 0)} 億
        <span class="s">外資、投信、期貨、融資的動向（回測：對之後 1～4 週沒有預測力，只當描述）</span></summary>
      <div class="wv-kv">
        <span class="k">外資今天</span><span>${yi(ch.f_net)}（${streak}）</span>
        <span class="k">外資 5 天／20 天</span><span>${yi(ch.f5)}／${yi(ch.f20)}</span>
        <span class="k">投信 5 天</span><span>${yi(ch.t5)}</span>
        <span class="k">外資台指期</span><span><b style="color:${colorOf(ch.fut_f_oi)}">${(ch.fut_f_oi || 0) < 0 ? '淨空單' : '淨多單'} ${fmt(Math.abs(ch.fut_f_oi || 0))} 口</b>
          <span class="wv-dim">（5 天${(ch.fut_chg5 || 0) > 0 ? '多單增加' : '空單增加'} ${fmt(Math.abs(ch.fut_chg5 || 0))} 口${pos}）</span></span>
        <span class="k">融資餘額</span><span>${fmt(ch.margin_amt, 0)} 億 <span class="wv-dim">（20 天 ${pctS(num(ch.margin_chg20) == null ? null : ch.margin_chg20 * 100, 1)}；增加＝散戶加碼）</span></span>
      </div>
      <div class="wv-what">紅＝買超、綠＝賣超（億元）。外資連續大賣常讓人緊張，但 2022～2026 回測，這些籌碼對大盤之後 1～4 週的漲跌<b>沒有預測力</b>。</div>`);
  }

  function renderGlobal() {
    const g = S.global || {};
    const el = $('wv-global');
    const sox = (g.items || []).find(i => i.sym === 'SOX' && i.ok);
    const so = g.sox_overnight;
    const rows = (g.items || []).filter(i => i.ok).map(i => `<tr><td>${esc(i.name)}</td><td class="n" style="color:${colorOf(i.chg1)}">${pctS(i.chg1)}</td>
      <td class="n" style="color:${colorOf(i.chg20)}">${pctS(i.chg20, 1)}</td><td>${i.above_ma60 ? '<span style="color:var(--up)">季線上</span>' : '<span style="color:var(--down)">季線下</span>'}</td>
      <td class="n">${num(i.corr60) == null ? '—' : Number(i.corr60).toFixed(2)}</td></tr>`).join('');
    keepOpen(el, `<summary>🌏 國際：${sox ? `費半昨晚 ${pctS(sox.chg1)}、近 20 天 ${pctS(sox.chg20, 1)}、在${sox.above_ma60 ? '季線上' : '季線下'}` : '資料還沒進來'}
        <span class="s">台股最常跟著美國半導體（費半）走${so ? `；昨晚費半換算加權今天平均 ${pctS(so.tw_expect)}` : ''}</span></summary>
      <table class="wv-tbl"><tr><th>指數</th><th>昨天</th><th>20 天</th><th>趨勢</th><th>跟加權連動</th></tr>${rows}</table>
      ${g.sox_wave ? `<div class="wv-what"><b>費半的波浪：</b>${esc(g.sox_wave.text)}；支撐 ${(g.sox_wave.support || []).map(v => fmt(v)).join('、') || '—'}、壓力 ${(g.sox_wave.resistance || []).map(v => fmt(v)).join('、') || '—'}</div>` : ''}
      <div class="wv-what">「跟加權連動」＝近 60 天每天漲跌的相關係數，1 代表完全同步、0 代表沒關係。前一晚費半漲跌是回測<b>唯一有效</b>的指標（只對隔天有用，對 1～4 週沒有）。</div>`);
  }

  function renderForecast() {
    const fc = S.forecast || {};
    const el = $('wv-fc');
    const r = (hz, nm) => {
      const x = fc[hz];
      return x ? `<tr><td>${nm}</td><td class="n">${rateS(x.p_up)}</td><td class="n">${fmt(x.lo_px)}～${fmt(x.hi_px)}</td></tr>` : '';
    };
    const h20 = fc.h20 || {};
    keepOpen(el, `<summary>📈 過去經驗：20 天後上漲 ${rateS(h20.p_up)}，八成落在 ${fmt(h20.lo_px)}～${fmt(h20.hi_px)}
        <span class="s">26 年來任何一天之後的漲跌統計，換算成現在的點數（不是預測方向）</span></summary>
      <table class="wv-tbl"><tr><th>多久之後</th><th>上漲的機率</th><th>八成的情況落在</th></tr>${r('h5', '1 週（5 天）')}${r('h20', '1 個月（20 天）')}${r('h60', '3 個月（60 天）')}</table>
      <div class="wv-what">例：1 個月後「八成落在」＝過去 26 年，每 10 次有 8 次 20 天後的指數在這個範圍內，可以拿來估「正常會震盪多大」。
        圖上勾「歷史範圍」會畫成灰色錐形。（也試過只挑「跟現在情況相似的日子」來算，回測反而比較不準，所以用全部歷史。）</div>`);
  }

  function renderContext() {
    const c = S.context || {};
    const el = $('wv-ctx');
    const L = [];
    if (c.regime) L.push(['總經狀態', `${esc(c.regime.label)}（${md(c.regime.date)}）`, '下面總經面板七個因子的綜合判斷']);
    if (c.box) L.push(['均線格局', esc(c.box), '收盤在月線、100 日線上下的組合（宏爺的四種格局）']);
    if (c.mslope) L.push(['月線方向', `${pctS(c.mslope.slope)}・${esc(c.mslope.tier || '')}`, '月線每天變化的幅度（權證小哥的月線斜率）']);
    if (c.crash) L.push(['大跌買點', (c.crash.deep || []).length ? '<b style="color:var(--warn)">出現深跌訊號</b>' : `沒有（離 60 天高點 ${pctS(c.crash.dd * 100, 1)}，要 −15% 才算）`, '過去 5 次深跌，有 4 次之後 2～6 個月是賺的']);
    if (c.dist_day) L.push(['大盤出貨日', c.dist_day.dist_day ? '<b style="color:var(--warn)">今天是</b>' : '沒有', '研究發現不是賣出訊號（5 年 6 次之後都漲）']);
    const head = [c.regime ? esc(String(c.regime.label).replace(/^\S+\s/, '')) : '', c.box ? `格局${esc(c.box)}` : '',
                  c.crash ? ((c.crash.deep || []).length ? '有深跌訊號' : '沒有深跌訊號') : ''].filter(Boolean).join('、');
    keepOpen(el, `<summary>🧭 之前研究的訊號：${head || '—'}<span class="s">網站其他分頁研究過的大盤指標</span></summary>
      <table class="wv-tbl">${L.map(([k, v, m]) => `<tr><td style="white-space:nowrap;color:var(--muted)">${k}</td><td>${v}<div class="wv-why">${m}</div></td></tr>`).join('')}</table>`);
  }

  function renderResearch() {
    const r = S.research || {};
    const el = $('wv-research');
    const hold = r.hold || {};
    const NAME = { pivot: '前高前低', pivot_k3: '近期高低點', fib: '費波那契回檔', target: '波浪目標價', ma20: '月線', ma60: '季線', ma120: '半年線', ma240: '年線', round: '整數關卡', multi: '多種重疊' };
    const rows = Object.entries(hold).map(([k, v]) => `<tr><td>${esc(NAME[k] || k)}</td><td class="n">${rateS(v.rate)}</td><td class="n">${rateS(v.placebo)}</td><td>${v.pass ? '✅' : '△ 差不多'}</td></tr>`).join('');
    keepOpen(el, `<summary>🔬 這些方法準不準？（加權 26 年回測）<span class="s">結論：只有「前一晚費半」有效；費波那契、波浪、支撐壓力、籌碼都跟隨便猜差不多</span></summary>
      <ul>${(r.summary || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
      <table class="wv-tbl"><tr><th>價位種類</th><th>先反彈的機率</th><th>隨便畫線</th><th>結果</th></tr>${rows}</table>
      <div class="wv-what">「先反彈的機率」＝價格第一次碰到這個價位後，先反彈一段（約 1 天平均波動）的比例；跟「隨便挑同樣距離的價位」比。
        ✅ 要明顯比隨便畫線好、而且每個時期都一樣才算。${esc(r.data_end || '')} 為止，${esc(r.n_tests || '')} 個測試一起校正。
        <a href="/api/wave/report" target="_blank" rel="noopener">完整研究報告</a></div>`);
  }

  // ── K 線圖（預設只畫：K 棒、月線、季線、轉折、浪別、最近 2 支撐＋2 壓力、失效線）──
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
        height: el.clientHeight || 500, layout: { background: { type: 'solid', color: 'transparent' }, textColor: C.muted, fontSize: 13 },
        grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
        rightPriceScale: { borderColor: 'rgba(148,163,184,.2)', scaleMargins: { top: 0.1, bottom: 0.08 } },
        timeScale: { borderColor: 'rgba(148,163,184,.2)', rightOffset: 4 },
        crosshair: { mode: 0 }, localization: { priceFormatter: p => Math.round(p).toLocaleString('zh-TW') },
      });
      candle = chart.addCandlestickSeries({ upColor: C.up, downColor: C.down, wickUpColor: C.up, wickDownColor: C.down, borderVisible: false, priceLineVisible: false });
      const noScale = { autoscaleInfoProvider: () => null, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };
      ma['20'] = chart.addLineSeries({ color: 'rgba(250,204,21,.8)', lineWidth: 1, ...noScale });
      ma['60'] = chart.addLineSeries({ color: 'rgba(56,189,248,.8)', lineWidth: 1, ...noScale });
      zz = chart.addLineSeries({ color: 'rgba(147,170,255,.9)', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      for (let k = 0; k < 3; k++) cone.push(chart.addLineSeries({ color: 'rgba(148,163,184,.55)', lineWidth: 1, lineStyle: k === 1 ? 0 : 2, ...noScale }));
      if (window.ResizeObserver) new ResizeObserver(() => chart && chart.applyOptions({ width: el.clientWidth, height: el.clientHeight || 500 })).observe(el);
    }
    const weekly = st.iv === '1wk';
    const bars = (weekly ? S.chart.weekly : S.chart.bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }))) || [];
    if (!bars.length) { $('wv-legend').textContent = '沒有 K 線資料'; return; }
    candle.setData(bars);
    for (const k of ['20', '60']) ma[k].setData(weekly ? [] : (S.chart.ma[k] || []));
    // 轉折連線＋浪別（起點 0 不標）
    const w = S.waves[deg()] || {};
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
      const all = cnt.labels || [];
      all.forEach((x, j) => {
        if (x.label === '0') return;
        const prev = all[j - 1];
        const high = prev ? x.p > prev.p : true;
        marks.push({ time: T(x.date), position: high ? 'aboveBar' : 'belowBar', color: 'ABC'.includes(x.label) ? C.warn : '#c7d7ff',
                     shape: 'circle', size: 0.1, text: x.label + (x.tentative ? '?' : '') });
      });
    }
    marks.sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
    candle.setMarkers(marks);
    // 價位線
    pls.forEach(p => { try { candle.removePriceLine(p); } catch (e) { /* 已移除 */ } });
    pls = [];
    const add = (price, color, title, style = 2, width = 1, axis = true) => { if (num(price) != null) pls.push(candle.createPriceLine({ price: Number(price), color, lineWidth: width, lineStyle: style, axisLabelVisible: axis, title })); };
    const lv = (S.levels || {})[st.mode] || {};
    (lv.support || []).slice(0, 2).forEach(z => add(z.price, C.down, '撐'));
    (lv.resistance || []).slice(0, 2).forEach(z => add(z.price, C.up, '壓'));
    if (cnt && num(cnt.invalid) != null) add(cnt.invalid, C.warn, '失效', 0, 2);
    if (st.show.fib && w.fib) (w.fib.levels || []).forEach(f => add(f.price, C.fib, `${f.ratio}`, 1, 1, false));
    if (st.show.tg && cnt) (cnt.targets || []).filter(t => t.kind === 'end').slice(0, 2).forEach(t => add(t.price, C.warn, '目標', 1, 1, false));
    // 歷史範圍錐形（只有日 K、勾選才畫）
    const fc = S.forecast || {};
    if (!weekly && st.show.cone && fc.h5 && fc.h20) {
      const last = bars[bars.length - 1].time;
      const fd = futureDays(last, 20);
      const p0 = { time: last, value: S.price };
      cone[0].setData([p0, { time: fd[4], value: fc.h5.hi_px }, { time: fd[19], value: fc.h20.hi_px }]);
      cone[1].setData([p0, { time: fd[4], value: fc.h5.mid_px }, { time: fd[19], value: fc.h20.mid_px }]);
      cone[2].setData([p0, { time: fd[4], value: fc.h5.lo_px }, { time: fd[19], value: fc.h20.lo_px }]);
    } else cone.forEach(s => s.setData([]));
    const n = bars.length;
    const span = weekly ? 110 : (deg() === 'small' ? 90 : deg() === 'mid' ? 170 : 280);
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - span), to: n + (weekly ? 3 : (st.show.cone ? 22 : 4)) });
    $('wv-legend').innerHTML = `<span><b style="color:#facc15">━</b> 月線</span><span><b style="color:#38bdf8">━</b> 季線</span>
      <span><b style="color:#93aaff">━</b> 波浪轉折（數字＝第幾段，${st.alt ? '替代' : '主要'}劇本）</span>
      <span><b style="color:${C.down}">┅</b> 支撐</span><span><b style="color:${C.up}">┅</b> 壓力</span><span><b style="color:${C.warn}">━</b> 劇本失效</span>
      ${S.chart.bars.length && S.chart.bars[S.chart.bars.length - 1].partial ? '<span>最後一根是盤中</span>' : ''}`;
  }

  // ── 🤖 AI 圓桌 ──
  async function loadPanel() {
    try {
      panelData = await (await fetch('/api/wave/panel')).json();
      renderPanel(panelData);
      if (S) renderSummary();
      if (panelData.running && !panelPoll) pollJob(panelData.running);
    } catch (e) { $('wv-ai').innerHTML = `<div class="wv-h3">🤖 AI 圓桌</div><div class="wv-dim">載入失敗：${esc(e.message)}</div>`; }
  }

  function renderPanel(d) {
    const ps = d.providers || [];
    const r = d.result;
    const btnTxt = d.running ? '⏳ 討論中…（約 2 分鐘）' : (r ? `🔄 再討論一次（今天還剩 ${d.manual_left} 次）` : `▶ 開始討論（今天還剩 ${d.manual_left} 次）`);
    const btn = ps.length ? `<button class="btn" id="wv-ai-run" ${d.running || !d.manual_left ? 'disabled' : ''}>${btnTxt}</button>` : '';
    let html = `<div class="wv-h3">🤖 AI 圓桌 ${btn}</div>
      <div class="wv-dim">參加：${ps.map(p => esc(p.name)).join('、') || '還沒設定 AI 金鑰'}。先各自看系統資料寫看法、再互相回應，最後整理共識和分歧。</div>`;
    if (d.note) html += `<div class="wv-note">${esc(d.note)}</div>`;
    if (!r) { $('wv-ai').innerHTML = html + '<div class="wv-what">還沒有討論紀錄：每個交易日 16:30 自動討論一次，或按上面的按鈕（約 2 分鐘）。</div>'; bindRun(); return; }
    const mo = r.moderator || {};
    const stanceColor = s => /多/.test(s || '') ? 'var(--up)' : /空/.test(s || '') ? 'var(--down)' : 'var(--muted)';
    const mode = { roundtable: '', single: `⚠ 只有 ${esc(((r.participants || [])[0] || {}).name || '')} 的看法（其他 AI 沒回應）`, none: '⚠ AI 都沒回應' }[r.mode] || '';
    if (mode) html += `<div class="wv-note">${mode}</div>`;
    if (mo.summary) {
      html += `<div class="wv-ai-sum"><span class="wv-stance" style="background:${stanceBg(mo.stance)};color:${stanceColor(mo.stance)}">${esc(mo.stance || '')}</span>
        <b>${esc(mo.summary)}</b> <span class="wv-dim">（${esc(mo.agree_count || '')} 位同意；信心 ${esc(mo.confidence || '')}）</span></div>
        <div class="wv-ai-grid">
          <div><b>大家都同意</b><ul>${(mo.consensus || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
          <div><b>意見不同</b><ul>${(mo.disagreements || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
        </div>
        <div style="margin-top:8px"><b>短線：</b>${esc(mo.short || '')}<br><b>波段：</b>${esc(mo.swing || '')}</div>
        <div class="wv-chips">${(mo.watch_levels || []).map(w => `<span class="wv-chip"><b>${fmt(w.price)}</b> ${esc(w.why || '')}</span>`).join('')}</div>`;
    }
    if ((r.flagged || []).length) html += `<div class="wv-note">⚠ 這些價位是 AI 自己算的、不是系統價位，不可靠：${r.flagged.map(v => fmt(v)).join('、')}</div>`;
    const ids = Object.keys(r.round1 || {});
    html += `<details class="wv-who"><summary>看每位 AI 說了什麼（兩輪）</summary>` + ids.map(id => {
      const a = r.round1[id] || {}, b = (r.round2 || {})[id];
      return `<div style="margin:8px 0;padding-top:6px;border-top:1px dashed var(--border)"><b>${esc(a.name)}</b>：<b style="color:${stanceColor(a.stance)}">${esc(a.stance || '')}</b>
        <div>第一輪：${esc(a.short || '')}${a.swing ? '；' + esc(a.swing) : ''}</div>
        ${b ? `<div>第二輪（${esc(b.stance || '')}）：${esc(b.view || '')}${(b.disagree || []).length ? `<div class="wv-dim">不同意：${(b.disagree || []).map(esc).join('；')}</div>` : ''}</div>` : '<div class="wv-dim">第二輪沒有回應</div>'}</div>`;
    }).join('') + (r.failed || []).map(f => `<div class="wv-dim">${esc(f.name)} 第 ${esc(f.round)} 輪沒回應</div>`).join('') + '</details>';
    const nw = r.news || {};
    if ((nw.items || []).length) html += `<details class="wv-who"><summary>討論用的新聞（Google 搜尋近 7 天，${nw.items.length} 則）</summary>
      <ul>${nw.items.map(x => `<li>${esc(x.date || '')} ${esc(x.title)}<span class="wv-dim">：${esc(x.why || '')}</span></li>`).join('')}</ul>
      <div class="wv-dim">${(nw.sources || []).slice(0, 8).map(s => `<a href="${esc(s.uri)}" target="_blank" rel="noopener">${esc(s.title || '來源')}</a>`).join('、')}</div></details>`;
    html += `<div class="wv-what">${esc(md(r.day))} ${esc((r.finished || '').slice(11, 16))}（${r.trigger === 'manual' ? '手動' : '每日自動'}）。AI 只能用系統算的價位，自己編的會標 ⚠；AI 看法不是系統計算、不是投資建議。</div>`;
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

  // ── 控制 ──
  function bind() {
    document.querySelectorAll('[data-wv-mode]').forEach(b => b.onclick = () => { st.mode = b.dataset.wvMode; lsSet('wv_mode', st.mode); if (S) render(); });
    document.querySelectorAll('[data-wv-iv]').forEach(b => b.onclick = () => { st.iv = b.dataset.wvIv; lsSet('wv_iv', st.iv); if (S) { renderHead(); drawChart(); } });
    document.querySelectorAll('[data-wv-deg]').forEach(b => b.onclick = () => { st.degSel = b.dataset.wvDeg; lsSet('wv_deg2', st.degSel); if (S) render(); });
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
    setInterval(() => { if (isSession() && document.visibilityState === 'visible') load(false); }, 120000);
  });
})();
