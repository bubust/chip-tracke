// 💬 戰略討論區（dashboard 內嵌）：貼跟老大哥的對話（文字／截圖）→ AI 找股票、題材、產業鏈、大哥／小弟、同族群，
// 每檔接上戰術中心的資料（現價、均線、今天中的策略、千張大戶、產業輪動、支撐／停損／目標），並追蹤「他提過的股票後來表現」。資料：/api/discuss/*
'use strict';

let _dcImgs = [];            // [{mime, data, url}]
let _dcSession = null;       // 目前顯示的分析
let _dcQuotes = {};          // {sid: quotes}
let _dcLevels = {};          // {sid: levels}
let _dcView = 'result';      // result | history | tracker | alias
let _dcInited = false;
let _dcPoll = null;

const _dcPct = (v, dp = 1) => v == null ? '<span class="muted">—</span>'
  : `<span style="color:${v > 0 ? 'var(--up)' : v < 0 ? 'var(--down)' : 'var(--muted)'}">${v > 0 ? '+' : ''}${Number(v).toFixed(dp)}%</span>`;
const _dcDate = d => d ? String(d).replace(/-/g, '').replace(/^(\d{4})(\d{2})(\d{2})$/, '$2/$3') : '—';
const _DC_ROLE = { leader: '<span class="dc-tag dc-lead">大哥</span>', follower: '<span class="dc-tag dc-follow">小弟</span>' };
const _DC_STANCE = { '看多': 'var(--up)', '看空': 'var(--down)', '中性': 'var(--muted)', '觀望': 'var(--yellow)' };
const _DC_CONF = { confirmed: ['✔ 已確認', '#22c55e'], high: ['高', '#22c55e'], medium: ['中', '#eab308'], low: ['不確定', '#f97316'] };

function _dcTodayTW() {
  return new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 10);
}

function discussOnShow() {
  if (!_dcInited) { _dcInited = true; _dcRenderShell(); _dcStatus(); dcSwitch('history', true); }
}

function _dcRenderShell() {
  document.getElementById('dc-root').innerHTML = `
    <div class="dc-input">
      <textarea id="dc-text" rows="5" placeholder="貼上對話文字…（截圖可以直接 Ctrl+V 貼在這裡，或按「📷 選截圖」）"></textarea>
      <div id="dc-imgs" class="dc-imgs"></div>
      <div class="dc-row">
        <label class="btn sm ghost" style="cursor:pointer">📷 選截圖<input type="file" accept="image/*" multiple style="display:none" onchange="dcPickFiles(this)"></label>
        <label style="font-size:.8rem;color:var(--muted)">對話日期 <input type="date" id="dc-date" value="${_dcTodayTW()}" style="padding:4px 8px"></label>
        <button class="btn" id="dc-go" onclick="dcAnalyze()">🔍 分析</button>
        <span id="dc-msg" style="font-size:.8rem;color:var(--muted)"></span>
      </div>
      <div style="font-size:.72rem;color:var(--muted);margin-top:4px">記錄價＝對話日期當天收盤（追蹤他提過的股票後來漲跌）。AI 用 Gemini 免費版：Google 可能拿內容去訓練，私人對話別貼。<span id="dc-quota"></span></div>
    </div>
    <div class="dc-subtabs">
      <button data-v="result" onclick="dcSwitch('result')">這次結果</button>
      <button data-v="history" onclick="dcSwitch('history')">歷史紀錄</button>
      <button data-v="tracker" onclick="dcSwitch('tracker')">📈 他提過的股票表現</button>
      <button data-v="alias" onclick="dcSwitch('alias')">暱稱對照</button>
    </div>
    <div id="dc-body"></div>`;
  const ta = document.getElementById('dc-text');
  ta.addEventListener('paste', _dcOnPaste);
  ta.addEventListener('dragover', e => e.preventDefault());
  ta.addEventListener('drop', e => { e.preventDefault(); _dcAddFiles([...(e.dataTransfer?.files || [])]); });
}

