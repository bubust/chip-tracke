// 🎫 可轉債分頁（dashboard 內嵌）。資料：/api/cb/*
'use strict';

let _cbRows = [];
let _cbFilter = 'buy';
let _cbLoaded = false;
let _cbPoll = null;
let _cbSort = { col: null, dir: 1 };
const _CB_COLS = [
  ['可轉債', 'code'], ['分類', 'tier', '分類＋評分'], ['CB 價', 'cb_price', 'CB 收市價（百元價）'], ['股價', 'stock_price'],
  ['轉換價', 'conv_price', '目前轉換價（公告調整／發行時／手動）'], ['理論價', 'parity', '股價 ÷ 轉換價 × 100'],
  ['溢價', 'premium_pct', 'CB 價 ÷ 理論價 − 1；正＝溢價（CB 比理論價貴）'],
  ['六大流程', 'flow', '①低檔發債 ②營收成長 ③利多消息 ④融券大增 ⑤CB量大增 ⑥融券大減（紅＝符合，④綠＝出場警訊，虛線＝無資料）'],
  ['營收年增', 'rev_yoy', '單月營收年增率'], ['融券 5 日', 'short_chg5', '發行公司融券餘額 5 日變化（張）'],
  ['CB 量', 'cb_vol', '最近一日成交張數／20 日均量'], ['已轉換', 'converted_pct', '1 − 流通在外 ÷ 發行額'],
  ['時機', 'stage'], ['到期', 'days_to_maturity'],
];
function cbSortBy(col) {
  _cbSort = _cbSort.col === col ? { col, dir: -_cbSort.dir } : { col, dir: ['code', 'tier', 'days_to_maturity', 'premium_pct', 'converted_pct', 'cb_price'].includes(col) ? 1 : -1 };
  cbRender();
}
const _CB_TIER = {
  buy: { label: '可以買', cls: 'sig-buy', color: '#ef4444' },
  chance: { label: '有機會', cls: 'sig-watch', color: '#f59e0b' },
  exit: { label: '該出場', cls: 'sig-avoid', color: '#22c55e' },
  watch: { label: '觀察', cls: 'sig-info', color: '#94a3b8' },
};
const _cbE = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const _cbN = (v, dp = 2) => v == null ? '—' : Number(v).toLocaleString('zh-TW', { maximumFractionDigits: dp, minimumFractionDigits: dp });
const _cbD = d => d ? String(d).slice(2).replace(/-/g, '/') : '—';
const _cbP = v => v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`;

function cbOnShow() {
  if (typeof _guideRemember === 'function') _guideRemember('cb-guide');
  if (!_cbLoaded) { _cbLoaded = true; cbLoad(); }
}

async function cbLoad() {
  const body = document.getElementById('cb-body');
  body.innerHTML = '<div style="color:var(--muted);text-align:center;padding:30px">載入中...</div>';
  try {
    const r = await api('GET', '/api/cb/list');
    _cbRows = r.rows || [];
    _cbStatus(r.status);
    cbRender();
    if (r.status?.job?.running) _cbWatch();
  } catch (e) { body.innerHTML = `<div style="color:var(--red)">載入失敗：${_cbE(e.message)}</div>`; }
}

function _cbStatus(s) {
  if (!s) return;
  document.getElementById('cb-status').textContent = [
    `${s.bonds || 0} 檔可轉債`, s.last_quote ? `行情到 ${s.last_quote}（${s.quote_days} 天）` : '尚無行情',
    s.last_refresh ? `上次更新 ${s.last_refresh}：${s.last_message || ''}` : '尚未更新'].join(' · ');
  const err = document.getElementById('cb-error');
  if (s.last_errors) { err.style.display = ''; err.textContent = '⚠️ ' + s.last_errors.split('\n').slice(0, 3).join('；'); }
  else err.style.display = 'none';
}

function _cbRecent(r) {
  if (!r.cb_date) return false;
  return (Date.now() - new Date(r.cb_date).getTime()) / 864e5 <= 8 && r.cb_vol != null;
}

function cbRender() {
  const stage = document.getElementById('cb-stage').value, par = document.getElementById('cb-par').checked,
    grab = document.getElementById('cb-grab').checked, traded = document.getElementById('cb-traded').checked,
    q = document.getElementById('cb-search').value.trim();
  const base = _cbRows.filter(r => (!traded || _cbRecent(r))
    && (!stage || (stage === 'new' ? r.stage.some(x => x.startsWith('定價')) : r.stage.some(x => !x.startsWith('定價'))))
    && (!par || r.near_par) && (!grab || r.grab)
    && (!q || r.code.includes(q) || (r.name || '').includes(q) || (r.sid || '').includes(q) || (r.issuer || '').includes(q)));
  const counts = { all: base.length };
  base.forEach(r => { counts[r.tier] = (counts[r.tier] || 0) + 1; });
  document.getElementById('cb-chips').innerHTML = ['buy', 'chance', 'exit', 'watch', 'all'].map(k => {
    const t = _CB_TIER[k] || { label: '全部', color: 'var(--accent)' }, on = _cbFilter === k;
    return `<button onclick="_cbFilter='${k}';cbRender()" style="cursor:pointer;border-radius:14px;padding:3px 12px;font-size:.8rem;border:1px solid ${on ? t.color : '#30363d'};background:${on ? t.color + '22' : 'transparent'};color:${on ? t.color : 'var(--muted)'}">${t.label} <b>${counts[k] || 0}</b></button>`;
  }).join('');
  const rows = base.filter(r => _cbFilter === 'all' || r.tier === _cbFilter);
  if (_cbSort.col) {
    const k = _cbSort.col, d = _cbSort.dir;
    const v = r => k === 'flow' ? r.flow.filter(f => f.on && f.n !== 4).length : k === 'tier' ? ({ buy: 0, chance: 1, exit: 2, watch: 3 }[r.tier] * 100 - r.score)
      : k === 'stage' ? r.stage.length : r[k];
    rows.sort((a, b) => { const x = v(a), y = v(b);
      if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
      return (typeof x === 'string' ? x.localeCompare(y) : x - y) * d; });
  }
  const body = document.getElementById('cb-body');
  if (!rows.length) {
    body.innerHTML = `<div style="color:var(--muted);text-align:center;padding:30px">${_cbRows.length ? '沒有符合條件的可轉債' : '尚無資料：按「🔄 更新資料」（第一次約 10～15 分鐘）'}</div>`;
    return;
  }
  const td = (v, x = '') => `<td style="padding:5px 8px;white-space:nowrap;${x}">${v}</td>`;
  const flow = r => r.flow.map(f => `<span title="${f.n}. ${_cbE(f.name)}${f.unknown ? '（無資料）' : ''}" style="display:inline-block;width:15px;height:15px;line-height:15px;text-align:center;border-radius:50%;font-size:.62rem;margin-right:1px;${
    f.on ? (f.n === 4 ? 'background:#22c55e;color:#000' : 'background:#ef4444;color:#fff') : f.unknown ? 'border:1px dashed #30363d;color:#484f58' : 'border:1px solid #30363d;color:var(--muted)'}">${f.n}</span>`).join('');
  body.innerHTML = `<div class="tbl-wrap" style="overflow-x:auto"><table style="width:100%;font-size:.8rem;border-collapse:collapse">
    <thead><tr style="background:#1c2128;color:var(--muted)">${_CB_COLS.map(([lab, key, tip]) => {
      const arrow = _cbSort.col === key ? (_cbSort.dir > 0 ? ' ▲' : ' ▼') : '';
      return `<th title="${_cbE(tip || '點一下排序')}" onclick="cbSortBy('${key}')" style="cursor:pointer;user-select:none;padding:6px 8px;white-space:nowrap${key === 'code' ? ';text-align:left' : ''}">${lab}${arrow}</th>`;
    }).join('')}
    </tr></thead><tbody>${rows.map(r => {
      const t = _CB_TIER[r.tier];
      return `<tr style="border-top:1px solid #21262d;cursor:pointer" onclick="cbDetail('${_cbE(r.code)}')">
        ${td(`<b style="color:var(--accent)">${_cbE(r.code)}</b> ${_cbE(r.name || '')}<br><span style="font-size:.7rem;color:var(--muted)">${_cbE(r.sid)} ${_cbE(r.issuer || '')}</span>`)}
        ${td(`<span class="sig ${t.cls}">${t.label}</span><br><span style="font-size:.66rem;color:var(--muted)">${r.score} 分</span>`)}
        ${td(`<b>${_cbN(r.cb_price)}</b>${r.near_par ? `<br><span style="font-size:.66rem;color:#ef4444">${r.cb_price < 100 ? '低於面額' : '貼近面額'}</span>` : ''}`, 'text-align:right')}
        ${td(_cbN(r.stock_price), 'text-align:right')}
        ${td(`${_cbN(r.conv_price)}${r.conv_src !== '發行時' ? `<br><span style="font-size:.64rem;color:var(--muted)">${r.conv_src === '手動' ? '手動' : '已調整'}</span>` : ''}`, 'text-align:right')}
        ${td(_cbN(r.parity, 1), 'text-align:right')}
        ${td(_cbP(r.premium_pct) + (r.grab ? '<br><span style="font-size:.64rem;color:#ef4444">🔥搶購</span>' : r.lock ? '<br><span style="font-size:.64rem;color:#22c55e">鎖利</span>' : ''), `text-align:right;color:${r.premium_pct == null ? 'var(--muted)' : r.grab ? '#ef4444' : 'var(--text)'}`)}
        ${td(flow(r))}
        ${td(_cbP(r.rev_yoy) + (r.rev_turn ? '<br><span style="font-size:.64rem;color:#ef4444">負轉正</span>' : ''), `text-align:right;color:${r.rev_yoy == null ? 'var(--muted)' : r.rev_yoy > 0 ? '#ef4444' : '#22c55e'}`)}
        ${td(r.short_chg5 == null ? (r.short_now != null ? _cbN(r.short_now, 0) + ' 張' : '—') : `${r.short_chg5 >= 0 ? '+' : ''}${_cbN(r.short_chg5, 0)}<br><span style="font-size:.64rem;color:var(--muted)">餘 ${_cbN(r.short_now, 0)}</span>`,
          `text-align:right;${r.short_surge ? 'color:#22c55e;font-weight:700' : r.short_drop ? 'color:#ef4444;font-weight:700' : ''}`)}
        ${td(r.cb_vol != null ? `${_cbN(r.cb_vol, 0)}<span style="color:var(--muted)">／${_cbN(r.cb_vol_avg20, 0)}</span>` : '—', `text-align:right;${r.cb_vol_surge ? 'color:#ef4444;font-weight:700' : ''}`)}
        ${td(r.converted_pct != null ? r.converted_pct.toFixed(1) + '%' : '—', 'text-align:right')}
        ${td(r.stage.length ? r.stage.map(_cbE).join('<br>') : '<span class="muted">—</span>', 'font-size:.74rem')}
        ${td(_cbD(r.maturity_date) + (r.days_to_maturity != null && r.days_to_maturity <= 365 ? `<br><span style="font-size:.66rem;color:#f59e0b">剩 ${r.days_to_maturity} 天</span>` : ''))}
      </tr>`;
    }).join('')}</tbody></table></div>`;
}

