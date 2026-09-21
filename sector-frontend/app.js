/**
 * app.js — 台股產業輪動引擎 V1 前端
 */

const BASE = "";  // 同源

// ── 狀態 ────────────────────────────────────────────────────────────────────
let _sectors = [];       // 當前表格資料
let _sortKey = "relative_rank_5d";
let _sortAsc = true;
let _currentTab = "rank";  // rank | change | event | events-list
let _statusTimer = null;

// ── localStorage 快取 ───────────────────────────────────────────────────────

const _LS_KEY = "sector_cache_v1";

function _saveCache(sectors, date) {
  try {
    localStorage.setItem(_LS_KEY, JSON.stringify({ sectors, date, saved: Date.now() }));
  } catch (e) {}
}

function _loadCache() {
  try {
    const raw = localStorage.getItem(_LS_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    // 快取超過 24 小時視為過期
    if (Date.now() - (obj.saved || 0) > 86400000) return null;
    return obj;
  } catch (e) { return null; }
}

// ── 初始化 ──────────────────────────────────────────────────────────────────

async function init() {
  // 先顯示 localStorage 快取（讓頁面重整後立刻有資料）
  const cache = _loadCache();
  if (cache && cache.sectors && cache.sectors.length > 0) {
    _sectors = cache.sectors;
    renderTable(_sectors);
    showLoading(false);
    // 在 header 顯示快取說明
    const dateBadge = document.getElementById("stat-date");
    if (dateBadge && cache.date) dateBadge.textContent = cache.date + "（快取）";
  }
  await loadStatus();
  await loadSectors(_currentTab);
  // 每 30s 自動刷狀態
  _statusTimer = setInterval(loadStatus, 30000);
}

// ── 狀態列 ──────────────────────────────────────────────────────────────────

async function loadStatus() {
  try {
    const r = await fetch(`${BASE}/sector/api/status`);
    const d = await r.json();

    document.getElementById("stat-sectors").textContent = d.sector_count ?? "—";
    document.getElementById("stat-stocks").textContent = d.stock_count ?? "—";
    document.getElementById("stat-date").textContent = formatDate(d.latest_date) || "尚無資料";

    const dot = document.getElementById("status-dot");
    const runTxt = document.getElementById("engine-running-txt");
    if (d.engine_running) {
      dot.className = "status-dot running";
      runTxt.style.display = "";
    } else {
      dot.className = d.initialized ? "status-dot ok" : "status-dot";
      runTxt.style.display = "none";
    }

    // 若未初始化，顯示提示
    if (!d.initialized) {
      showEmpty("尚未初始化", "請點擊右上角「初始化」按鈕，從 FinMind 建立產業對照表");
    }
  } catch (e) {
    console.error("loadStatus:", e);
  }
}

// ── 排序 Tab ────────────────────────────────────────────────────────────────

function switchSortTab(tab, el) {
  _currentTab = tab;
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  el.classList.add("active");

  if (tab === "events-list") {
    document.getElementById("sectors-panel").style.display = "none";
    document.getElementById("detail-panel").style.display = "none";
    document.getElementById("events-panel").style.display = "";
    document.getElementById("bubble-panel").style.display = "none";
    loadEvents();
  } else if (tab === "bubble") {
    document.getElementById("sectors-panel").style.display = "none";
    document.getElementById("detail-panel").style.display = "none";
    document.getElementById("events-panel").style.display = "none";
    document.getElementById("bubble-panel").style.display = "";
    renderBubbleChart(_sectors.length > 0 ? _sectors : null);
  } else {
    document.getElementById("events-panel").style.display = "none";
    document.getElementById("detail-panel").style.display = "none";
    document.getElementById("sectors-panel").style.display = "";
    document.getElementById("bubble-panel").style.display = "none";
    loadSectors(tab);
  }
}

// ── 載入產業列表 ─────────────────────────────────────────────────────────────

async function loadSectors(tab) {
  const sortByMap = {
    rank: "rank5d",
    change: "rank_change",
    event: "event",
  };
  const sortBy = sortByMap[tab] || "rank5d";

  showLoading(true);
  try {
    const r = await fetch(`${BASE}/sector/api/sectors?sort_by=${sortBy}`);
    const d = await r.json();
    const fresh = d.sectors || [];
    if (fresh.length > 0) {
      _sectors = fresh;
      renderTable(_sectors);
      _saveCache(fresh, d.date);  // 成功時存快取
    } else if (_sectors.length === 0) {
      // API 空且沒有快取 → 顯示「無資料」
      renderTable([]);
    }
    // 若 API 空但有快取，保留快取畫面不清除
  } catch (e) {
    showToast("載入失敗：" + e.message, "err");
  } finally {
    showLoading(false);
  }
}

// ── 表格渲染 ─────────────────────────────────────────────────────────────────

function renderTable(sectors) {
  if (!sectors || sectors.length === 0) {
    showEmpty("尚無資料", "請先初始化並執行計算");
    return;
  }

  document.getElementById("sectors-panel").style.display = "";
  document.getElementById("loading-indicator").style.display = "none";

  const tbody = document.getElementById("sectors-tbody");
  tbody.innerHTML = "";

  sectors.forEach((s, i) => {
    const tr = document.createElement("tr");
    tr.id = `row-${i}`;
    tr.innerHTML = buildSectorRow(s, i);
    tbody.appendChild(tr);

    // 展開列（預設隱藏）
    const expandTr = document.createElement("tr");
    expandTr.id = `expand-${i}`;
    expandTr.className = "expand-row";
    expandTr.style.display = "none";
    expandTr.innerHTML = `<td colspan="12"><div class="expand-inner" id="expand-inner-${i}"></div></td>`;
    tbody.appendChild(expandTr);
  });
}

function buildSectorRow(s, i) {
  const name = s.sector_name || s.sector_id;
  const trend = s.trend_state || "—";
  const trendBadge = trendBadgeHtml(trend);

  const rank5 = rankHtml(s.relative_rank_5d, _sectors.length);
  const rank20 = rankHtml(s.relative_rank_20d, _sectors.length);
  const rank60 = rankHtml(s.relative_rank_60d, _sectors.length);

  const rankTrend = rankTrendHtml(s.rank_trend, s.rank_change_5d);
  const ret5 = retHtml(s.return_ew_5d);
  const ret20 = retHtml(s.return_ew_20d);

  const evBadge = s.structure_event ? eventBadgeHtml(s.structure_event) : '<span style="color:var(--muted)">—</span>';
  const healthBadge = healthBadgeHtml(s.internal_health);
  const regimeBadge = s.sector_regime
    ? `<span class="regime-chip regime-${s.sector_regime}">${s.sector_regime}</span>`
    : '<span style="color:var(--muted)">—</span>';

  return `
    <td style="font-weight:600;cursor:pointer" onclick="toggleDetail(${i}, '${escHtml(s.sector_id)}')">${name}</td>
    <td>${trendBadge}</td>
    <td>${rank5}</td>
    <td>${rank20}</td>
    <td>${rank60}</td>
    <td>${rankTrend}</td>
    <td>${ret5}</td>
    <td>${ret20}</td>
    <td>${evBadge}</td>
    <td>${healthBadge}</td>
    <td>${regimeBadge}</td>
    <td><button class="btn" style="padding:3px 8px;font-size:.75rem" onclick="openDetail('${escHtml(s.sector_id)}')">詳細</button></td>
  `;
}

// ── 行內展開 ────────────────────────────────────────────────────────────────

async function toggleDetail(i, sectorId) {
  const expandTr = document.getElementById(`expand-${i}`);
  const mainTr = document.getElementById(`row-${i}`);
  if (expandTr.style.display === "none") {
    expandTr.style.display = "";
    mainTr.classList.add("expanded");
    const inner = document.getElementById(`expand-inner-${i}`);
    inner.innerHTML = '<div class="loading"><div class="spinner"></div> 載入中...</div>';
    try {
      const r = await fetch(`${BASE}/sector/api/sector/${encodeURIComponent(sectorId)}?days=30`);
      const d = await r.json();
      inner.innerHTML = buildExpandContent(d.latest, d.stocks);
    } catch (e) {
      inner.innerHTML = '<span style="color:var(--red)">載入失敗</span>';
    }
  } else {
    expandTr.style.display = "none";
    mainTr.classList.remove("expanded");
  }
}

function buildExpandContent(latest, stocks) {
  if (!latest) return "無資料";

  const items = [
    ["指數水位", latest.index_level?.toFixed(2)],
    ["MA20", latest.ma20?.toFixed(2)],
    ["MA60", latest.ma60?.toFixed(2)],
    ["MA120", latest.ma120?.toFixed(2)],
    ["MA60 斜率", latest.ma60_slope !== null ? (latest.ma60_slope * 100).toFixed(3) + "%" : "—"],
    ["1D 報酬", pctFmt(latest.return_ew_1d)],
    ["5D 報酬", pctFmt(latest.return_ew_5d)],
    ["20D 報酬", pctFmt(latest.return_ew_20d)],
    ["60D 報酬", pctFmt(latest.return_ew_60d)],
    ["中位數 1D", pctFmt(latest.return_median_1d)],
    ["漲跌比", latest.breadth_up_ratio !== null ? (latest.breadth_up_ratio * 100).toFixed(1) + "%" : "—"],
    ["站上MA20", latest.above_ma20_ratio !== null ? (latest.above_ma20_ratio * 100).toFixed(1) + "%" : "—"],
    ["站上MA60", latest.above_ma60_ratio !== null ? (latest.above_ma60_ratio * 100).toFixed(1) + "%" : "—"],
    ["量能偏多比", latest.up_volume_ratio !== null ? (latest.up_volume_ratio * 100).toFixed(1) + "%" : "—"],
    ["Top3 貢獻", latest.top3_contribution !== null ? (latest.top3_contribution * 100).toFixed(1) + "%" : "—"],
    ["Swing High", latest.swing_high?.toFixed(2) + (latest.swing_high_date ? ` (${formatDate(latest.swing_high_date)})` : "") || "—"],
    ["Swing Low",  latest.swing_low?.toFixed(2)  + (latest.swing_low_date  ? ` (${formatDate(latest.swing_low_date)})` : "")  || "—"],
    ["市場相對 5D", latest.market_relative_5d !== null ? pctFmt(latest.market_relative_5d) : "—"],
    ["轉換狀態", latest.transition_state || "None"],
    ["股票數", latest.stock_count],
  ];

  const gridItems = items.map(([label, val]) =>
    `<div class="detail-item"><span class="detail-label">${label}</span><span class="detail-value">${val ?? "—"}</span></div>`
  ).join("");

  const stockList = (stocks || []).slice(0, 20).join("、");
  const moreStocks = (stocks || []).length > 20 ? ` 等 ${(stocks || []).length} 支` : "";

  return `
    <div class="expand-section">
      <h4>詳細指標</h4>
      <div class="detail-grid">${gridItems}</div>
    </div>
    <div class="expand-section" style="flex:1;min-width:200px">
      <h4>成份股（${(stocks || []).length} 支）</h4>
      <div style="color:var(--muted);font-size:.78rem;line-height:1.7">${stockList}${moreStocks}</div>
    </div>
  `;
}

// ── 產業詳細頁 ────────────────────────────────────────────────────────────────

async function openDetail(sectorId) {
  document.getElementById("sectors-panel").style.display = "none";
  document.getElementById("events-panel").style.display = "none";
  const detailPanel = document.getElementById("detail-panel");
  detailPanel.style.display = "";
  document.getElementById("detail-content").innerHTML = '<div class="loading"><div class="spinner"></div> 載入中...</div>';

  try {
    const r = await fetch(`${BASE}/sector/api/sector/${encodeURIComponent(sectorId)}?days=60`);
    const d = await r.json();
    renderDetailPage(d);
  } catch (e) {
    document.getElementById("detail-content").innerHTML = `<div style="color:var(--red)">載入失敗：${e.message}</div>`;
  }
}

function renderDetailPage(d) {
  const s = d.latest || {};
  const name = s.sector_name || s.sector_id || d.sector_id || '';

  const metrics = [
    { label: "趨勢狀態", value: trendBadgeHtml(s.trend_state) },
    { label: "5D 排名", value: rankHtml(s.relative_rank_5d, null) },
    { label: "20D 排名", value: rankHtml(s.relative_rank_20d, null) },
    { label: "排名趨勢", value: rankTrendHtml(s.rank_trend, s.rank_change_5d) },
    { label: "5D 報酬", value: `<span class="${retClass(s.return_ew_5d)}">${pctFmt(s.return_ew_5d)}</span>` },
    { label: "20D 報酬", value: `<span class="${retClass(s.return_ew_20d)}">${pctFmt(s.return_ew_20d)}</span>` },
    { label: "60D 報酬", value: `<span class="${retClass(s.return_ew_60d)}">${pctFmt(s.return_ew_60d)}</span>` },
    { label: "指數水位", value: s.index_level?.toFixed(2) ?? "—" },
    { label: "健康度", value: healthBadgeHtml(s.internal_health) },
    { label: "漲跌比", value: s.breadth_up_ratio !== null && s.breadth_up_ratio !== undefined ? `<div class="health-bar-wrap"><div class="health-bar"><div class="health-bar-fill" style="width:${(s.breadth_up_ratio*100).toFixed(0)}%;background:${s.breadth_up_ratio>=0.5?'var(--green)':'var(--red)'}"></div></div>${(s.breadth_up_ratio*100).toFixed(1)}%</div>` : "—" },
    { label: "站上MA20", value: s.above_ma20_ratio !== null && s.above_ma20_ratio !== undefined ? `${(s.above_ma20_ratio*100).toFixed(1)}%` : "—" },
    { label: "結構事件", value: s.structure_event ? eventBadgeHtml(s.structure_event) : "—" },
  ];

  const metricCards = metrics.map(m =>
    `<div class="metric-card"><div class="metric-label">${m.label}</div><div class="metric-value">${m.value}</div></div>`
  ).join("");

  // 歷史事件
  const events = (d.events || []).map(ev =>
    `<div class="event-card">
      <span class="event-date">${formatDate(ev.observation_date)}</span>
      ${eventBadgeHtml(ev.event_type)}
      <span class="event-detail">參考價 ${ev.reference_price?.toFixed(2) ?? "—"} | 事件價 ${ev.event_price?.toFixed(2) ?? "—"}</span>
      <span style="color:var(--muted);font-size:.75rem">${ev.confirmation_status}</span>
    </div>`
  ).join("") || '<div style="color:var(--muted);font-size:.85rem">無近期事件</div>';

  // 歷史資料表格
  const historyRows = (d.history || []).slice(-20).reverse().map(h =>
    `<tr>
      <td>${formatDate(h.observation_date)}</td>
      <td>${h.index_level?.toFixed(2) ?? "—"}</td>
      <td class="${retClass(h.return_ew_1d)}">${pctFmt(h.return_ew_1d)}</td>
      <td class="${retClass(h.return_ew_5d)}">${pctFmt(h.return_ew_5d)}</td>
      <td>${h.ma20?.toFixed(2) ?? "—"}</td>
      <td>${h.ma60?.toFixed(2) ?? "—"}</td>
      <td>${trendBadgeHtml(h.trend_state)}</td>
      <td>${h.relative_rank_5d ?? "—"}</td>
    </tr>`
  ).join("");

  document.getElementById("detail-content").innerHTML = `
    <div class="detail-header">
      <h2>${name}</h2>
      <div class="meta">觀察日：${formatDate(s.observation_date)} | 股票數：${s.stock_count ?? "—"} | ${s.sector_regime ? `<span class="regime-chip regime-${s.sector_regime}">${s.sector_regime}</span>` : ""}</div>
    </div>

    <div class="metrics-grid">${metricCards}</div>

    <div style="margin-bottom:20px">
      <h4 style="color:var(--muted);margin-bottom:10px;font-size:.85rem">近期結構事件</h4>
      <div class="event-list">${events}</div>
    </div>

    <div>
      <h4 style="color:var(--muted);margin-bottom:10px;font-size:.85rem">歷史資料（最近 20 天）</h4>
      <div class="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>日期</th><th>指數</th><th>1D%</th><th>5D%</th>
              <th>MA20</th><th>MA60</th><th>趨勢</th><th>5D#</th>
            </tr>
          </thead>
          <tbody>${historyRows}</tbody>
        </table>
      </div>
    </div>

    <div style="margin-top:20px">
      <h4 style="color:var(--muted);margin-bottom:10px;font-size:.85rem">成份股（${(d.stocks||[]).length} 支）</h4>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        ${(d.stocks||[]).map(sid => `<span style="display:inline-block;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:3px 8px;font-size:.8rem;color:var(--accent);font-weight:600">${sid}</span>`).join('')}
      </div>
    </div>
  `;
}

function backToList() {
  document.getElementById("detail-panel").style.display = "none";
  if (_currentTab === "events-list") {
    document.getElementById("events-panel").style.display = "";
  } else {
    document.getElementById("sectors-panel").style.display = "";
  }
}

// ── 事件記錄 ────────────────────────────────────────────────────────────────

async function loadEvents() {
  const container = document.getElementById("events-list-container");
  container.innerHTML = '<div class="loading"><div class="spinner"></div> 載入中...</div>';
  try {
    const r = await fetch(`${BASE}/sector/api/events?limit=50`);
    const d = await r.json();
    const events = d.events || [];
    if (events.length === 0) {
      container.innerHTML = '<div class="empty-state"><h3>尚無事件記錄</h3><p>請先執行計算</p></div>';
      return;
    }
    container.innerHTML = events.map(ev =>
      `<div class="event-card">
        <span class="event-date">${formatDate(ev.observation_date)}</span>
        <span class="event-sector">${ev.sector_name || ev.sector_id}</span>
        ${eventBadgeHtml(ev.event_type)}
        <span class="event-detail">參考價 <b>${ev.reference_price?.toFixed(2) ?? "—"}</b> | 事件價 <b>${ev.event_price?.toFixed(2) ?? "—"}</b></span>
        <span style="color:var(--muted);font-size:.75rem">${ev.confirmation_status}</span>
      </div>`
    ).join("");
  } catch (e) {
    container.innerHTML = `<div style="color:var(--red)">載入失敗：${e.message}</div>`;
  }
}

// ── 排序 ────────────────────────────────────────────────────────────────────

let _lastSortKey = null;
let _lastSortAsc = true;

function sortTable(key) {
  if (_lastSortKey === key) {
    _lastSortAsc = !_lastSortAsc;
  } else {
    _lastSortKey = key;
    _lastSortAsc = key.startsWith("return") ? false : true;
  }

  const sorted = [..._sectors].sort((a, b) => {
    let va = a[key], vb = b[key];
    if (va === null || va === undefined) return 1;
    if (vb === null || vb === undefined) return -1;
    if (typeof va === "number") return _lastSortAsc ? va - vb : vb - va;
    return _lastSortAsc
      ? String(va).localeCompare(String(vb))
      : String(vb).localeCompare(String(va));
  });

  // 更新表頭箭頭
  document.querySelectorAll("th").forEach(th => th.classList.remove("sorted"));
  renderTable(sorted);
}

// ── Actions ──────────────────────────────────────────────────────────────────

async function triggerSmartRefresh() {
  const btn = document.getElementById("btn-smart-refresh");
  btn.disabled = true;

  try {
    // 先查狀態
    const st = await fetch(`${BASE}/sector/api/status`).then(r => r.json()).catch(() => null);

    if (!st || !st.initialized) {
      // 未初始化：先 init 再等待，然後 refresh
      btn.textContent = "初始化中...";
      showToast("尚未初始化，開始從 FinMind 建立產業對照表...", "ok");
      await fetch(`${BASE}/sector/api/init`, { method: "POST" });

      // 輪詢等待初始化完成（最多 5 分鐘）
      let waited = 0;
      await new Promise(resolve => {
        const poll = setInterval(async () => {
          waited += 10;
          const s = await fetch(`${BASE}/sector/api/status`).then(r => r.json()).catch(() => null);
          if ((s && s.initialized) || waited > 300) {
            clearInterval(poll);
            resolve();
          }
        }, 10000);
      });
    }

    // 執行更新計算
    btn.textContent = "計算中...";
    const r = await fetch(`${BASE}/sector/api/refresh?days_back=120`, { method: "POST" });
    const d = await r.json();
    if (d.ok) {
      showToast("引擎已開始計算（約需 3~10 分鐘）", "ok");
      const poll = setInterval(async () => {
        const s = await fetch(`${BASE}/sector/api/status`).then(r => r.json()).catch(() => null);
        if (s && !s.engine_running) {
          clearInterval(poll);
          btn.disabled = false;
          btn.textContent = "🔄 初始化/更新";
          await loadStatus();
          await loadSectors(_currentTab);
          showToast("更新完成！", "ok");
        }
      }, 10000);
    } else {
      showToast(d.message || "啟動失敗", "err");
      btn.disabled = false;
      btn.textContent = "🔄 初始化/更新";
    }
  } catch (e) {
    showToast("請求失敗：" + e.message, "err");
    btn.disabled = false;
    btn.textContent = "🔄 初始化/更新";
  }
}

// 保留舊名稱相容
async function triggerRefresh() { return triggerSmartRefresh(); }
async function triggerInit()    { return triggerSmartRefresh(); }

// ── UI helpers ────────────────────────────────────────────────────────────────

function trendBadgeHtml(trend) {
  const map = { BULL: ["badge-bull", "多頭"], BEAR: ["badge-bear", "空頭"], RANGE: ["badge-range", "盤整"] };
  const [cls, label] = map[trend] || ["badge-stable", trend || "—"];
  return `<span class="badge ${cls}">${label}</span>`;
}

function rankHtml(rank, total) {
  if (rank === null || rank === undefined) return '<span style="color:var(--muted)">—</span>';
  let cls = "rank-num";
  if (total && rank <= Math.ceil(total * 0.15)) cls += " rank-top3";
  else if (total && rank >= Math.ceil(total * 0.85)) cls += " rank-bot3";
  return `<span class="${cls}">${rank}</span>`;
}

function rankTrendHtml(trend, change) {
  const changeStr = change !== null && change !== undefined
    ? ` (${change > 0 ? "+" : ""}${change})`
    : "";
  if (trend === "STRENGTHENING") return `<span class="badge badge-strong arrow-up">↑↑ 強化${changeStr}</span>`;
  if (trend === "WEAKENING")     return `<span class="badge badge-weak arrow-down">↓↓ 弱化${changeStr}</span>`;
  return `<span class="badge badge-stable">→ 穩定${changeStr}</span>`;
}

function eventBadgeHtml(event) {
  const labels = {
    BREAKOUT:        "突破",
    BREAKDOWN:       "跌破",
    FALSE_BREAKDOWN: "假跌破",
    FALSE_BREAKOUT:  "假突破",
    RECLAIM:         "收復",
  };
  const label = labels[event] || event;
  return `<span class="badge-event badge-event-${event}">${label}</span>`;
}

function healthBadgeHtml(health) {
  const map = {
    HEALTHY:      ["badge-strong", "健康"],
    CONCENTRATED: ["badge-range",  "集中"],
    WEAK:         ["badge-weak",   "弱勢"],
    IMPROVING:    ["badge-strong", "改善"],
    DETERIORATING:["badge-weak",  "惡化"],
    STABLE:       ["badge-stable", "穩定"],
  };
  const [cls, label] = map[health] || ["badge-stable", health || "—"];
  return `<span class="badge ${cls}">${label}</span>`;
}

function retClass(val) {
  if (val === null || val === undefined) return "ret-neu";
  return val > 0 ? "ret-pos" : val < 0 ? "ret-neg" : "ret-neu";
}

function retHtml(val) {
  if (val === null || val === undefined) return '<span class="ret-neu">—</span>';
  const pct = (val * 100).toFixed(2);
  const sign = val > 0 ? "+" : "";
  return `<span class="${retClass(val)}">${sign}${pct}%</span>`;
}

function pctFmt(val) {
  if (val === null || val === undefined) return "—";
  const pct = (val * 100).toFixed(2);
  const sign = val > 0 ? "+" : "";
  return `${sign}${pct}%`;
}

function formatDate(d) {
  if (!d) return "—";
  const s = String(d);
  if (s.length === 8) return `${s.slice(0, 4)}/${s.slice(4, 6)}/${s.slice(6, 8)}`;
  if (s.includes("T")) return s.slice(0, 10);
  return s;
}

function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[c]));
}