async function _dcStatus() {
  try {
    const s = await api('GET', '/api/discuss/status');
    document.getElementById('dc-quota').textContent = s.has_key ? ` 今天分析 ${s.today}／${s.limit} 次。` : '';
    if (!s.has_key) document.getElementById('dc-msg').innerHTML = '<span style="color:var(--orange)">⚠️ 伺服器還沒設定 Gemini 金鑰（GEMINI_API_KEY）</span>';
  } catch (e) {}
}

// ── 截圖 ──
function _dcOnPaste(e) {
  const files = [...(e.clipboardData?.items || [])].filter(it => it.type.startsWith('image/')).map(it => it.getAsFile()).filter(Boolean);
  if (files.length) { e.preventDefault(); _dcAddFiles(files); }
}
function dcPickFiles(inp) { _dcAddFiles([...inp.files]); inp.value = ''; }

async function _dcAddFiles(files) {
  for (const f of files) {
    if (!f.type.startsWith('image/')) continue;
    if (_dcImgs.length >= 8) { toast('截圖最多 8 張'); break; }
    try { _dcImgs.push(await _dcShrink(f)); } catch (e) { toast('讀不到這張圖：' + e.message); }
  }
  _dcRenderImgs();
}

// 長邊超過 1800px 才縮（聊天截圖要看得清楚字），轉 JPEG 減少上傳量
function _dcShrink(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, 1800 / Math.max(img.width, img.height));
      const cv = document.createElement('canvas');
      cv.width = Math.round(img.width * k); cv.height = Math.round(img.height * k);
      const ctx = cv.getContext('2d');
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cv.width, cv.height);
      ctx.drawImage(img, 0, 0, cv.width, cv.height);
      const dataUrl = cv.toDataURL('image/jpeg', 0.9);
      resolve({ mime: 'image/jpeg', data: dataUrl.split(',')[1], url: dataUrl });
      URL.revokeObjectURL(url);
    };
    img.onerror = () => reject(new Error('格式不支援'));
    img.src = url;
  });
}

function _dcRenderImgs() {
  document.getElementById('dc-imgs').innerHTML = _dcImgs.map((im, i) =>
    `<div class="dc-thumb"><img src="${im.url}" alt=""><button onclick="dcRemoveImg(${i})" title="移除">✕</button></div>`).join('');
}
function dcRemoveImg(i) { _dcImgs.splice(i, 1); _dcRenderImgs(); }

// ── 分析 ──
async function dcAnalyze() {
  const text = document.getElementById('dc-text').value.trim();
  if (!text && !_dcImgs.length) { toast('請貼上對話文字或截圖'); return; }
  const btn = document.getElementById('dc-go'), msg = document.getElementById('dc-msg');
  btn.disabled = true;
  msg.textContent = '送出中…';
  try {
    const r = await api('POST', '/api/discuss/analyze', {
      text, chat_date: document.getElementById('dc-date').value || _dcTodayTW(),
      images: _dcImgs.map(({ mime, data }) => ({ mime, data })),
    });
    _dcWatch(r.job_id);
  } catch (e) { msg.innerHTML = `<span style="color:var(--red)">${_esc(e.message)}</span>`; btn.disabled = false; }
}

function _dcWatch(jid) {
  clearInterval(_dcPoll);
  const btn = document.getElementById('dc-go'), msg = document.getElementById('dc-msg');
  _dcPoll = setInterval(async () => {
    try {
      const j = await api('GET', `/api/discuss/job/${jid}`);
      msg.textContent = `${j.step}（${j.elapsed} 秒）`;
      if (j.status === 'running') return;
      clearInterval(_dcPoll);
      btn.disabled = false;
      _dcStatus();
      if (j.status === 'error') { msg.innerHTML = `<span style="color:var(--red)">${_esc(j.error)}</span>`; return; }
      msg.textContent = `✅ 分析完成（${j.elapsed} 秒）`;
      document.getElementById('dc-text').value = '';
      _dcImgs = []; _dcRenderImgs();
      await dcOpen(j.session_id);
    } catch (e) { clearInterval(_dcPoll); btn.disabled = false; msg.innerHTML = `<span style="color:var(--red)">${_esc(e.message)}</span>`; }
  }, 2000);
}

