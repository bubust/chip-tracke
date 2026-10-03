// auth-shim.js — 寫入保護的前端配套（dashboard 與各分頁 iframe 共用）
// 同源請求自動帶 X-Auth-Token（寫入類與診斷端點需要）；伺服器回 401（需要登入）時跳出登入框，成功後自動重送一次。
// token 存 localStorage，同網域的所有分頁共用，登入一次 30 天內不用再登入。
(function () {
  'use strict';
  if (window.__chipAuthShim) return;
  window.__chipAuthShim = true;
  var KEY = 'chip_auth_token';
  var origFetch = window.fetch.bind(window);
  var pending = null;

  function getToken() { try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; } }
  function setToken(t) { try { t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY); } catch (e) {} }
  function sameOrigin(u) { try { return new URL(u, location.href).origin === location.origin; } catch (e) { return false; } }

  // 登入框（同時只開一個；多個請求一起 401 時共用同一次登入）
  function login() {
    if (pending) return pending;
    pending = new Promise(function (resolve) {
      var m = document.createElement('div');
      m.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:2147483000;display:flex;align-items:center;justify-content:center;padding:16px;font-family:system-ui,sans-serif';
      m.innerHTML = '<form style="background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;padding:20px;width:100%;max-width:320px;color:#e2e8f0">' +
        '<div style="font-weight:700;margin-bottom:6px">🔒 需要登入</div>' +
        '<div style="font-size:.8rem;color:#94a3b8;margin-bottom:12px">修改資料、啟動掃描或更新前請先登入（30 天內不用再輸入）</div>' +
        '<input type="password" autocomplete="current-password" placeholder="密碼" style="width:100%;box-sizing:border-box;padding:10px;border-radius:6px;border:1px solid #2a2d3a;background:#0f1117;color:#e2e8f0;font-size:16px">' +
        '<div class="err" style="color:#f87171;font-size:.8rem;min-height:1.2em;margin-top:6px"></div>' +
        '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:6px">' +
        '<button type="button" class="cancel" style="padding:8px 14px;border-radius:6px;border:1px solid #2a2d3a;background:transparent;color:#e2e8f0">取消</button>' +
        '<button type="submit" style="padding:8px 16px;border-radius:6px;border:none;background:#4f8ef7;color:#fff;font-weight:600">登入</button></div></form>';
      document.body.appendChild(m);
      var form = m.querySelector('form'), input = m.querySelector('input'), err = m.querySelector('.err');
      setTimeout(function () { input.focus(); }, 30);
      function done(ok) { m.remove(); pending = null; resolve(ok); }
      m.querySelector('.cancel').onclick = function () { done(false); };
      form.onsubmit = function (e) {
        e.preventDefault();
        err.textContent = '';
        origFetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                       body: JSON.stringify({ password: input.value }) })
          .then(function (r) { return r.json().then(function (d) { return { r: r, d: d }; }); })
          .then(function (x) {
            if (x.r.ok && x.d.ok) { setToken(x.d.token || ''); done(true); }
            else { err.textContent = (x.d && x.d.detail) || '登入失敗'; input.select(); }
          })
          .catch(function () { err.textContent = '連線失敗'; });
      };
    });
    return pending;
  }

  window.chipAuthLogin = login;
  window.chipAuthLogout = function () { setToken(''); };
  window.chipAuthStatus = function () {
    return origFetch('/api/auth/status', { headers: { 'X-Auth-Token': getToken() } }).then(function (r) { return r.json(); });
  };

  window.fetch = function (input, init) {
    init = init || {};
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    // 同源請求一律帶 token（診斷類 GET 也要登入）；外站請求不碰
    if (!sameOrigin(url) || url.indexOf('/api/auth/login') >= 0) return origFetch(input, init);
    function send() {
      var h = new Headers(init.headers || (typeof input !== 'string' && input ? input.headers : undefined));
      var t = getToken();
      if (t) h.set('X-Auth-Token', t);
      return origFetch(input, Object.assign({}, init, { headers: h }));
    }
    return send().then(function (r) {
      if (r.status !== 401) return r;
      return r.clone().json().catch(function () { return {}; }).then(function (d) {
        if (!d || !d.auth_required) return r;
        setToken('');
        return login().then(function (ok) { return ok ? send() : r; });
      });
    });
  };
})();
