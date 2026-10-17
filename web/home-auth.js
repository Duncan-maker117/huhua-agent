(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const dialog = $('auth-dialog'), form = $('auth-form');
  const email = $('auth-email'), code = $('auth-code');
  const submit = $('auth-submit'), resend = $('auth-resend');
  const defaultLead = $('auth-lead').textContent;
  const unavailable = '邮箱登录暂未配置，邮件服务准备好后就能获取验证码。';
  const listeners = new Set();
  let account = {authenticated: false}, settled = false, busy = false;
  let sentTo = '', resendAt = 0, interval, closeTimer;

  function apiError(response, body, url) {
    const detail = typeof body.detail === 'string' ? body.detail : body.detail?.message;
    let message;
    if (response.status === 404 && url.startsWith('/api/account/')) message = '当前服务尚未启用账号登录，请等待服务更新后重试。';
    else if (response.status === 401) message = '登录已过期，请重新登录。';
    else if (response.status === 429) message = detail && /[\u3400-\u9fff]/.test(detail) ? detail : '操作过于频繁，请稍后重试。';
    else if (detail && /[\u3400-\u9fff]/.test(detail)) message = detail;
    else if (response.status >= 500) message = '服务暂时不可用，请稍后重试。';
    else message = `操作未完成（${response.status}），请重试。`;
    const error = new Error(message); error.status = response.status;
    error.retryAfter = Number(response.headers.get('Retry-After')) || 0;
    return error;
  }
  async function request(url, data) {
    let response;
    try {
      response = await fetch(url, {method: data === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
        ...(data === undefined ? {} : {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)})});
    } catch (_) { throw new Error('连接失败，请检查网络后重试。当前页面的内容会保留。'); }
    let body; try { body = await response.json(); } catch (_) { body = {}; }
    if (!response.ok) throw apiError(response, body || {}, url);
    return body;
  }
  function say(message, error = false) {
    $('auth-status').textContent = message;
    $('auth-status').classList.toggle('error', error);
  }
  function notifyOne(cb) {
    // 页面订阅者出错不能把 ready 变成拒绝态，或中断其他订阅者。
    try { cb(account); } catch (error) { console.error(error); }
  }
  function notify() { listeners.forEach(notifyOne); }
  function secondStep() { return Boolean(sentTo) && email.value.trim().toLowerCase() === sentTo.toLowerCase(); }
  function syncControls() {
    const sent = secondStep(), blocked = Boolean(account.error) || account.login_available === false;
    const remaining = Math.max(0, Math.ceil((resendAt - Date.now()) / 1000));
    form.setAttribute('aria-busy', String(busy));
    form.querySelectorAll('button,input').forEach(element => { element.disabled = busy; });
    $('auth-fields').hidden = blocked;
    $('auth-code-step').hidden = !sent;
    code.required = sent; code.disabled = busy || blocked || !sent;
    resend.hidden = blocked || !sent;
    resend.disabled = busy || remaining > 0;
    resend.textContent = remaining > 60 ? `${Math.ceil(remaining / 60)} 分钟后可重发` : remaining > 0 ? `${remaining} 秒后可重发` : '重新发送';
    submit.textContent = account.error ? '重试连接' : account.login_available === false ? '我知道了' : sent ? '登录' : '发送验证码';
    submit.disabled = busy || (!blocked && !sent && remaining > 0);
    if (sent) $('auth-destination').textContent = `验证码已发到 ${sentTo}，10 分钟内有效。没收到请看看垃圾邮件。`;
  }
  function setBusy(value) { busy = value; syncControls(); }
  function startTimer() {
    clearInterval(interval);
    if (dialog.open && resendAt > Date.now()) interval = setInterval(() => {
      syncControls();
      if (resendAt <= Date.now()) clearInterval(interval);
    }, 1000);
  }
  function render() {
    syncControls(); startTimer();
    say(account.error || (account.login_available === false ? unavailable : account.authenticated ? '已登录' : secondStep() ? '' : '填写邮箱，获取一次性登录验证码。'), Boolean(account.error));
  }
  async function refreshAccount() {
    try {
      const value = await request('/api/account/me');
      if (!value || typeof value.authenticated !== 'boolean') throw new Error('账号服务响应异常，请稍后重试。');
      account = value;
    } catch (error) { account = {authenticated: false, error: error.message, errorStatus: error.status || 0}; }
    return account;
  }
  async function retryAccount() {
    if (busy) return;
    const retry = $('connect-retry');
    if (retry) retry.disabled = true;
    setBusy(true); say('正在连接账号服务…');
    try { await refreshAccount(); render(); notify(); }
    finally { setBusy(false); if (retry) retry.disabled = false; }
  }
  function cleanup() {
    clearInterval(interval); clearTimeout(closeTimer);
    $('auth-lead').textContent = defaultLead;
  }
  function close() { cleanup(); if (dialog.open) dialog.close(); }
  function open(reason = '') {
    clearTimeout(closeTimer);
    $('auth-lead').textContent = typeof reason === 'string' && reason ? reason : defaultLead;
    if (!dialog.open) dialog.showModal();
    render();
    if (!busy) ($('auth-fields').hidden ? submit : secondStep() ? code : email).focus();
  }
  async function sendCode() {
    if (busy || resendAt > Date.now()) return;
    email.value = email.value.trim();
    if (!email.reportValidity()) return;
    setBusy(true); say('正在发送验证码…');
    try {
      const result = await request('/api/account/login/start', {email: email.value});
      if (result?.sent !== true) throw new Error('未确认验证码发送成功，请稍后重试。');
      sentTo = email.value; code.value = '';
      resendAt = Date.now() + Math.max(1, Number(result.retry_after) || 60) * 1000;
      say('');
    } catch (error) {
      if (error.status === 429) resendAt = Date.now() + Math.max(1, error.retryAfter || 60) * 1000;
      say(error.message, true);
    } finally { setBusy(false); startTimer(); if (dialog.open && secondStep()) code.focus(); }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return;
    if (account.error) { await retryAccount(); return; }
    if (account.login_available === false || account.authenticated) { close(); return; }
    if (!secondStep()) { await sendCode(); return; }
    if (!/^[0-9]{6}$/.test(code.value.trim())) { say('请填写邮件中的 6 位数字验证码。', true); code.focus(); return; }
    setBusy(true); say('正在验证并登录…');
    try {
      const result = await request('/api/account/login/verify', {email: sentTo, code: code.value.trim()});
      if (result?.authenticated !== true) throw new Error('未确认登录成功，请重新验证。');
      await refreshAccount();
      if (!account.authenticated) throw new Error(account.error || '登录状态尚未确认，请重试。');
      sentTo = ''; code.value = ''; resendAt = 0; clearInterval(interval);
      say('已登录'); notify();
      if (dialog.open) closeTimer = setTimeout(close, 600);
    } catch (error) {
      if (error.status === 429) resendAt = Date.now() + Math.max(1, error.retryAfter || 60) * 1000;
      say(error.message, true); startTimer();
    } finally { setBusy(false); }
  });
  email.addEventListener('input', () => { sentTo = ''; code.value = ''; syncControls(); });
  resend.addEventListener('click', sendCode);
  $('auth-close').addEventListener('click', close);
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('close', cleanup);
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
  document.querySelectorAll('[data-auth-open]').forEach(element => element.addEventListener('click', event => {
    if (account.authenticated) return;
    event.preventDefault(); open(element.id === 'connect-login' ? '登录后即可生成 MCP 令牌。' : '');
  }));
  // 接入页的重新检查也更新这份共享状态，避免弹窗仍持有旧的错误状态。
  $('connect-retry')?.addEventListener('click', retryAccount);
  setBusy(true);
  const ready = refreshAccount().then(() => {
    settled = true; setBusy(false); render(); notify();
    if (dialog.open) ($('auth-fields').hidden ? submit : secondStep() ? code : email).focus();
    return account;
  });
  window.HuhuaHomeAuth = {ready, open, me: () => account, onChange(cb) {
    listeners.add(cb); if (settled) notifyOne(cb);
  }};
})();