function dcSwitch(v, quiet) {
  _dcView = v;
  document.querySelectorAll('.dc-subtabs button').forEach(b => b.classList.toggle('active', b.dataset.v === v));
  if (v === 'result') _dcRenderResult();
  else if (v === 'history') _dcLoadHistory(quiet);
  else if (v === 'tracker') _dcLoadTracker();
  else if (v === 'alias') _dcLoadAlias();
}

async function dcOpen(id) {
  const body = document.getElementById('dc-body');
  body.innerHTML = '<div class="muted" style="padding:20px;text-align:center">載入中...</div>';
  try {
    _dcSession = await api('GET', `/api/discuss/session/${id}`);
    _dcQuotes = {}; _dcLevels = {};
    dcSwitch('result');
    _dcLoadMarket();
  } catch (e) { body.innerHTML = `<div style="color:var(--red)">載入失敗：${_esc(e.message)}</div>`; }
}

function _dcAllIds(s) {
  const r = s.result || {}, ids = [];
  (r.mentions || []).forEach(m => m.stock_id && ids.push(m.stock_id));
  (r.related || []).forEach(x => ids.push(x.stock_id));
  (r.themes || []).forEach(t => (t.chain || []).forEach(seg => (seg.stocks || []).forEach(x => ids.push(x.stock_id))));
  return [...new Set(ids)];
}

async function _dcLoadMarket() {
  const s = _dcSession;
  if (!s) return;
  const ids = _dcAllIds(s);
  if (!ids.length) return;
  try { _dcQuotes = await api('GET', `/api/discuss/quotes?ids=${ids.join(',')}`); } catch (e) {}
  if (_dcSession === s && _dcView === 'result') _dcRenderResult();
  // 支撐／停損／目標比較慢（要算關鍵價位），對話提到的＋同族群先算
  const key = [...new Set([...(s.result.mentions || []).map(m => m.stock_id).filter(Boolean), ...(s.result.related || []).map(x => x.stock_id)])].slice(0, 40);
  if (!key.length) return;
  try { _dcLevels = await api('GET', `/api/levels?ids=${key.join(',')}`); } catch (e) {}
  if (_dcSession === s && _dcView === 'result') _dcRenderResult();
}

// ── 這次結果 ──
function _dcStockCell(sid, name) {
  if (name) _chartNames[sid] = name;
  return `<a class="dc-link" href="javascript:void(0)" onclick="openChart('${_jsq(sid)}')" title="看 K 線"><b>${_esc(sid)}</b> ${_esc(name || '')}</a>`;
}