function cbDetail(code) {
  const r = _cbRows.find(x => x.code === code);
  if (!r) return;
  const t = _CB_TIER[r.tier];
  const m = document.createElement('div');
  m.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:10001;display:flex;align-items:center;justify-content:center;padding:16px';
  m.onclick = e => { if (e.target === m) m.remove(); };
  const line = (k, v) => `<div><span class="muted">${k}</span>　${v}</div>`;
  const li = (arr, c) => arr.length ? `<ul style="margin:2px 0 6px;padding-left:18px;color:${c}">${arr.map(x => `<li>${_cbE(x)}</li>`).join('')}</ul>` : '';
  m.innerHTML = `<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;max-width:560px;width:100%;max-height:88vh;overflow:auto;font-size:.85rem;line-height:1.8">
    <div style="display:flex;justify-content:space-between;align-items:center"><b style="font-size:1rem">${_cbE(r.code)} ${_cbE(r.name || '')}　<span class="sig ${t.cls}">${t.label}</span></b>
      <button class="btn sm ghost" onclick="this.closest('div[style*=fixed]').remove()">✕</button></div>
    <div class="muted" style="font-size:.76rem">發行公司 ${_cbE(r.sid)} ${_cbE(r.issuer || '')}　評分 ${r.score}</div>
    ${r.good.length ? `<div style="margin-top:6px"><b style="color:#ef4444">👍 加分</b>${li(r.good, 'var(--text)')}</div>` : ''}
    ${r.warn.length ? `<div><b style="color:#22c55e">⚠️ 注意</b>${li(r.warn, 'var(--text)')}</div>` : ''}
    <div style="margin:4px 0 8px"><b>六大流程</b>　${r.flow.map(f => `<span style="margin-right:8px;${f.on ? (f.n === 4 ? 'color:#22c55e;font-weight:700' : 'color:#ef4444;font-weight:700') : 'color:var(--muted)'}">${f.on ? '●' : f.unknown ? '◌' : '○'} ${f.n}.${_cbE(f.name)}</span>`).join('')}</div>
    ${line('CB 價', `${_cbN(r.cb_price)}（${_cbE(r.cb_date || '—')}）`)}
    ${line('股價', `${_cbN(r.stock_price)}${r.ma60 ? `（季線 ${_cbN(r.ma60)}，${r.above_ma60 ? '站上' : '跌破'}）` : ''}`)}
    ${line('轉換價', `${_cbN(r.conv_price)}（${_cbE(r.conv_src)}）　每張可換 ${_cbN(r.shares_per_bond, 0)} 股`)}
    ${line('理論價', r.parity == null ? '沒有股價資料' : `${_cbN(r.parity, 2)} ＝ ${_cbN(r.stock_price)} ÷ ${_cbN(r.conv_price)} × 100　→ CB ${r.premium_pct >= 0 ? `溢價 ${_cbP(r.premium_pct)}${r.grab ? '，<b style="color:#ef4444">搶購訊號：大戶搶 CB、看好現股</b>' : ''}` : `折價 ${_cbP(r.premium_pct)}${r.lock ? '，<b style="color:#22c55e">高檔融券鎖利</b>' : ''}`}${r.cb_5d_pct != null ? `（CB 5 日 ${_cbP(r.cb_5d_pct)}）` : ''}`)}
    ${line('發行／到期', `${_cbE(r.issue_date || '—')} ～ ${_cbE(r.maturity_date || '—')}${r.put_date ? `　賣回日 ${_cbE(r.put_date)}` : ''}`)}
    ${line('發債時股價位置', r.issue_pos == null ? '股價資料不足' : `一年區間的 ${(r.issue_pos * 100).toFixed(0)}%${r.issue_pos <= 0.4 ? '（低檔發債）' : ''}`)}
    ${line('已轉換率', r.converted_pct != null ? `${r.converted_pct}%（流通在外 ${_cbN(r.outstanding_yi)} 億）` : '—')}
    ${line('營收', r.rev_yoy != null ? `${_cbE(r.rev_ym)}：單月年增 ${_cbP(r.rev_yoy)}、累計 ${_cbP(r.rev_cum_yoy)}` : '—')}
    ${line('融券', r.short_now != null ? `餘額 ${_cbN(r.short_now, 0)} 張${r.short_chg5 != null ? `，5 日 ${r.short_chg5 >= 0 ? '+' : ''}${_cbN(r.short_chg5, 0)} 張（${_cbP(r.short_chg5_pct)}）` : ''}` : '無資料（沒有融券就看技術分析）')}
    ${line('CB 成交量', r.cb_vol != null ? `${_cbN(r.cb_vol, 0)} 張（20 日均 ${_cbN(r.cb_vol_avg20, 0)}）` : '—')}
    <div style="margin-top:8px;padding:8px;border:1px solid #30363d;border-radius:8px">
      <div class="muted" style="font-size:.76rem;margin-bottom:4px">手動補充（好債：股東人數少、委買高；轉換價不對可以改）</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px">
        <label style="font-size:.74rem;color:var(--muted)">目前轉換價<input id="cbm-conv" type="number" step="0.01" value="${r.conv_src === '手動' ? r.conv_price : ''}" placeholder="${_cbN(r.conv_price)}" style="width:100%;font-size:16px"></label>
        <label style="font-size:.74rem;color:var(--muted)">CB 股東人數<input id="cbm-holders" type="number" value="${r.holders ?? ''}" style="width:100%;font-size:16px"></label>
        <label style="font-size:.74rem;color:var(--muted);grid-column:1/-1">備註<input id="cbm-note" value="${_cbE(r.note || '')}" placeholder="利多消息、委買狀況…" style="width:100%;font-size:16px"></label>
      </div>
      <div style="text-align:right;margin-top:6px"><button class="btn sm" onclick="cbSaveManual('${_cbE(r.code)}', this)">儲存</button></div>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">
      <button class="btn sm ghost" onclick="this.closest('div[style*=fixed]').remove();cbChart('${_cbE(r.code)}')">📈 股票 K 線</button>
      <button class="btn sm ghost" style="color:#22c55e" onclick="cbAddWl('${_cbE(r.code)}')">+ 觀察清單</button>
    </div></div>`;
  document.body.appendChild(m);
}

