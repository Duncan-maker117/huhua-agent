(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const auth = window.HuhuaHomeAuth, form = $('token-form');
  const menu = $('site-nav'), toggle = $('menu-toggle');
  const defaultHint = $('config-hint').textContent;
  const scopeNames = {
    'profile:read': '读取档案', 'profile:propose': '提交待确认建议', 'profile:contacts': '包含联系方式',
    'resume:read': '读取简历', 'resume:write': '保存简历草稿', 'resume:export': '导出简历',
  };
  let tokenValue = '', selectedTab = 0, busy = false, loadVersion = 0;
  const confirmationTimers = new Set();
  function setMenu(open) {
    menu.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? '关闭导航菜单' : '打开导航菜单');
  }
  toggle.addEventListener('click', () => setMenu(toggle.getAttribute('aria-expanded') !== 'true'));
  menu.addEventListener('click', event => { if (event.target.closest('a')) setMenu(false); });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') { setMenu(false); toggle.focus(); }
  });
  function say(message, error = false) {
    $('connect-status').textContent = message;
    $('connect-status').classList.toggle('error', error);
  }
  async function request(url, data, method = 'GET') {
    let response;
    try {
      response = await fetch(url, {method, credentials: 'same-origin', cache: 'no-store',
        ...(data === undefined ? {} : {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)})});
    } catch (_) { throw new Error('连接失败，请检查网络后重试。当前页面的内容会保留。'); }
    let body; try { body = await response.json(); } catch (_) { body = {}; }
    if (!response.ok) {
      const detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.message;
      throw new Error(response.status === 401 ? '登录已过期，请重新登录。'
        : response.status === 404 ? '当前服务尚未启用账号登录，请等待服务更新后重试。'
        : detail && /[\u3400-\u9fff]/.test(detail) ? detail
        : response.status === 429 ? '操作过于频繁，请稍后重试。'
        : response.status >= 500 ? '服务暂时不可用，请稍后重试。' : `操作未完成（${response.status}），请重试。`);
    }
    return body;
  }
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function mcpLocalTime(value, fallback = '未知') {
    if (!value) return fallback;
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return fallback;
    const pad = part => String(part).padStart(2, '0');
    return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes());
  }
  function setBusy(value) {
    busy = value; form.setAttribute('aria-busy', String(value));
    form.querySelectorAll('input,select,button').forEach(element => { element.disabled = value; });
    $('token-list').querySelectorAll('button').forEach(element => { element.disabled = value; });
  }
  function clearConfirmations() {
    confirmationTimers.forEach(timer => clearTimeout(timer)); confirmationTimers.clear();
  }
  function renderTokens(tokens, calls) {
    clearConfirmations(); $('token-list').replaceChildren(); $('call-list').replaceChildren();
    $('token-empty').hidden = tokens.length > 0;
    $('call-empty').hidden = calls.length > 0;
    for (const token of tokens) {
      const row = node('li', undefined, 'token-row'); row.dataset.tokenId = token.id;
      const main = node('div', undefined, 'token-row-main');
      main.append(node('p', token.name, 'token-row-name'),
        node('p', (token.scopes || []).map(scope => scopeNames[scope] || scope).join(' · '), 'token-row-meta'),
        node('p', '有效期至 ' + mcpLocalTime(token.expires_at) + ' · 最后使用：' + mcpLocalTime(token.last_used_at, '尚未使用'), 'token-row-meta'));
      row.append(main);
      if (token.revoked_at || (token.expires_at && Date.parse(token.expires_at) <= Date.now())) {
        row.append(node('span', token.revoked_at ? '已吊销' : '已过期', 'token-badge'));
      } else {
        const revoke = node('button', '吊销', 'token-revoke'); revoke.type = 'button'; revoke.disabled = busy;
        let confirming = false, timer;
        function reset() { confirming = false; revoke.textContent = '吊销'; revoke.classList.remove('is-confirming'); }
        revoke.addEventListener('click', async () => {
          if (busy) return;
          if (!confirming) {
            confirming = true; revoke.textContent = '确认吊销？'; revoke.classList.add('is-confirming');
            timer = setTimeout(() => { confirmationTimers.delete(timer); reset(); }, 3000);
            confirmationTimers.add(timer); return;
          }
          clearTimeout(timer); confirmationTimers.delete(timer); reset(); setBusy(true);
          try {
            await request('/api/account/mcp/tokens/' + encodeURIComponent(token.id), undefined, 'DELETE');
            say('令牌已吊销。'); await loadTokens();
          } catch (error) { say(error.message, true); }
          finally { setBusy(false); }
        });
        row.append(revoke);
      }
      $('token-list').append(row);
    }
    for (const call of calls) {
      const token = tokens.find(item => item.id === call.token_id);
      $('call-list').append(node('li', mcpLocalTime(call.called_at) + ' · ' + (token?.name || '令牌') + ' · ' + call.tool + ' · ' + call.duration_ms + 'ms · ' + call.status_code));
    }
  }
  async function loadTokens() {
    const version = ++loadVersion;
    $('connect-manage').setAttribute('aria-busy', 'true');
    try {
      const result = await request('/api/account/mcp/tokens');
      if (!result || !Array.isArray(result.tokens) || !Array.isArray(result.recent_calls)) throw new Error('令牌列表响应异常，请稍后重试。');
      if (version === loadVersion) renderTokens(result.tokens, result.recent_calls);
    } catch (error) {
      if (version === loadVersion) say('令牌列表未能刷新：' + error.message, true);
    } finally { if (version === loadVersion) $('connect-manage').setAttribute('aria-busy', 'false'); }
  }
  function showState(state) {
    for (const name of ['loading', 'guest', 'unavailable']) $('connect-state-' + name).hidden = state !== name;
    form.hidden = state !== 'authenticated'; $('connect-manage').hidden = state !== 'authenticated';
  }
  function updateAccount(account) {
    const authenticated = account.authenticated === true;
    $('nav-account').textContent = authenticated ? '我的档案' : '登录';
    $('nav-account-mobile').textContent = authenticated ? '我的档案' : '登录';
    $('nav-workspace-label').textContent = authenticated ? '进入工作台' : '开始写简历';
    $('nav-mobile-label').textContent = authenticated ? '工作台' : '开始';
    if (authenticated) { showState('authenticated'); loadTokens(); return; }
    ++loadVersion; clearConfirmations(); dismissToken();
    $('token-list').replaceChildren(); $('call-list').replaceChildren();
    const unavailable = account.error || account.login_available === false;
    showState(unavailable ? 'unavailable' : 'guest');
    $('connect-unavailable-message').textContent = account.error || '邮箱登录暂未配置，邮件服务准备好后就能获取验证码。';
  }
  // 账号重试由共用登录脚本发起；订阅结果后再退出加载态。
  $('connect-retry').addEventListener('click', () => showState('loading'));

  const tabs = ['claude', 'cursor', 'codex'];
  function updateConfig() {
    const token = tokenValue || '<你的令牌>', origin = location.origin;
    const configs = [
      `claude mcp add --transport http huhua ${origin}/mcp --header "Authorization: Bearer ${token}"`,
      JSON.stringify({mcpServers: {huhua: {url: origin + '/mcp', headers: {Authorization: 'Bearer ' + token}}}}, null, 2),
      '[mcp_servers.huhua]\nurl = ' + JSON.stringify(origin + '/mcp') + '\nhttp_headers = { Authorization = ' + JSON.stringify('Bearer ' + token) + ' }',
    ];
    $('config-text').textContent = configs[selectedTab];
    $('config-label').textContent = ['在终端运行', '写入 ~/.cursor/mcp.json', '写入 ~/.codex/config.toml'][selectedTab];
    $('config-hint').textContent = tokenValue ? '已填入刚生成的令牌。' : defaultHint;
  }
  function selectTab(index, focus = false) {
    selectedTab = index;
    tabs.forEach((name, position) => {
      const tab = $('config-tab-' + name), selected = index === position;
      tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    $('config-panel').setAttribute('aria-labelledby', 'config-tab-' + tabs[index]);
    updateConfig();
  }
  tabs.forEach((name, index) => {
    const tab = $('config-tab-' + name);
    tab.addEventListener('click', () => selectTab(index));
    tab.addEventListener('keydown', event => {
      const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
        : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
      if (next === null) return;
      event.preventDefault(); selectTab(next, true);
    });
  });
  function dismissToken() {
    tokenValue = ''; $('token-value').textContent = ''; $('token-once').hidden = true; updateConfig();
  }
  $('token-dismiss').addEventListener('click', dismissToken);
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !auth.me().authenticated) return;
    const scopes = [...form.querySelectorAll('input[name="scope"]')].filter(input => input.checked).map(input => input.value);
    if (!scopes.length) { say('至少选一项权限', true); return; }
    if (!form.reportValidity()) return;
    setBusy(true); say('正在生成令牌…');
    try {
      const result = await request('/api/account/mcp/tokens', {name: $('token-name').value.trim(), expires_days: Number($('token-days').value), scopes}, 'POST');
      if (typeof result?.token !== 'string' || !result.token) throw new Error('未收到令牌，请刷新列表检查。');
      tokenValue = result.token; $('token-value').textContent = tokenValue;
      $('token-once').hidden = false; updateConfig(); $('token-once').scrollIntoView({block: 'center'});
      say('令牌已生成，请复制接入配置。');
      // 列表读取失败不能抹掉仅返回一次的明文令牌。
      await loadTokens();
    } catch (error) { say(error.message, true); }
    finally { setBusy(false); }
  });
  function bindCopy(copy, source, status, success, failure) {
    let feedbackTimer;
    const label = copy.textContent;
    copy.addEventListener('click', async () => {
      clearTimeout(feedbackTimer); copy.disabled = true;
      try {
        await navigator.clipboard.writeText(source.textContent);
        copy.textContent = '已复制'; status.textContent = success;
        feedbackTimer = setTimeout(() => { copy.textContent = label; if (status.textContent === success) status.textContent = ''; }, 4000);
      } catch (_) { copy.textContent = label; status.textContent = failure; }
      finally { copy.disabled = false; }
    });
  }
  bindCopy($('copy-token'), $('token-value'), $('connect-status'), '令牌已复制，请妥善保存。', '复制未完成，请选中令牌手动复制。');
  bindCopy($('copy-config'), $('config-text'), $('copy-config-status'), '配置已复制。', '复制未完成，请选中上方配置手动复制。');
  for (const task of ['tailor', 'fit', 'project', 'memory', 'check']) {
    bindCopy($('copy-task-' + task), $('mcp-task-' + task), $('copy-task-' + task + '-status'),
      '已复制，可粘贴到你的 AI 助手里。', '复制未完成，请选中示例话术手动复制。');
  }
  selectTab(0); showState('loading'); auth.onChange(updateAccount);
})();