function _dcMarketTds(sid) {
  const q = _dcQuotes[sid], lv = _dcLevels[sid];
  if (!q) return `<td colspan="7" class="muted" style="font-size:.75rem">${Object.keys(_dcQuotes).length ? '沒有價格資料' : '載入中…'}</td>`;
  // 只列現在還在的策略（舊掃描結果可能有已刪掉的策略）
  const strat = (q.strategies || []).filter(k => typeof STRATEGY_SHORT === 'undefined' || STRATEGY_SHORT[k]).map(k => `<span class="dc-chip">${_esc((typeof STRATEGY_SHORT !== 'undefined' && STRATEGY_SHORT[k]) || k)}</span>`).join(' ') || '<span class="muted">—</span>';
  const sec = q.sector ? `${_esc(q.sector.sector_name || '')}${q.sector.relative_rank_20d ? `<br><small class="muted">20日第 ${q.sector.relative_rank_20d}/${q.sector.total} ${_esc(q.sector.rank_trend || '')}</small>` : ''}` : '<span class="muted">—</span>';
  let lvTd = '<span class="muted">…</span>';
  if (lv && !lv.error) {
    const stop = typeof _levelsPrimaryStop === 'function' ? _levelsPrimaryStop(lv) : lv.stop;
    lvTd = `<span style="color:#4ade80">撐 ${lv.support ? lv.support.price : '—'}</span><br><span style="color:#22c55e">損 ${stop && stop.price != null ? stop.price : '—'}</span> · <span style="color:#ef4444">標 ${lv.target ?? '—'}</span>`;
  } else if (lv && lv.error) lvTd = '<span class="muted">—</span>';
  return `<td>${q.close ?? '—'} ${_dcPct(q.change_pct, 2)}<br><small class="muted">${_dcDate(q.date)}</small></td>
    <td>${_dcPct(q.ret5)}<br>${_dcPct(q.ret20)}</td>
    <td>${_esc(q.ma_state || '—')}<br><small class="muted">${q.vol_ratio != null ? `量 ${q.vol_ratio} 倍` : ''}${q.from_high_pct != null ? ` · 離高 ${q.from_high_pct}%` : ''}</small></td>
    <td style="white-space:normal;min-width:90px">${strat}</td>
    <td>${q.kpct != null ? `${q.kpct}%` : '—'}${q.kpct_change != null ? `<br><small>${_dcPct(q.kpct_change, 2)}</small>` : ''}</td>
    <td style="white-space:normal;min-width:90px;font-size:.78rem">${sec}</td>
    <td style="font-size:.78rem">${lvTd}</td>`;
}
const _DC_MKT_TH = '<th>現價</th><th>5日<br>20日</th><th>均線</th><th>今天中的策略</th><th>千張大戶</th><th>產業（輪動排名）</th><th>撐／損／標</th>';

function _dcWlBtn(sid, name, note) {
  return wlRowBtn(sid, `dcAddWl('${_jsq(sid)}','${_jsq(name || '')}','${_jsq(note)}')`);
}
async function dcAddWl(sid, name, note) {
  try { await wlAddExternal(sid, name, note); } catch (e) { toast('加入失敗：' + e.message); }
  if (_dcView === 'result') _dcRenderResult(); else if (_dcView === 'tracker') _dcLoadTracker();
}

function _dcMentionStock(m) {
  const conf = _DC_CONF[m.confidence] || _DC_CONF.low;
  if (m.status === 'ignored') return '<span class="muted">不是股票</span>';
  const head = m.stock_id ? `${_dcStockCell(m.stock_id, m.name)} <span class="dc-conf" style="color:${conf[1]}">${conf[0]}</span>` : '<span style="color:var(--orange)">❓ 看不出來</span>';
  const why = m.reason ? `<div class="muted" style="font-size:.72rem;white-space:normal;max-width:260px">${_esc(m.reason)}</div>` : '';
  if (m.status === 'ok') return head + why;
  // 不確定：候選＋自己輸入，選了就記住
  const t = _jsq(m.text);
  const cands = (m.candidates || []).map(c => `<button class="btn sm ghost" style="padding:1px 7px" onclick="dcResolve('${t}','${_jsq(c.stock_id)}')">${_esc(c.stock_id)} ${_esc(c.name)}</button>`).join(' ');
  const self = m.stock_id ? `<button class="btn sm ghost" style="padding:1px 7px;color:#22c55e" onclick="dcResolve('${t}','${_jsq(m.stock_id)}')">✔ 是 ${_esc(m.stock_id)}</button>` : '';
  return `${head}${why}<div class="dc-fix">${self} ${cands}
    <input type="text" placeholder="代號或股名" style="width:96px;padding:2px 6px" onkeydown="if(event.key==='Enter')dcResolveInput(this,'${t}')">
    <button class="btn sm ghost" style="padding:1px 7px" onclick="dcResolveInput(this.previousElementSibling,'${t}')">設定</button>
    <button class="btn sm ghost" style="padding:1px 7px;color:var(--muted)" onclick="dcResolve('${t}','')">不是股票</button></div>`;
}