async function cbSaveManual(code, btn) {
  const v = id => document.getElementById(id).value.trim();
  try {
    await api('PUT', `/api/cb/manual/${encodeURIComponent(code)}`, {
      conv_price: v('cbm-conv') ? Number(v('cbm-conv')) : null, holders: v('cbm-holders') ? Number(v('cbm-holders')) : null, note: v('cbm-note') });
    btn.closest('div[style*=fixed]').remove();
    toast('已儲存');
    cbLoad();
  } catch (e) { toast(e.message, true); }
}

function cbChart(code) {
  const r = _cbRows.find(x => x.code === code);
  if (!r) return;
  const ids = [...new Set(_cbRows.filter(x => _cbFilter === 'all' || x.tier === _cbFilter).map(x => x.sid))];
  _frozenChartList = ids.length ? ids : [r.sid];
  _frozenChartIdx = Math.max(0, _frozenChartList.indexOf(r.sid));
  if (r.issuer) _chartNames[r.sid] = r.issuer;
  _chartSource = '可轉債'; _chartOhlcvUrl = null; _resetChartPeriod();
  openChart(r.sid);
}

async function cbAddWl(code) {
  const r = _cbRows.find(x => x.code === code);
  if (!r) return;
  const note = `可轉債 ${r.code}`;
  try {
    await api('POST', '/api/watchlist', { stock_id: r.sid, name: r.issuer || '', note });
    if (!_wlData.find(x => x.stock_id === r.sid)) _wlData.push({ stock_id: r.sid, name: r.issuer || '', memo: '', note, has_data: false });
    const ls = lsLoadWatchlist();
    if (!ls.find(x => x.stock_id === r.sid)) { ls.push({ stock_id: r.sid, name: r.issuer || '', memo: '', note }); lsSaveWatchlist(ls); }
    renderWatchlist();
    toast(`已加入觀察清單：${r.sid} ${r.issuer || ''}`);
  } catch (e) { toast(e.message, true); }
}

async function cbRefresh() {
  try { const r = await api('POST', '/api/cb/refresh'); toast(r.message, !r.ok); _cbWatch(); } catch (e) { toast(e.message, true); }
}

function _cbWatch() {
  clearTimeout(_cbPoll);
  const el = document.getElementById('cb-progress');
  const tick = async () => {
    try {
      const s = await api('GET', '/api/cb/status');
      if (s.job?.running) {
        el.style.display = ''; el.textContent = `更新中… ${s.job.step || ''}${s.job.total ? ` ${s.job.progress}/${s.job.total}` : ''}`;
        _cbPoll = setTimeout(tick, 3000);
      } else { el.style.display = 'none'; cbLoad(); }
    } catch (e) { el.style.display = 'none'; }
  };
  tick();
}