function showLoading(show) {
  const el = document.getElementById("loading-indicator");
  if (show) {
    el.style.display = "";
    document.getElementById("sectors-panel").style.display = "none";
  } else {
    el.style.display = "none";
    document.getElementById("sectors-panel").style.display = "";
  }
}

function showEmpty(title, msg) {
  document.getElementById("loading-indicator").style.display = "none";
  document.getElementById("sectors-panel").style.display = "";
  document.getElementById("sectors-tbody").innerHTML =
    `<tr><td colspan="12">
      <div class="empty-state">
        <h3>${title}</h3>
        <p style="margin-top:6px;font-size:.85rem">${msg}</p>
      </div>
    </td></tr>`;
}

function showToast(msg, type = "ok") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = `toast show ${type}`;
  setTimeout(() => { t.className = "toast"; }, 3000);
}

// ── 泡泡圖 ───────────────────────────────────────────────────────────────────

async function renderBubbleChart(sectors) {
  const container = document.getElementById("bubbleSection");

  // 若無資料，嘗試載入
  if (!sectors || sectors.length === 0) {
    container.innerHTML = '<div class="loading"><div class="spinner"></div> 載入中...</div>';
    try {
      const r = await fetch(`${BASE}/sector/api/sectors?sort_by=rank5d`);
      const d = await r.json();
      sectors = d.sectors || [];
    } catch (e) {
      container.innerHTML = `<div style="color:var(--red);padding:20px">載入失敗：${e.message}</div>`;
      return;
    }
  }

  if (!sectors || sectors.length === 0) {
    container.innerHTML = '<div class="empty-state"><h3>尚無資料</h3><p>請先初始化並執行計算</p></div>';
    return;
  }

  // SVG 尺寸與邊距
  const W = 700, H = 500;
  const margin = { top: 40, right: 40, bottom: 50, left: 60 };
  const pw = W - margin.left - margin.right;
  const ph = H - margin.top - margin.bottom;

  // 取出有效資料
  const pts = sectors.filter(s =>
    s.return_ew_5d != null && s.return_ew_20d != null
  );

  // 座標範圍
  const x20 = pts.map(s => s.return_ew_20d * 100);
  const y5  = pts.map(s => s.return_ew_5d  * 100);
  const xMin = Math.min(...x20), xMax = Math.max(...x20);
  const yMin = Math.min(...y5),  yMax = Math.max(...y5);
  const xPad = (xMax - xMin) * 0.15 || 2;
  const yPad = (yMax - yMin) * 0.15 || 2;
  const xL = xMin - xPad, xR = xMax + xPad;
  const yB = yMin - yPad, yT = yMax + yPad;

  const toSvgX = v => margin.left + ((v - xL) / (xR - xL)) * pw;
  const toSvgY = v => margin.top  + ((yT - v) / (yT - yB)) * ph;
  const x0 = toSvgX(0), y0 = toSvgY(0);

  // 氣泡半徑
  const maxCount = Math.max(...pts.map(s => s.stock_count || 1));
  const bubbleR = s => {
    const cnt = s.stock_count || 1;
    return 6 + (cnt / maxCount) * 14;
  };

  // 顏色
  const bubbleColor = s => {
    const x = s.return_ew_20d, y = s.return_ew_5d;
    if (y >= 0 && x >= 0) return "#f85149";
    if (y >= 0 && x <  0) return "#d29922";
    if (y <  0 && x >= 0) return "#388bfd";
    return "#8b949e";
  };

  // 建立 SVG
  let svgParts = [];

  // 象限背景
  const qBg = [
    { x: x0, y: margin.top, w: margin.left + pw - x0, h: y0 - margin.top, color: "rgba(248,81,73,.05)" },   // 右上
    { x: margin.left, y: margin.top, w: x0 - margin.left, h: y0 - margin.top, color: "rgba(210,153,34,.05)" }, // 左上
    { x: margin.left, y: y0, w: x0 - margin.left, h: margin.top + ph - y0, color: "rgba(139,148,158,.04)" },   // 左下
    { x: x0, y: y0, w: margin.left + pw - x0, h: margin.top + ph - y0, color: "rgba(56,139,253,.05)" },       // 右下
  ];
  qBg.forEach(q => {
    svgParts.push(`<rect x="${q.x}" y="${q.y}" width="${Math.max(0,q.w)}" height="${Math.max(0,q.h)}" fill="${q.color}"/>`);
  });

  // 零線
  svgParts.push(`<line x1="${x0}" y1="${margin.top}" x2="${x0}" y2="${margin.top+ph}" class="bubble-zero-line"/>`);
  svgParts.push(`<line x1="${margin.left}" y1="${y0}" x2="${margin.left+pw}" y2="${y0}" class="bubble-zero-line"/>`);

  // 象限標籤
  const qlPad = 8;
  const quadLabels = [
    { text: "領漲・中短期皆強",   x: margin.left + pw - qlPad, y: margin.top + qlPad, anchor: "end" },
    { text: "轉強・短強中弱",     x: margin.left + qlPad,      y: margin.top + qlPad, anchor: "start" },
    { text: "領跌・中短期皆弱",   x: margin.left + qlPad,      y: margin.top + ph - qlPad, anchor: "start" },
    { text: "落後・中強短弱",     x: margin.left + pw - qlPad, y: margin.top + ph - qlPad, anchor: "end" },
  ];
  quadLabels.forEach(q => {
    svgParts.push(`<text x="${q.x}" y="${q.y}" text-anchor="${q.anchor}" class="bubble-quadrant-label">${q.text}</text>`);
  });

  // 軸刻度（簡單 4 格）
  const xTicks = 5, yTicks = 5;
  for (let i = 0; i <= xTicks; i++) {
    const v = xL + (i / xTicks) * (xR - xL);
    const sx = toSvgX(v);
    svgParts.push(`<line x1="${sx}" y1="${margin.top+ph}" x2="${sx}" y2="${margin.top+ph+4}" stroke="var(--border)" stroke-width="1"/>`);
    svgParts.push(`<text x="${sx}" y="${margin.top+ph+16}" text-anchor="middle" class="bubble-axis-label">${v.toFixed(1)}%</text>`);
  }
  for (let i = 0; i <= yTicks; i++) {
    const v = yB + (i / yTicks) * (yT - yB);
    const sy = toSvgY(v);
    svgParts.push(`<line x1="${margin.left-4}" y1="${sy}" x2="${margin.left}" y2="${sy}" stroke="var(--border)" stroke-width="1"/>`);
    svgParts.push(`<text x="${margin.left-8}" y="${sy+4}" text-anchor="end" class="bubble-axis-label">${v.toFixed(1)}%</text>`);
  }

  // 軸標籤
  svgParts.push(`<text x="${margin.left+pw/2}" y="${H-6}" text-anchor="middle" class="bubble-axis-label" fill="var(--muted)">中期動能 (20日%)</text>`);
  svgParts.push(`<text x="12" y="${margin.top+ph/2}" text-anchor="middle" transform="rotate(-90,12,${margin.top+ph/2})" class="bubble-axis-label" fill="var(--muted)">短期趨勢 (5日%)</text>`);

  // 泡泡
  pts.forEach((s, idx) => {
    const cx = toSvgX(s.return_ew_20d * 100);
    const cy = toSvgY(s.return_ew_5d  * 100);
    const r  = bubbleR(s);
    const col = bubbleColor(s);
    const name = escHtml(s.sector_name || s.sector_id);
    svgParts.push(`
      <g class="bubble-node" onclick="onBubbleClick('${escHtml(s.sector_id)}','${name}')">
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="${col}" fill-opacity="0.75" stroke="${col}" stroke-width="1.5"/>
        <text x="${cx}" y="${cy}" class="bubble-node-label" style="font-size:${Math.max(8, r*0.65)}px">${name.length > 5 ? name.slice(0,4)+'…' : name}</text>
      </g>`);
  });

  // 邊框
  svgParts.push(`<rect x="${margin.left}" y="${margin.top}" width="${pw}" height="${ph}" fill="none" stroke="var(--border)" stroke-width="1"/>`);

  const svgHtml = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${svgParts.join("")}</svg>`;

  container.innerHTML = `
    <div class="bubble-wrap">
      <div class="bubble-svg-wrap">${svgHtml}</div>
      <div class="bubble-side-panel" id="bubble-side-panel">
        <div class="bubble-side-title" id="bubble-side-title">—</div>
        <div class="bubble-side-metrics" id="bubble-side-metrics"></div>
        <div class="bubble-side-stocks" id="bubble-side-stocks"></div>
      </div>
    </div>`;
}

async function onBubbleClick(sectorId, name) {
  const panel = document.getElementById("bubble-side-panel");
  const titleEl = document.getElementById("bubble-side-title");
  const metricsEl = document.getElementById("bubble-side-metrics");
  const stocksEl = document.getElementById("bubble-side-stocks");

  panel.classList.add("open");
  titleEl.textContent = name;
  metricsEl.innerHTML = '<div style="color:var(--muted);font-size:.8rem">載入中...</div>';
  stocksEl.innerHTML = "";

  try {
    const r = await fetch(`${BASE}/sector/api/sector/${encodeURIComponent(sectorId)}?days=60`);
    const d = await r.json();
    const s = d.latest || {};
    const metrics = [
      { lbl: "5D%",  val: pctFmt(s.return_ew_5d)  },
      { lbl: "20D%", val: pctFmt(s.return_ew_20d) },
      { lbl: "60D%", val: pctFmt(s.return_ew_60d) },
      { lbl: "趨勢",  val: s.trend_state || "—"    },
      { lbl: "健康",  val: s.internal_health || "—"},
      { lbl: "股票數", val: s.stock_count ?? "—"   },
    ];
    metricsEl.innerHTML = metrics.map(m =>
      `<div class="bubble-side-metric"><div class="lbl">${m.lbl}</div><div class="val ${retClass(typeof m.val === 'number' ? m.val : null)}">${m.val}</div></div>`
    ).join("");
    const stocks = d.stocks || [];
    stocksEl.innerHTML = `<b style="color:var(--text)">成份股（${stocks.length}支）</b><br>` + stocks.join("、");
  } catch (e) {
    metricsEl.innerHTML = `<div style="color:var(--red)">載入失敗</div>`;
  }
}

// ── 啟動 ────────────────────────────────────────────────────────────────────
init();