async function dcResolveInput(inp, text) {
  const q = inp.value.trim();
  if (!q) return;
  let sid = /^\d{4}$/.test(q) ? q : null;
  if (!sid) {
    try {
      const r = await api('GET', `/api/search?q=${encodeURIComponent(q)}`);
      const hit = (r || []).find(x => x.name === q) || (r || [])[0];
      if (hit) sid = hit.stock_id;
    } catch (e) {}
  }
  if (!sid) { toast(`找不到「${q}」`); return; }
  dcResolve(text, sid);
}

async function dcResolve(text, sid) {
  if (!_dcSession) return;
  try {
    _dcSession = await api('POST', `/api/discuss/session/${_dcSession.id}/resolve`, { text, stock_id: sid });
    toast(sid ? `記住了：「${text}」＝${sid}（下次自動對上）` : `「${text}」不是股票`);
    _dcRenderResult();
    _dcLoadMarket();
  } catch (e) { toast('設定失敗：' + e.message); }
}

function _dcLeaderFollower(r) {
  const lfs = r.leader_follower || [];
  if (!lfs.length) return '';
  const nm = sid => (_dcQuotes[sid] && _dcQuotes[sid].name) || sid;
  const avg = ids => { const v = ids.map(s => _dcQuotes[s] && _dcQuotes[s].ret20).filter(x => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const chip = sid => `<span class="dc-chip" style="cursor:pointer" onclick="openChart('${_jsq(sid)}')">${_esc(sid)} ${_esc(nm(sid))} ${_dcPct(_dcQuotes[sid] && _dcQuotes[sid].ret20)}</span>`;
  return `<div class="dc-sec"><h4>👑 大哥／小弟（20 日漲跌）</h4>${lfs.map(lf => {
    const a = avg(lf.leaders || []), b = avg(lf.followers || []);
    const gap = a != null && b != null ? a - b : null;
    return `<div class="dc-lf">
      <div><span class="dc-tag dc-lead">大哥</span> ${(lf.leaders || []).map(chip).join(' ') || '—'}</div>
      <div><span class="dc-tag dc-follow">小弟</span> ${(lf.followers || []).map(chip).join(' ') || '—'}</div>
      ${gap != null ? `<div style="font-size:.8rem">${gap > 0 ? `小弟落後大哥 <b style="color:var(--yellow)">${gap.toFixed(1)}%</b>（還沒跟上＝補漲空間？）` : `小弟已經比大哥多漲 ${(-gap).toFixed(1)}%`}</div>` : ''}
      ${lf.note ? `<div class="muted" style="font-size:.75rem">${_esc(lf.note)}</div>` : ''}</div>`;
  }).join('')}</div>`;
}

function _dcThemes(r) {
  const mentioned = new Set((r.mentions || []).map(m => m.stock_id).filter(Boolean));
  return (r.themes || []).map(t => `<div class="dc-sec"><h4>🧭 ${_esc(t.name)}</h4>
    ${t.why_now ? `<div style="font-size:.82rem;line-height:1.6;margin-bottom:8px">${_esc(t.why_now)}</div>` : ''}
    ${(t.chain || []).map(seg => `<div class="dc-seg"><div class="dc-seg-h">${_esc(seg.segment)}</div>
      <div class="dc-seg-b">${(seg.stocks || []).map(x => {
        const q = _dcQuotes[x.stock_id];
        return `<div class="dc-stock${mentioned.has(x.stock_id) ? ' dc-mentioned' : ''}" onclick="openChart('${_jsq(x.stock_id)}')" title="${_esc(x.note || '')}">
          <div><b>${_esc(x.stock_id)}</b> ${_esc(x.name)}${mentioned.has(x.stock_id) ? ' ⭐' : ''}</div>
          <div style="font-size:.74rem">${q ? `${q.close ?? ''} ${_dcPct(q.change_pct, 2)} · 20日 ${_dcPct(q.ret20)}` : ''}</div>
          ${x.note ? `<div class="muted" style="font-size:.7rem">${_esc(x.note)}</div>` : ''}</div>`;
      }).join('') || '<span class="muted">—</span>'}</div></div>`).join('')}</div>`).join('');
}

function _dcRenderResult() {
  const body = document.getElementById('dc-body');
  const s = _dcSession;
  if (!s) { body.innerHTML = '<div class="muted" style="padding:20px;text-align:center">貼上對話後按「🔍 分析」，或到「歷史紀錄」打開之前的分析</div>'; return; }
  const r = s.result || {};
  const ms = r.mentions || [];
  const roleOf = {};
  (s.stocks || []).forEach(x => roleOf[x.stock_id] = x);
  const views = (r.views || []).map(v => `<li><span style="color:${_DC_STANCE[v.stance] || 'var(--muted)'};font-weight:700">${_esc(v.stance || '')}</span> ${_esc(v.point)}</li>`).join('');
  const mentionRows = ms.map(m => {
    const st = roleOf[m.stock_id] || {};
    const since = st.price_at != null ? `${st.price_at}<br><small>${_dcPct(st.chg_since)}</small>` : '—';
    return `<tr><td>「${_esc(m.text)}」</td><td style="white-space:normal;min-width:150px">${_dcMentionStock(m)}</td>
      <td>${_DC_ROLE[st.role] || ''}</td><td>${since}</td>
      ${m.stock_id && m.status !== 'ignored' ? _dcMarketTds(m.stock_id) + `<td>${_dcWlBtn(m.stock_id, m.name, `戰略討論區 ${_dcDate(s.chat_date)}：${r.themes && r.themes[0] ? r.themes[0].name : ''}`)}</td>` : '<td colspan="8"></td>'}</tr>`;
  }).join('');
  const related = (r.related || []).map(x => `<tr><td>${_dcStockCell(x.stock_id, x.name)}</td>
      <td style="white-space:normal;min-width:180px;font-size:.76rem">${_esc(x.why || '')}</td>${_dcMarketTds(x.stock_id)}
      <td>${_dcWlBtn(x.stock_id, x.name, `戰略討論區同族群：${r.themes && r.themes[0] ? r.themes[0].name : ''}`)}</td></tr>`).join('');
  body.innerHTML = `
    <div class="dc-head">
      <div><b style="font-size:1rem">${_esc(s.title || '')}</b>
        <span class="muted" style="font-size:.78rem">對話 ${_esc(s.chat_date)} · ${_esc(s.model || '')} ·
        ${r.searched ? '🔎 有查最新網路消息' : '<span style="color:var(--orange)">⚠️ 沒查網路（AI 記憶，產業資訊可能過時）</span>'}</span></div>
      <button class="btn sm ghost" onclick="dcDelete(${s.id})" style="margin-left:auto">🗑 刪除</button>
    </div>
    ${r.summary ? `<div class="dc-sec"><div style="font-size:.9rem;line-height:1.6">${_esc(r.summary)}</div>${views ? `<ul class="dc-views">${views}</ul>` : ''}</div>` : ''}
    <div class="dc-sec"><h4>🎯 對話提到的股票</h4>
      ${ms.length ? `<div class="dc-table"><table><thead><tr><th>對話寫法</th><th>股票</th><th>角色</th><th>記錄價<br>到現在</th>${_DC_MKT_TH}<th></th></tr></thead><tbody>${mentionRows}</tbody></table></div>`
        : '<div class="muted">沒有找到股票</div>'}
      ${ms.some(m => m.status === 'unsure' || m.status === 'unknown') ? '<div style="font-size:.74rem;color:var(--orange);margin-top:4px">❓ 標「不確定」的：點候選或輸入代號，選過系統就記住這個暱稱</div>' : ''}
    </div>
    ${_dcLeaderFollower(r)}
    ${_dcThemes(r)}
    ${related ? `<div class="dc-sec"><h4>🔗 同族群（對話沒提到）</h4><div class="dc-table"><table><thead><tr><th>股票</th><th>為什麼</th>${_DC_MKT_TH}<th></th></tr></thead><tbody>${related}</tbody></table></div></div>` : ''}
    ${(r.checks || []).length ? `<div class="dc-sec"><h4>⚠️ 要自己查證</h4><ul class="dc-views">${r.checks.map(c => `<li>${_esc(c)}</li>`).join('')}</ul></div>` : ''}
    ${(r.dropped || []).length ? `<div class="muted" style="font-size:.74rem;margin:6px 0">AI 列了但代號對不上、已拿掉：${r.dropped.map(_esc).join('、')}</div>` : ''}
    ${(s.sources || []).length ? `<details class="dc-sec"><summary style="cursor:pointer">📰 搜尋來源（${s.sources.length}）${(r.queries || []).length ? `<span class="muted" style="font-size:.74rem"> 搜了：${r.queries.map(_esc).join('、')}</span>` : ''}</summary>
      <ul class="dc-views">${s.sources.map(x => `<li><a class="dc-link" href="${_esc(x.uri)}" target="_blank" rel="noopener">${_esc(x.title || x.uri)}</a></li>`).join('')}</ul></details>` : ''}
    <details class="dc-sec"><summary style="cursor:pointer">💬 對話原文</summary><pre class="dc-pre">${_esc(r.transcript || s.transcript || '')}</pre></details>
    <div class="dc-sec"><h4>📝 我的筆記</h4><textarea id="dc-note" rows="2" style="width:100%" placeholder="這次討論的想法、後續要追的…">${_esc(s.note || '')}</textarea>
      <button class="btn sm ghost" style="margin-top:4px" onclick="dcSaveNote()">儲存筆記</button></div>`;
}

async function dcSaveNote() {
  if (!_dcSession) return;
  const note = document.getElementById('dc-note').value;
  try { await api('PUT', `/api/discuss/session/${_dcSession.id}/note`, { note }); _dcSession.note = note; toast('筆記已存'); }
  catch (e) { toast('儲存失敗：' + e.message); }
}

async function dcDelete(id) {
  if (!confirm('刪除這次分析？（記住的暱稱不會刪）')) return;
  try { await api('DELETE', `/api/discuss/session/${id}`); } catch (e) { toast('刪除失敗：' + e.message); return; }
  if (_dcSession && _dcSession.id === id) _dcSession = null;
  dcSwitch('history');
}

// ── 歷史紀錄 ──
async function _dcLoadHistory(quiet) {
  const body = document.getElementById('dc-body');
  body.innerHTML = '<div class="muted" style="padding:20px;text-align:center">載入中...</div>';
  try {
    const { rows } = await api('GET', '/api/discuss/sessions');
    if (!rows.length) { body.innerHTML = '<div class="muted" style="padding:20px;text-align:center">還沒有分析紀錄。貼上跟老大哥的對話試試看。</div>'; return; }
    body.innerHTML = rows.map(r => {
      const ms = r.stocks.filter(x => x.kind === 'mentioned');
      return `<div class="dc-hist" onclick="dcOpen(${r.id})">
        <div><b>${_esc(r.title || '')}</b> <span class="muted" style="font-size:.76rem">對話 ${_esc(r.chat_date)}${r.image_count ? ` · 📷${r.image_count}` : ''}</span></div>
        <div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px">${ms.map(x => `<span class="dc-chip">${_DC_ROLE[x.role] || ''}${_esc(x.stock_id)} ${_esc(x.name || '')} ${_dcPct(x.chg_since)}</span>`).join('') || '<span class="muted" style="font-size:.76rem">沒有提到股票</span>'}</div>
        ${r.note ? `<div class="muted" style="font-size:.76rem;margin-top:3px">📝 ${_esc(r.note)}</div>` : ''}</div>`;
    }).join('');
  } catch (e) { body.innerHTML = `<div style="color:var(--red)">載入失敗：${_esc(e.message)}</div>`; }
}

// ── 他提過的股票表現 ──
async function _dcLoadTracker() {
  const body = document.getElementById('dc-body');
  body.innerHTML = '<div class="muted" style="padding:20px;text-align:center">載入中...</div>';
  try {
    const { rows } = await api('GET', '/api/discuss/tracker');
    if (!rows.length) { body.innerHTML = '<div class="muted" style="padding:20px;text-align:center">還沒有紀錄</div>'; return; }
    const v = rows.map(x => x.chg).filter(x => x != null);
    const up = v.filter(x => x > 0).length, avg = v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
    body.innerHTML = `<div style="font-size:.85rem;margin-bottom:8px">對話提到的 ${rows.length} 檔，從第一次提到到現在：
        平均 ${_dcPct(avg)}，上漲 ${up}／${v.length} 檔${v.length ? `（${Math.round(up / v.length * 100)}%）` : ''}</div>
      <div class="dc-table"><table><thead><tr><th>股票</th><th>角色</th><th>第一次提到</th><th>記錄價</th><th>現價</th><th>漲跌</th><th>提到次數</th><th>最近提到</th><th></th></tr></thead><tbody>
      ${rows.map(x => `<tr><td>${_dcStockCell(x.stock_id, x.name)}</td><td>${x.roles.map(k => _DC_ROLE[k] || '').join('')}</td>
        <td>${_esc(x.first_date)}</td><td>${x.first_price ?? '—'}</td><td>${x.price_now ?? '—'}<br><small class="muted">${_dcDate(x.now_date)}</small></td>
        <td>${_dcPct(x.chg)}</td><td>${x.times}</td>
        <td><a class="dc-link" href="javascript:void(0)" onclick="dcOpen(${x.sessions[x.sessions.length - 1]})">${_esc(x.last_date)}</a></td>
        <td>${_dcWlBtn(x.stock_id, x.name, `戰略討論區：${x.first_date} 提到`)}</td></tr>`).join('')}
      </tbody></table></div>`;
  } catch (e) { body.innerHTML = `<div style="color:var(--red)">載入失敗：${_esc(e.message)}</div>`; }
}

// ── 暱稱對照 ──
async function _dcLoadAlias() {
  const body = document.getElementById('dc-body');
  try {
    const { rows } = await api('GET', '/api/discuss/aliases');
    body.innerHTML = `<div style="font-size:.8rem;color:var(--muted);margin-bottom:8px">在結果裡確認過「對話寫法＝哪一檔」就會記在這裡，下次 AI 分析直接照這個對應。</div>
      ${rows.length ? `<div class="dc-table"><table><thead><tr><th>對話寫法</th><th>股票</th><th></th></tr></thead><tbody>
      ${rows.map(a => `<tr><td>「${_esc(a.alias)}」</td><td>${_dcStockCell(a.stock_id, a.name)}</td>
        <td><button class="btn sm ghost" onclick="dcDelAlias('${_jsq(a.alias)}')">刪除</button></td></tr>`).join('')}
      </tbody></table></div>` : '<div class="muted">還沒有</div>'}`;
  } catch (e) { body.innerHTML = `<div style="color:var(--red)">載入失敗：${_esc(e.message)}</div>`; }
}
async function dcDelAlias(alias) {
  try { await api('DELETE', `/api/discuss/alias?alias=${encodeURIComponent(alias)}`); _dcLoadAlias(); } catch (e) { toast('刪除失敗：' + e.message); }
}
