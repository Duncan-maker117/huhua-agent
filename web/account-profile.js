(() => {
  'use strict';
  // Never persist account contents, chat text, or resume JSON in browser storage.
  function clearPrivateCache(all = false) {
    for (const storeName of ['localStorage', 'sessionStorage']) {
      try {
        const storage = window[storeName];
        for (const key of Object.keys(storage)) {
          if (/^huhua_(messages|saved_at|chat_backup:|chat_recovery:|editor_draft:)/.test(key) || (all && /^huhua_/.test(key))) storage.removeItem(key);
        }
      } catch (_) { /* Storage may be unavailable. */ }
    }
  }
  clearPrivateCache();
  let account = {authenticated: false, require_account: true, login_available: false};
  let profile = null, overlay, content, status, opener, returnFocus, busy = false, loadVersion = 0;
  let profileView = 'facts', entryPanel = '';
  let inbox = {items: [], pending_count: 0}, connections = {tokens: [], recent_calls: []};
  let syncConfirmationControls = () => {};
  let confirmationButton = null;
  const selectedConfirmations = new Set();
  let confirmationFailures = [];
  let loginTimer, syncLoginControls = () => {};
  let loginReason = '', guestSession = null, pendingClaim = null;
  const guestSessionKey = 'huhua_guest_session_id';
  const pendingClaimKey = 'huhua_pending_guest_claim';
  const isGuest = () => Boolean((account.guest_allowed && !account.authenticated) || pendingClaim);
  const guestNotice = () => `当前为临时体验，闲置 ${Number(account.guest_retention_hours) || 24} 小时后清理；登录后可导出、保留对话并让 Agent 记住你的信息。`;
  function rememberedSession() {
    try { return isGuest() ? sessionStorage.getItem(guestSessionKey) : localStorage.getItem('huhua_session_id'); } catch (_) { return null; }
  }
  function rememberSession(id) {
    if (!id) return;
    try {
      if (isGuest()) { guestSession = id; sessionStorage.setItem(guestSessionKey, id); }
      else localStorage.setItem('huhua_session_id', id);
    } catch (_) { if (isGuest()) guestSession = id; }
  }
  const login = {email: '', code: '', sentTo: '', resendAt: 0, expiresAt: 0};
  const text = value => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value);
  const node = (tag, value, className = '') => { const n = document.createElement(tag); n.className = className; if (value !== undefined) n.textContent = value; return n; };
  const button = (label, action, secondary = true) => { const n = node('button', label, secondary ? 'profile-button secondary' : 'profile-button'); n.type = 'button'; n.addEventListener('click', action); return n; };
  const mcpTasks = [
    {title: '按 JD 改简历', example: '用胡话简历里我的档案，按这份 JD 改一版简历，并导出 PDF：<粘贴 JD>',
      note: '只用已确认档案事实，逐条带出处，先测页数再导出。', prompt: '/mcp__huhua__tailor_resume_for_jd'},
    {title: '把项目记进档案', example: '读一下这个仓库，把我负责的部分整理成建议，提交到胡话简历档案',
      note: '只提交为待确认建议，需你在网页「我的档案 → 信息确认」确认后才入档。', prompt: '/mcp__huhua__log_project_to_profile'},
    {title: '检查简历依据', example: '检查这份简历里哪些说法在我的胡话简历档案里找不到依据',
      note: '逐条对照档案事实，标出没有出处的句子。'},
  ];
  const fieldNames = {summary: '简介', pr: 'PR 号或链接', level: '级别 / 名次', date: '时间', highlights: '教育荣誉', link: '链接', availability: '到岗 / 可实习时间', name: '姓名', phone: '手机', email: '邮箱', location: '所在地', role: '个人职责', status: '进展状态', description: '经历描述', result: '实际结果', skill: '技能', preference: '长期偏好', objective: '求职方向', school: '学校', degree: '学历', major: '专业', start_date: '开始时间', end_date: '结束时间', company: '公司', title: '岗位', tool: '使用工具', deliverable: '交付物'};
  const categories = {basic: '基本信息', education: '教育', project: '项目', work: '工作与实习', campus: '校园经历', open_source: '开源贡献', awards: '竞赛荣誉', skill: '技能', preference: '偏好'};
  const stateNames = {pending: '待整理', running: '整理中', failed: '整理失败', complete: '已整理', completed: '已整理', succeeded: '已整理'};
  function apiError(response, body, url) {
    const detail = typeof body.detail === 'string' ? body.detail : body.detail?.message;
    const accountRoute = url.startsWith('/api/account/');
    let message;
    if (response.status === 404 && accountRoute) message = '当前服务尚未启用账号登录，请等待服务更新后重试。';
    else if (response.status === 404 && url === '/api/profile') message = '个人档案服务暂未就绪，请稍后重试。';
    else if (response.status === 401) message = '登录已过期，请重新登录。';
    else if (response.status === 429) message = detail && /[\u3400-\u9fff]/.test(detail) ? detail : '操作过于频繁，请稍后重试。';
    else if (detail && /[\u3400-\u9fff]/.test(detail)) message = detail;
    else if (response.status >= 500) message = '服务暂时不可用，请稍后重试。';
    else message = `操作未完成（${response.status}），请重试。`;
    const error = new Error(message); error.status = response.status;
    error.retryAfter = Number(response.headers.get('Retry-After')) || 0;
    return error;
  }
  async function request(url, data, method = 'GET') {
    let response;
    try { response = await fetch(url, {method, credentials: 'same-origin', headers: data === undefined ? {} : {'Content-Type': 'application/json'}, ...(data === undefined ? {} : {body: JSON.stringify(data)})}); }
    catch (_) { throw new Error('连接失败，请检查网络后重试。当前页面的内容会保留。'); }
    let body; try { body = await response.json(); } catch (_) { body = {}; }
    if (!response.ok) throw apiError(response, body, url);
    return body;
  }
  function syncAccountPresentation() {
    if (opener) opener.textContent = account.authenticated ? '我的档案' : '登录账号';
    // Signing in is a centered window; the signed-in profile keeps the side drawer.
    overlay?.classList.toggle('is-login', !account.authenticated || Boolean(pendingClaim));
    const heading = document.getElementById('profile-heading');
    if (heading) heading.textContent = profileView === 'connections' ? '连接 AI 助手' : account.authenticated ? '个人档案' : '登录账号';
    const retentionNotice = document.getElementById('data-retention-notice');
    if (retentionNotice) {
      const retention = account.authenticated && !pendingClaim
        ? '对话及简历保存在你的账号下，可从历史对话继续编辑或手动删除；新建对话会保留旧记录。'
        : `未登录时，对话和简历仅供临时体验，闲置 ${Number(account.guest_retention_hours) || 24} 小时后清理；新建对话后无法从历史找回这次体验。登录后才会长期保留当前对话和个人信息。`;
      retentionNotice.textContent = '发送的内容会交给第三方生成模型处理。' + retention + '请勿上传与求职无关的敏感信息。';
    }
  }
  window.addEventListener('huhua-account-changed', syncAccountPresentation);
  const readAccount = value => {
    if (typeof value.authenticated !== 'boolean' || typeof value.login_available !== 'boolean') throw new Error('账号服务响应异常，请稍后重试。');
    account = {authenticated: false, require_account: true, login_available: false, ...value};
    syncAccountPresentation(); return account;
  };
  const ready = request('/api/account/me').then(value => {
    readAccount(value);
    try { if (account.authenticated) pendingClaim = sessionStorage.getItem(pendingClaimKey); } catch (_) { /* Identifier storage is optional. */ }
    return account;
  }).catch(error => { account.error = error.message; account.errorStatus = error.status; return account; });
  async function refreshAccount() {
    const value = readAccount(await request('/api/account/me'));
    try { pendingClaim = value.authenticated ? sessionStorage.getItem(pendingClaimKey) : null; } catch (_) { /* Identifier storage is optional. */ }
    return value;
  }
  function say(message, error = false) { if (status) { status.textContent = message; status.classList.toggle('error', error); } }
  function setBusy(value) { busy = value; content?.setAttribute('aria-busy', String(value)); content?.querySelectorAll('button,input,textarea,select').forEach(n => { n.disabled = value; }); syncLoginControls(); syncConfirmationControls(); }
  async function mutate(action, success, refresh = true) {
    if (busy) return;
    setBusy(true); say('正在保存…');
    try { await action(); confirmationFailures = []; if (refresh) await loadProfile(); say(success); }
    catch (error) {
      if (error.status === 409) { await loadProfile(); say('资料已被另一处更新，已载入最新内容，请重新核对。', true); }
      else say(error.message, true);
    } finally { setBusy(false); }
  }
  function inputField(form, label, value = '', type = 'text') {
    const wrap = node('label', undefined, 'profile-field'); wrap.append(node('span', label));
    const input = node(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    input.value = text(value); input.required = true; wrap.append(input); form.append(wrap); return input;
  }
  function focusInlineForm(container, kind) {
    const form = container.querySelector('form[data-profile-form="' + kind + '"]');
    if (!form) return false;
    form.querySelector('input,textarea,select')?.focus(); return true;
  }
  function close() { if (pendingClaim) { say('当前对话尚待关联，请点击重试；内容仍保留。', true); return; } overlay.hidden = true; if (account.authenticated) content.replaceChildren(); clearInterval(loginTimer); (returnFocus || opener)?.setAttribute('aria-expanded', 'false'); (returnFocus || opener)?.focus(); }
  async function open(reason = '', panel = '', trigger = opener) {
    selectedConfirmations.clear(); confirmationFailures = [];
    entryPanel = panel === 'connect' || panel === 'profile' ? panel : '';
    profileView = entryPanel === 'connect' ? 'connections' : new URLSearchParams(location.search).get('profile') === 'inbox' ? 'confirmations' : 'facts';
    loginReason = panel === 'connect' ? '登录后可生成 MCP 令牌，连接你的 AI 助手。' : typeof reason === 'string' ? reason : '';
    returnFocus = trigger; syncAccountPresentation();
    overlay.hidden = false; returnFocus?.setAttribute('aria-expanded', 'true'); document.getElementById('btn-close-profile').focus();
    say('正在连接账号服务…');
    await ready;
    if (pendingClaim) renderClaim(); else if (account.authenticated) await loadProfile(); else renderLogin();
  }
  async function retryAccount() {
    if (busy) return;
    setBusy(true); say('正在连接账号服务…');
    try { readAccount(await request('/api/account/me')); account.authenticated ? await loadProfile() : renderLogin(); }
    catch (error) { account.error = error.message; account.errorStatus = error.status; renderLogin(); }
    finally { setBusy(false); }
  }
  function renderLogin() {
    clearInterval(loginTimer); syncLoginControls = () => {}; syncAccountPresentation(); content.replaceChildren();
    content.append(node('p', loginReason || '无需登录即可聊天、改简历和查看模板。登录后可以导出简历、保留对话，让 Agent 记住你的信息。', 'profile-muted'));
    content.append(node('p', '用邮箱验证码登录，无需设置密码。当前聊好的内容会接着保留。', 'profile-muted'));
    if (profileView === 'connections') {
      const tasks = node('ul', undefined, 'profile-mcp-task-names');
      for (const task of mcpTasks) tasks.append(node('li', task.title));
      content.append(node('p', '接入后可以这样用', 'profile-muted'), tasks);
    }
    if (account.error) {
      say(account.error, true);
      content.append(node('div', account.errorStatus === 404 ? '登录入口尚未就绪，暂时无法获取验证码。更新服务后，点击下方按钮重新连接。' : '暂时无法确认登录状态。连接恢复后可以继续，不会自动提交你的资料。', 'profile-notice'));
      content.append(button('重试连接', retryAccount)); return;
    }
    if (!account.login_available) {
      content.append(node('div', '邮箱登录暂未配置。邮件服务准备好后，就可以在这里获取验证码。', 'profile-notice'));
      content.append(button('重新检查', retryAccount));
      say(account.require_account ? '登录服务已连接，邮件发送尚未就绪。' : '当前是本地浏览器模式，尚未关联账号。'); return;
    }
    const form = node('form', undefined, 'profile-form');
    const email = inputField(form, '登录邮箱', login.email, 'email'); email.autocomplete = 'email'; email.maxLength = 254; email.placeholder = '你的常用邮箱';
    const codeWrap = node('div', undefined, 'profile-code-step');
    const destination = node('p', '', 'profile-muted'); destination.id = 'profile-code-destination'; codeWrap.append(destination);
    const code = inputField(codeWrap, '邮箱验证码', login.code); code.inputMode = 'numeric'; code.autocomplete = 'one-time-code'; code.pattern = '[0-9]{6}'; code.maxLength = 6; code.placeholder = '输入 6 位验证码'; code.setAttribute('aria-describedby', destination.id);
    const verify = node('button', '登录', 'profile-button'); verify.type = 'submit';
    const send = button('发送验证码', sendCode, false);
    form.append(send, codeWrap); codeWrap.append(verify);
    function validCodeStep() { return login.sentTo && email.value.trim().toLowerCase() === login.sentTo.toLowerCase(); }
    syncLoginControls = () => {
      const sent = validCodeStep(); const remaining = Math.max(0, Math.ceil((login.resendAt - Date.now()) / 1000));
      codeWrap.hidden = !sent; code.required = Boolean(sent); code.disabled = busy || !sent; verify.disabled = busy || !sent;
      send.type = sent ? 'button' : 'submit';
      send.disabled = busy || remaining > 0;
      send.textContent = remaining > 3600 ? '发送暂受限' : remaining > 60 ? `${Math.ceil(remaining / 60)} 分钟后可重试` : remaining > 0 ? `${remaining} 秒后可重发` : sent ? '重新发送验证码' : '发送验证码';
      destination.textContent = `收件邮箱：${login.sentTo}。请查看收件箱或垃圾邮件。`;
      if (sent && login.expiresAt) destination.textContent += Date.now() < login.expiresAt ? '验证码 10 分钟内有效。' : '此验证码可能已过期，请重新获取。';
    };
    async function sendCode() {
      if (busy || login.resendAt > Date.now() || !email.reportValidity()) return;
      setBusy(true); say('正在发送验证码…');
      try {
        const result = await request('/api/account/login/start', {email: email.value.trim()}, 'POST');
        if (result.sent !== true) throw new Error('未确认验证码发送成功，请稍后重试。');
        login.email = email.value.trim(); login.sentTo = login.email; login.code = ''; code.value = '';
        login.resendAt = Date.now() + Math.max(1, Number(result.retry_after) || 60) * 1000;
        login.expiresAt = Date.now() + Math.max(1, Number(result.expires_in) || 600) * 1000;
        say(typeof result.message === 'string' && result.message ? result.message : '验证码已提交发送，请检查收件箱或垃圾邮件。');
      } catch (error) {
        if (error.status === 429) login.resendAt = Date.now() + Math.max(1, error.retryAfter || 60) * 1000;
        say(error.message, true);
      } finally { setBusy(false); if (!codeWrap.hidden) code.focus(); }
    }
    email.addEventListener('input', () => { login.email = email.value; login.code = ''; code.value = ''; syncLoginControls(); });
    code.addEventListener('input', () => { login.code = code.value; });
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (busy) return;
      if (!validCodeStep()) { await sendCode(); return; }
      if (!form.reportValidity()) return;
      setBusy(true); say('正在验证并登录…');
      try {
        if (window.HuhuaHistory?.prepareLogin && !await window.HuhuaHistory.prepareLogin()) throw new Error('请先结束当前生成或上传，再登录；已输入的内容会保留。');
        if (window.HuhuaEditor?.prepareProfileChange && !await window.HuhuaEditor.prepareProfileChange()) throw new Error('请先重试保存当前修改，再登录；编辑内容仍保留在本页。');
        const currentGuest = isGuest() ? guestSession : null;
        document.querySelectorAll('main').forEach(main => { main.inert = true; });
        const result = await request('/api/account/login/verify', {email: login.sentTo, code: code.value.trim()}, 'POST');
        if (result.authenticated !== true) throw new Error('未确认登录成功，请重新验证。');
        login.code = ''; login.sentTo = ''; clearInterval(loginTimer);
        if (currentGuest) {
          pendingClaim = currentGuest;
          try { sessionStorage.setItem(pendingClaimKey, currentGuest); } catch (_) { /* In-memory retry remains available. */ }
          document.querySelectorAll('main').forEach(main => { main.inert = true; });
          window.dispatchEvent(new Event('huhua-account-claim-pending'));
          await claimCurrentGuest();
        }
        else await finishLogin(null);
      } catch (error) { say(error.message, true); }
      finally { setBusy(false); if (!pendingClaim) document.querySelectorAll('main').forEach(main => { main.inert = false; }); }
    });
    content.append(form); syncLoginControls(); loginTimer = setInterval(syncLoginControls, 1000);
    say(validCodeStep() ? '填写邮件中的 6 位验证码即可登录。' : '填写邮箱，获取一次性登录验证码。');
  }
  async function finishLogin(session) {
    readAccount(await request('/api/account/me'));
    if (!account.authenticated) throw new Error('登录状态尚未确认，请重试。');
    pendingClaim = null; guestSession = null;
    document.querySelectorAll('main').forEach(main => { main.inert = false; });
    try { sessionStorage.removeItem(guestSessionKey); sessionStorage.removeItem(pendingClaimKey); } catch (_) { /* Optional identifier only. */ }
    if (session) {
      rememberSession(session);
      const url = new URL(location.href); url.searchParams.set('session', session);
      if (url.pathname === '/' || url.pathname === '/static/index.html') url.pathname = '/chat';
      history.replaceState(null, '', url.pathname + url.search + url.hash);
    }
    // Continue in place: the composer, attachments and unsaved editor fields stay intact.
    window.dispatchEvent(new CustomEvent('huhua-account-changed', {detail: {session_id: session}}));
    if (entryPanel) { entryPanel = ''; await loadProfile(); }
    else close();
  }
  function renderClaim(error = '') {
    clearInterval(loginTimer); syncLoginControls = () => {}; content.replaceChildren();
    content.append(node('p', '邮箱已验证。当前对话还没有确认保存到账号，页面里的聊天和简历仍然保留。', 'profile-muted'));
    content.append(button('重试保留当前对话', async () => {
      if (busy) return;
      setBusy(true); await claimCurrentGuest(); setBusy(false);
    }, false));
    say(error || '正在把当前对话关联到账号…', Boolean(error));
  }
  async function claimCurrentGuest() {
    const session = pendingClaim;
    if (!session) return;
    try {
      const result = await request('/api/account/claim-guest', {session_id: session}, 'POST');
      if (result.session_id !== session || ![true, 0, 1].includes(result.claimed)) throw new Error('当前对话尚未确认关联，请重试。');
      await finishLogin(session);
    } catch (error) { renderClaim(error.message + ' 请重试保留当前对话。'); }
  }
  function requireLogin(reason = '') {
    if (!(account.require_account && (!account.authenticated || pendingClaim))) return false;
    open(reason); return true;
  }
  function sourceDetails(fact) {
    const details = node('details', undefined, 'profile-source'); details.append(node('summary', '查看来源与时间'));
    details.append(node('p', '用户提供 · 修订 ' + fact.revision));
    const sources = Array.isArray(fact.sources) ? fact.sources : [];
    if (!sources.length) details.append(node('p', '来源记录：' + (fact.source_ids || []).join('、')));
    for (const source of sources) {
      const line = node('div'); line.append(node('p', source.kind === 'memory_import' ? '来自其他 AI 导入' : source.kind === 'manual' ? '手动填写' : '对话中补充'));
      if (source.excerpt) line.append(node('blockquote', text(source.excerpt)));
      if (source.evidence) line.append(node('p', '原始依据：' + source.evidence));
      if (source.recorded_at) line.append(node('p', '记录于 ' + source.recorded_at));
      if (source.session_id) { const link = node('a', '打开来源对话'); link.href = '/chat?session=' + encodeURIComponent(source.session_id); line.append(link); }
      details.append(line);
    }
    if (fact.effective_at) details.append(node('p', '生效时间：' + fact.effective_at));
    for (const entry of fact.history || []) details.append(node('p', '历史记录：' + factValue(entry) + (entry.until ? '（截至 ' + entry.until + '）' : '')));
    return details;
  }
  function factValue(fact) {
    return (fact.proficiency ? text(fact.proficiency) + ' ' : '') + text(fact.value);
  }
  function editFact(card, fact) {
    const form = node('form', undefined, 'profile-form');
    const value = inputField(form, '更正本人事实', factValue(fact), 'textarea'); value.maxLength = 4000;
    form.append(node('p', '这里会更正个人档案，并提示受影响的简历同步。只调整本份简历的措辞，请到简历编辑。', 'profile-muted'));
    const save = node('button', '保存更正', 'profile-button'); save.type = 'submit';
    form.append(save, button('取消', renderProfile));
    form.addEventListener('submit', e => { e.preventDefault(); if (!form.reportValidity()) return; mutate(() => request('/api/profile/facts/' + encodeURIComponent(fact.id), {value: value.value.trim(), expected_revision: fact.revision}, 'PATCH'), '已更正个人档案。'); });
    card.replaceChildren(form); value.focus();
  }
  function renderFact(fact) {
    const card = node('div', undefined, 'profile-fact-row'); card.dataset.factId = fact.id;
    const body = node('div', undefined, 'profile-fact-body');
    const label = fact.field === 'name' && fact.category !== 'basic' ? '名称' : fieldNames[fact.field] || fact.field;
    body.append(node('strong', label, 'profile-field-name'), node('p', factValue(fact), 'profile-value'), sourceDetails(fact));
    if ((fact.sources || []).some(source => source.kind === 'memory_import')) body.append(node('span', '来自其他 AI 导入', 'profile-muted'));
    const actions = node('div', undefined, 'profile-actions profile-field-actions');
    actions.append(button('更正', () => editFact(card, fact)), button('删除', () => {
      const confirmBox = node('div', undefined, 'profile-notice');
      confirmBox.append(node('p', '从个人档案删除，并停止后续引用。相关原始聊天可能仍保留，可到历史对话单独删除；备份按保留期限清理。'));
      confirmBox.append(button('确认删除这条事实', () => mutate(() => request('/api/profile/facts/' + encodeURIComponent(fact.id) + '?expected_revision=' + encodeURIComponent(fact.revision), undefined, 'DELETE'), '已删除，后续不再使用这条事实。')), button('取消', renderProfile));
      actions.replaceChildren(confirmBox);
    }));
    card.append(body, actions); return card;
  }
  function currentProfileSession() {
    const params = new URLSearchParams(location.search);
    return params.get('session_id') || params.get('session');
  }
  function renderEntry(category, subject, facts) {
    const card = node('article', undefined, 'profile-card profile-entry');
    card.dataset.category = category; card.dataset.subject = subject;
    const head = node('div', undefined, 'profile-entry-head'); head.append(node('h3', subject));
    const session = currentProfileSession();
    if (session && category !== 'preference') head.append(button('用于当前简历', () => mutate(async () => {
      if (window.HuhuaEditor && !await window.HuhuaEditor.prepareProfileChange()) throw new Error('当前简历还有未保存修改，请先重试保存或下载草稿。');
      await request('/api/resume/session/' + encodeURIComponent(session) + '/profile-facts', {fact_ids: facts.map(fact => fact.id)}, 'POST');
      if (window.HuhuaEditor) await window.HuhuaEditor.refreshCurrent();
      if (window.HuhuaWorkspace) await window.HuhuaWorkspace.refresh?.();
    }, '已用于当前简历，可在预览中核对。', false)));
    card.append(head, ...facts.map(renderFact)); return card;
  }
  function renderFactGroups(facts) {
    for (const category of Object.keys(categories)) {
      const groups = new Map();
      for (const fact of facts.filter(fact => fact.category === category)) {
        const subject = category === 'basic' ? '基本信息' : fact.subject;
        if (!groups.has(subject)) groups.set(subject, []);
        groups.get(subject).push(fact);
      }
      if (!groups.size) continue;
      content.append(node('h2', categories[category], 'profile-section-title'));
      for (const [subject, entries] of groups) content.append(renderEntry(category, subject, entries));
    }
  }
  function addFact() {
    if (focusInlineForm(content, 'fact')) return;
    const card = node('form', undefined, 'profile-card profile-form');
    card.dataset.profileForm = 'fact';
    const label = node('label', undefined, 'profile-field'); label.append(node('span', '资料类别'));
    const category = node('select'); category.setAttribute('aria-label', '资料类别'); for (const [key, value] of Object.entries(categories)) { const option = node('option', value); option.value = key; category.append(option); } label.append(category); card.append(label);
    const subject = inputField(card, '属于哪段经历或信息', '基本信息');
    const fieldLabel = node('label', undefined, 'profile-field'); fieldLabel.append(node('span', '信息类型')); const field = node('select'); field.setAttribute('aria-label', '信息类型'); for (const [key, label] of Object.entries(fieldNames)) { const option = node('option', label); option.value = key; field.append(option); } fieldLabel.append(field); card.append(fieldLabel);
    const allowed = {basic: ['name','phone','email','location','objective','link','availability'], education: ['school','degree','major','start_date','end_date','highlights','description'], project: ['role','status','description','result','tool','deliverable','start_date','end_date'], work: ['company','title','role','description','result','start_date','end_date'], campus: ['name','role','description','result','link','start_date','end_date'], open_source: ['name','summary','pr','description','result','link'], awards: ['name','level','date','description','result','link'], skill: ['skill','tool'], preference: ['preference']};
    const updateFields = () => { field.replaceChildren(); for (const key of allowed[category.value]) { const option = node('option', fieldNames[key]); option.value = key; field.append(option); } };
    category.addEventListener('change', () => { updateFields(); if (['基本信息','长期偏好'].includes(subject.value)) subject.value = category.value === 'basic' ? '基本信息' : category.value === 'preference' ? '长期偏好' : ''; subject.placeholder = category.value === 'project' ? '例如：PDF 工具项目' : '这条信息属于哪段经历'; }); updateFields();
    subject.maxLength = 160;
    const value = inputField(card, '本人提供的内容', '', 'textarea'); value.maxLength = 4000;
    const save = node('button', '加入个人档案', 'profile-button'); save.type = 'submit'; card.append(save, button('取消', renderProfile));
    card.addEventListener('submit', event => { event.preventDefault(); if (!card.reportValidity()) return; mutate(() => request('/api/profile/facts', {category: category.value, subject: subject.value.trim(), field: category.value === 'preference' ? 'preference' : field.value, value: value.value.trim()}, 'POST'), '已加入个人档案。'); });
    content.prepend(card); value.focus();
  }
  function renderConflict(conflict) {
    const card = node('article', undefined, 'profile-card conflict'); card.append(node('p', '需要你确认', 'profile-eyebrow'), node('h3', [conflict.subject, fieldNames[conflict.field] || conflict.field].filter(Boolean).join(' · ')), node('p', '原记录：' + text(conflict.current_value)), node('p', '新说法：' + text(conflict.proposed_value)));
    card.dataset.conflictId = conflict.id;
    if (conflict.import_batch_id) card.append(node('p', '来自其他 AI 导入', 'profile-muted'));
    if (conflict.evidence) card.append(node('blockquote', conflict.evidence, 'profile-source'));
    const actions = node('div', undefined, 'profile-actions');
    const resolve = (choice, value) => mutate(() => request('/api/profile/conflicts/' + encodeURIComponent(conflict.id) + '/resolve', {choice, value, expected_revision: conflict.expected_revision}, 'POST'), '冲突已处理。');
    actions.append(button('保留原记录', () => resolve('keep')), button('采用新说法', () => resolve('replace')), button('我来更正', () => {
      const form = node('form', undefined, 'profile-form'); const input = inputField(form, '正确说法', '', 'textarea'); const save = node('button', '确认更正', 'profile-button'); save.type = 'submit'; form.append(save, button('取消', renderProfile));
      form.addEventListener('submit', e => { e.preventDefault(); if (form.reportValidity()) resolve('custom', input.value.trim()); }); actions.replaceChildren(form); input.focus();
    })); card.append(actions); return card;
  }
  function renderInboxItem(item) {
    const card = node('article', undefined, 'profile-card profile-inbox-item'); card.dataset.inboxId = item.id;
    const origin = item.import_batch_id ? '来自其他 AI 导入 · 内容不确定，待你确认' : item.source_kind === 'memory_import' ? '来自其他 AI 导入 · 待你确认' : 'AI 助手建议 · 待你确认';
    card.append(node('p', origin, 'profile-eyebrow'), node('h3', (categories[item.category] || item.category) + ' · ' + item.subject + ' · ' + (fieldNames[item.field] || item.field)), node('p', factValue(item) || '尚未提供内容，请改一下再确认', 'profile-value'));
    const evidence = node('div', undefined, 'profile-source'); evidence.append(node('strong', '助手提供的依据（尚未核实）'), node('blockquote', item.evidence)); card.append(evidence);
    const actions = node('div', undefined, 'profile-actions');
    const accept = value => mutate(() => request('/api/account/mcp/inbox/' + encodeURIComponent(item.id) + '/accept', {expected_revision: item.expected_revision, ...(value === undefined ? {} : {value})}, 'POST'), '已确认。若与已有资料冲突，请在信息确认中继续核对。');
    actions.append(button('确认', () => accept(), false), button('改一下再确认', () => {
      const form = node('form', undefined, 'profile-form'); const value = inputField(form, '确认进入档案的内容', factValue(item), 'textarea'); value.maxLength = 4000;
      const submit = node('button', '确认修改并加入档案', 'profile-button'); submit.type = 'submit'; form.append(submit, button('取消', renderProfile));
      form.addEventListener('submit', event => { event.preventDefault(); if (form.reportValidity()) return accept(value.value.trim()); }); actions.replaceChildren(form); value.focus();
    }), button('不要', () => mutate(() => request('/api/account/mcp/inbox/' + encodeURIComponent(item.id) + '/reject', {}, 'POST'), '已拒绝，未加入档案。')));
    card.append(actions); return card;
  }
  function pendingCount() { return (profile?.conflicts || []).length + (inbox.pending_count || 0); }
  function updateConfirmationBadge() {
    const confirmation = confirmationButton;
    if (!confirmation) return;
    confirmation.replaceChildren(); confirmation.textContent = '信息确认';
    if (pendingCount()) {
      const badge = node('span', String(pendingCount()), 'profile-confirm-badge');
      badge.setAttribute('aria-label', pendingCount() + ' 条待确认'); confirmation.append(badge);
    }
  }
  function renderConfirmations() {
    const entries = [...(inbox.items || []).map(item => ({kind: 'inbox', item})),
      ...(profile.conflicts || []).map(item => ({kind: 'conflict', item}))];
    const key = entry => entry.kind + ':' + entry.item.id;
    const keys = new Set(entries.map(key));
    for (const id of selectedConfirmations) if (!keys.has(id)) selectedConfirmations.delete(id);
    if (confirmationFailures.length) {
      const failures = node('div', undefined, 'profile-notice profile-batch-failures'); failures.setAttribute('role', 'alert');
      failures.append(node('strong', '以下条目未处理，其余所选已生效：'));
      const list = node('ul');
      for (const failure of confirmationFailures) list.append(node('li', failure.label + '：' + failure.message));
      failures.append(list); content.append(failures);
    }
    if (!entries.length) { content.append(node('p', '没有待确认的信息。', 'profile-muted')); return; }
    const controls = [], checks = [];
    function selector(label, subset, compact = false) {
      const wrap = node('label', undefined, compact ? 'profile-selection profile-selection-compact' : 'profile-selection'); const input = node('input'); input.type = 'checkbox';
      input.setAttribute('aria-label', label); wrap.append(input, node('span', label));
      input.addEventListener('change', () => { for (const entry of subset) { if (input.checked) selectedConfirmations.add(key(entry)); else selectedConfirmations.delete(key(entry)); } syncConfirmationControls(); });
      checks.push({input, subset}); return wrap;
    }
    const toolbar = node('div', undefined, 'profile-batch-toolbar'); toolbar.append(selector('全选待确认信息', entries));
    async function runBatch(action) {
      if (busy) return;
      const chosen = entries.filter(entry => selectedConfirmations.has(key(entry)));
      if (!chosen.length) return;
      setBusy(true); say('正在处理所选信息…');
      try {
        const result = await request('/api/profile/confirmations/batch', {action, items: chosen.map(({kind, item}) => ({kind, id: item.id, expected_revision: item.expected_revision}))}, 'POST');
        confirmationFailures = result.results.filter(row => row.status === 'failed').map(row => {
          const item = chosen.find(entry => entry.kind === row.kind && entry.item.id === row.id)?.item;
          return {...row, label: item ? item.subject + ' · ' + (fieldNames[item.field] || item.field) : row.id};
        });
        selectedConfirmations.clear();
        await loadProfile();
        const count = action === 'accept' ? result.accepted_count : result.rejected_count;
        const stale = confirmationFailures.filter(row => row.code === 'revision_conflict').length;
        const other = confirmationFailures.length - stale;
        const conflicts = result.results.filter(row => row.archive_result === 'conflict').length;
        say(`已${action === 'accept' ? '确认' : '拒绝'} ${count} 条` + (stale ? `，${stale} 条因档案已更新需重新查看` : '')
          + (other ? `，${other} 条未处理，原因见下方` : '') + (conflicts ? `，其中 ${conflicts} 条与已有档案冲突，请继续核对` : '') + '。', Boolean(confirmationFailures.length));
      } catch (error) {
        if (error.status === 409) await loadProfile();
        say(error.message, true);
      } finally { setBusy(false); }
    }
    for (const [action, label] of [['accept', '确认所选'], ['reject', '不要所选']]) {
      const control = button(label + '（0）', () => runBatch(action), action !== 'accept'); controls.push({control, label}); toolbar.append(control);
    }
    content.append(toolbar, node('p', '确认冲突项会采用新说法；不要冲突项会保留原记录。空白或占位内容需先修改。', 'profile-muted'));
    const groups = new Map();
    for (const entry of entries) {
      const title = entry.kind === 'conflict' ? '与已有档案冲突' : entry.item.import_batch_id || entry.item.source_kind === 'memory_import' ? '来自其他 AI 导入' : '来自 AI 助手的建议';
      if (!groups.has(title)) groups.set(title, []);
      groups.get(title).push(entry);
    }
    for (const [title, subset] of groups) {
      const group = node('section', undefined, 'profile-confirm-group'); group.append(node('h3', title, 'profile-section-title'), selector('选择整组：' + title, subset));
      for (const entry of subset) {
        const card = entry.kind === 'conflict' ? renderConflict(entry.item) : renderInboxItem(entry.item);
        card.classList.add('profile-selectable');
        card.prepend(selector('选择：' + entry.item.subject + ' · ' + (fieldNames[entry.item.field] || entry.item.field), [entry], true)); group.append(card);
      }
      content.append(group);
    }
    syncConfirmationControls = () => {
      for (const {input, subset} of checks) {
        const count = subset.filter(entry => selectedConfirmations.has(key(entry))).length;
        input.checked = count === subset.length; input.indeterminate = count > 0 && count < subset.length; input.disabled = busy;
      }
      for (const {control, label} of controls) { control.textContent = `${label}（${selectedConfirmations.size}）`; control.disabled = busy || !selectedConfirmations.size; }
    };
    syncConfirmationControls();
  }
  async function undoMemoryImport(batchId) {
    if (busy) return;
    setBusy(true); say('正在撤销这次导入…');
    try {
      const result = await request('/api/profile/import-memory/' + encodeURIComponent(batchId) + '/undo', {}, 'POST');
      confirmationFailures = [];
      await loadProfile();
      say(`已撤销 ${result.deleted_count} 条新导入的信息` + (result.cancelled_count ? `，取消 ${result.cancelled_count} 条待确认信息` : '')
        + (result.changed_count ? `；${result.changed_count} 条后来已更正，予以保留` : '') + '。');
    } catch (error) { say(error.message, true); }
    finally { setBusy(false); }
  }
  async function copyMcp(value) {
    try { await navigator.clipboard.writeText(value); say('已复制。'); }
    catch (_) { say('未能复制，请选中内容手动复制。', true); }
  }
  async function importMemory() {
    if (busy || focusInlineForm(content, 'memory-import')) return;
    const form = node('form', undefined, 'profile-card profile-form profile-memory-import');
    form.dataset.profileForm = 'memory-import';
    form.append(node('h2', '从其他 AI 导入', 'profile-section-title'),
      node('p', '让你常用的 AI 把它记得的你的经历整理出来。明确的信息导入即加入档案，重复内容自动跳过；只有冲突和不确定内容需要确认。可以单条更正、删除或撤销这次导入。', 'profile-muted'));
    const step1 = node('div', undefined, 'profile-memory-step');
    const step1Head = node('div', undefined, 'profile-memory-step-head');
    step1Head.append(node('span', '1', 'profile-memory-step-index'), node('strong', '复制提示词，发给 ChatGPT / Claude / 豆包 / Kimi / DeepSeek'));
    const prompt = node('textarea', undefined, 'profile-memory-prompt'); prompt.readOnly = true; prompt.rows = 6;
    prompt.setAttribute('aria-label', '记忆导出提示词');
    const copy = button('复制提示词', () => copyMcp(prompt.value)); copy.disabled = true; copy.classList.add('profile-memory-copy');
    const retry = button('重新读取提示词', () => loadPrompt()); retry.hidden = true;
    step1.append(step1Head, prompt, copy, retry);
    const step2 = node('div', undefined, 'profile-memory-step');
    const step2Head = node('div', undefined, 'profile-memory-step-head');
    step2Head.append(node('span', '2', 'profile-memory-step-index'), node('strong', '把它的回答整段粘贴回来'));
    const answer = node('textarea', undefined, 'profile-memory-answer'); answer.rows = 8; answer.placeholder = '粘贴完整回答（包括 JSON 代码块）';
    answer.setAttribute('aria-label', '粘贴 AI 的回答');
    const hint = node('p', '', 'profile-muted profile-memory-hint');
    step2.append(step2Head, answer, hint);
    const submit = node('button', '导入档案', 'profile-button'); submit.type = 'submit';
    const actionsRow = node('div', undefined, 'profile-memory-actions');
    actionsRow.append(submit, button('取消', () => { if (!busy) renderProfile(); }));
    const result = node('p', '', 'profile-memory-result'); result.setAttribute('role', 'status'); result.setAttribute('aria-live', 'polite');
    form.append(step1, step2, actionsRow, result); content.prepend(form);
    async function loadPrompt() {
      if (busy) return;
      setBusy(true); say('正在读取导出提示词…');
      try {
        const response = await request('/api/profile/import-memory/prompt');
        if (typeof response.prompt !== 'string' || !response.prompt) throw new Error('提示词暂不可用，请重试。');
        prompt.value = response.prompt; retry.hidden = true;
        hint.textContent = `单次最多 ${response.max_facts} 条，超过 ${response.max_chars} 字会截断并提示，请分批导入。`;
        say('提示词已准备好。');
      } catch (error) { retry.hidden = false; say(error.message, true); }
      finally { setBusy(false); copy.disabled = !prompt.value; }
    }
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (busy || !form.reportValidity()) return;
      if (!answer.value.trim()) { say('请先粘贴 AI 的回答。', true); return; }
      setBusy(true); say('正在导入档案…');
      try {
        const response = await request('/api/profile/import-memory', {text: answer.value}, 'POST');
        const count = Number(response.added_count) || 0, duplicates = Number(response.duplicate_count) || 0;
        const pending = [[response.conflict_count, '冲突'], [response.uncertain_count, '不确定']].filter(([value]) => Number(value) > 0).map(([value, label]) => `${Number(value)} 条${label}`).join('、');
        result.textContent = `已加入档案 ${count} 条` + (duplicates ? `，${duplicates} 条重复已跳过` : '') + '。' + (pending ? pending + '，需要确认。' : '')
          + (response.warnings || []).join(' ');
        say(result.textContent);
        if (response.batch_id) {
          const undo = button('撤销这次导入', () => undoMemoryImport(response.batch_id)); form.append(undo);
        }
        if (!form.querySelector('.profile-memory-review')) {
          const review = button('查看待确认信息', async () => {
            if (busy) return;
            profileView = 'confirmations'; await loadProfile();
          }); review.classList.add('profile-memory-review'); form.append(review);
        }
        try {
          [profile, inbox] = await Promise.all([request('/api/profile'), request('/api/account/mcp/inbox')]);
          updateConfirmationBadge();
        } catch (_) { say(result.textContent + ' 计数暂未刷新，请点击刷新档案。', true); }
      } catch (error) { result.textContent = error.message + ' 输入已保留，可重试。'; say(result.textContent, true); }
      finally { setBusy(false); copy.disabled = !prompt.value; }
    });
    await loadPrompt(); answer.focus();
  }
  function renderMcpTasks() {
    const section = node('section', undefined, 'profile-mcp-tasks'); section.setAttribute('aria-label', '接入后可以这样用');
    section.append(node('h3', '接入后可以这样用'));
    for (const task of mcpTasks) {
      const row = node('article', undefined, 'profile-mcp-task');
      const heading = node('div', undefined, 'profile-mcp-task-heading');
      const copy = button('复制', () => copyMcp(task.example)); copy.setAttribute('aria-label', '复制' + task.title + '示例');
      heading.append(node('h4', task.title), copy);
      row.append(heading, node('p', task.example, 'profile-mcp-task-example'), node('p', task.note, 'profile-muted'));
      section.append(row);
    }
    return section;
  }
  function showMcpToken(token) {
    const panel = node('section', undefined, 'profile-notice profile-token-once'); panel.setAttribute('aria-label', '仅显示一次的令牌');
    panel.append(node('strong', '令牌仅显示这一次，请现在保存。关闭面板后无法再次查看。'));
    const field = inputField(panel, '个人访问令牌', token, 'textarea'); field.readOnly = true; field.spellcheck = false;
    panel.append(button('复制令牌', () => copyMcp(token)));
    const origin = location.origin;
    const command = 'claude mcp add --transport http huhua ' + origin + '/mcp --header "Authorization: Bearer ' + token + '"';
    const cursor = JSON.stringify({mcpServers: {huhua: {url: origin + '/mcp', headers: {Authorization: 'Bearer ' + token}}}}, null, 2);
    const codex = '[mcp_servers.huhua]\nurl = ' + JSON.stringify(origin + '/mcp') + '\nhttp_headers = { Authorization = ' + JSON.stringify('Bearer ' + token) + ' }';
    for (const [label, value] of [['Claude Code', command], ['Cursor', cursor], ['Codex', codex]]) {
      const details = node('details', undefined, 'profile-mcp-config'); details.open = label === 'Claude Code'; details.append(node('summary', label));
      details.append(node('pre', value), button('复制 ' + label + (label === 'Claude Code' ? ' 命令' : ' 配置'), () => copyMcp(value))); panel.append(details);
    }
    panel.append(node('p', '接好后试试上面的任务；Claude Code 用户也可使用以下命令：'));
    for (const task of mcpTasks.filter(task => task.prompt)) {
      const hint = node('p', task.title + '：'); hint.append(node('code', task.prompt)); panel.append(hint);
    }
    panel.append(button('已保存，隐藏令牌', () => panel.remove()));
    const form = document.getElementById('profile-mcp-token-form');
    form.parentElement.insertBefore(panel, form);
  }
  function mcpLocalTime(value, fallback = '未知') {
    if (!value) return fallback;
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return fallback;
    const pad = part => String(part).padStart(2, '0');
    return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes());
  }
  function renderConnections() {
    const section = node('section', undefined, 'profile-connections'); section.setAttribute('aria-label', '连接 AI 助手');
    section.append(node('h2', '连接 AI 助手', 'profile-section-title'), node('p', '连接 Claude Code、Cursor 或 Codex。助手提出的信息需要你在网页确认，才会进入档案。', 'profile-muted'));
    section.append(renderMcpTasks());
    const form = node('form', undefined, 'profile-card profile-form');
    form.id = 'profile-mcp-token-form';
    const name = inputField(form, '令牌名称', '我的 AI 助手'); name.maxLength = 80;
    const days = inputField(form, '有效天数（1–365，默认 90）', '90', 'number'); days.min = '1'; days.max = '365';
    const scopeGroup = node('fieldset', undefined, 'profile-mcp-scopes'); scopeGroup.append(node('legend', '允许的操作'));
    const scopes = [];
    for (const [scope, label] of [['profile:read','读取档案'],['profile:contacts','包含联系方式'],['profile:propose','提交待确认建议'],['resume:read','读取简历'],['resume:write','保存简历草稿'],['resume:export','导出简历']]) {
      const wrap = node('label'); const input = node('input'); input.type = 'checkbox'; input.value = scope; input.checked = scope !== 'profile:contacts';
      input.setAttribute('aria-label', label); wrap.append(input, node('span', label)); scopeGroup.append(wrap); scopes.push(input);
    }
    const submit = node('button', '生成令牌', 'profile-button'); submit.type = 'submit'; form.append(scopeGroup, submit);
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (busy || !form.reportValidity()) return;
      setBusy(true); say('正在生成令牌…');
      try {
        const result = await request('/api/account/mcp/tokens', {name: name.value.trim(), expires_days: Number(days.value), scopes: scopes.filter(input => input.checked).map(input => input.value)}, 'POST');
        if (!result.token) throw new Error('未收到令牌，请刷新列表检查。');
        // Retain the only copy even if the optional list refresh fails.
        connections.tokens = [{...result, token: undefined}, ...(connections.tokens || [])];
        renderProfile(); showMcpToken(result.token); say('令牌已生成，请复制接入配置。');
      } catch (error) { say(error.message, true); }
      finally { setBusy(false); }
    });
    section.append(form, node('h3', '已有令牌'));
    if (!connections.tokens?.length) section.append(node('p', '尚未生成令牌。', 'profile-muted'));
    for (const token of connections.tokens || []) {
      const row = node('article', undefined, 'profile-card profile-token-row'); row.dataset.tokenId = token.id;
      const expired = token.expires_at && Date.parse(token.expires_at) <= Date.now();
      row.append(node('h3', token.name), node('p', (token.scopes || []).join(' · '), 'profile-muted'), node('p', '有效期至 ' + mcpLocalTime(token.expires_at)), node('p', '最后使用：' + mcpLocalTime(token.last_used_at, '尚未使用')));
      if (token.revoked_at || expired) row.append(node('strong', token.revoked_at ? '已吊销' : '已过期'));
      else row.append(button('吊销令牌', () => mutate(() => request('/api/account/mcp/tokens/' + encodeURIComponent(token.id), undefined, 'DELETE'), '令牌已吊销。')));
      section.append(row);
    }
    section.append(node('h3', '最近调用'), node('p', '最多显示最近 50 次，只记录时间、令牌、工具、耗时和结果码；服务重启后清空。', 'profile-muted'));
    const calls = node('ol', undefined, 'profile-mcp-audit');
    for (const row of connections.recent_calls || []) {
      const token = (connections.tokens || []).find(token => token.id === row.token_id);
      calls.append(node('li', mcpLocalTime(row.called_at) + ' · ' + (token?.name || '令牌') + ' · ' + row.tool + ' · ' + row.duration_ms + 'ms · ' + row.status_code));
    }
    section.append(calls); if (!calls.children.length) section.append(node('p', '尚无调用记录。', 'profile-muted'));
    content.append(section);
  }
  async function logout({returnToCurrent = false} = {}) {
    if (busy || !confirm('退出登录将清除本页未保存内容。请先确认聊天与简历已保存。')) return false;
    const destination = returnToCurrent ? location.href : '/chat';
    setBusy(true);
    try {
      await request('/api/account/logout', {}, 'POST');
      clearPrivateCache(true);
      window.dispatchEvent(new Event('huhua-account-reset'));
      location.href = destination;
      return true;
    } finally { setBusy(false); }
  }
  function renderProfile() {
    clearInterval(loginTimer); syncLoginControls = () => {}; syncConfirmationControls = () => {}; syncAccountPresentation(); content.replaceChildren(); if (!profile && profileView !== 'connections') return;
    const identity = node('div', undefined, 'profile-identity'); identity.append(node('strong', account.account?.email || '已登录'));
    if (profileView !== 'connections') identity.append(node('p', '本人唯一主档案 · ' + profile.revision + ' 次修订', 'profile-muted'));
    identity.append(button('退出登录', () => logout().catch(error => say(error.message, true)))); content.append(identity);
    if (profileView === 'connections') { renderConnections(); return; }
    const actions = node('div', undefined, 'profile-actions');
    const confirmation = button('信息确认', () => { profileView = profileView === 'confirmations' ? 'facts' : 'confirmations'; renderProfile(); });
    confirmationButton = confirmation;
    confirmation.classList.add('profile-confirm-button'); confirmation.setAttribute('aria-expanded', String(profileView === 'confirmations'));
    actions.append(confirmation, button('补充一条信息', addFact, false), button('从其他 AI 导入', importMemory), button('刷新档案', loadProfile), button('导入此浏览器旧对话', () => {
      const note = node('div', undefined, 'profile-notice'); note.append(node('p', '把此浏览器凭证下可认领的旧对话关联到当前账号，并整理其中明确的本人信息。只导入你自己的资料。'));
      note.append(button('确认导入本人旧对话', () => mutate(() => request('/api/account/claim-browser', {}, 'POST'), '已认领可导入的旧对话，整理状态见下方。')), button('取消', renderProfile)); actions.replaceChildren(note);
    })); content.append(actions);
    updateConfirmationBadge();
    const imports = profile.import_status || {};
    if (imports.pending || imports.running || imports.failed || imports.completed) {
      const notice = node('section', undefined, 'profile-notice'); notice.setAttribute('aria-label', '旧对话导入状态');
      notice.append(node('strong', `旧对话导入：${imports.pending || 0} 待导入 · ${imports.running || 0} 处理中 · ${imports.failed || 0} 失败 · ${imports.completed || 0} 已完成`));
      notice.append(node('p', imports.failed ? '部分旧对话尚未导入成功。稍后可刷新查看进度；个人档案只使用已完成整理的信息。' : '旧对话导入后会继续整理本人信息，可在下方查看档案整理进度。'));
      content.append(notice);
    }
    const state = profile.archive_status || {};
    if (state.pending || state.running || state.failed) {
      const notice = node('div', undefined, 'profile-notice'); notice.append(node('strong', `档案整理：${state.pending || 0} 待处理 · ${state.running || 0} 处理中 · ${state.failed || 0} 失败`), node('p', '聊天保存与档案整理分开进行；整理完成后可在其他对话使用。'));
      for (const task of state.tasks || []) { const row = node('p', task.message || stateNames[task.status] || '等待更新'); if (task.status === 'failed' && task.id && task.retryable !== false) row.append(button('重试整理', () => mutate(() => request('/api/profile/tasks/' + encodeURIComponent(task.id) + '/retry', {}, 'POST'), '已重新加入整理队列。'))); notice.append(row); } content.append(notice);
    }
    if (profileView === 'confirmations') {
      content.append(button('返回已有信息', () => { profileView = 'facts'; renderProfile(); }));
      content.append(node('h2', '待确认信息', 'profile-section-title'));
      renderConfirmations();
      return;
    }
    content.append(node('h2', '已有信息', 'profile-section-title'));
    if (profile.memory_imports?.length) {
      const imports = node('details', undefined, 'profile-source profile-import-history'); imports.append(node('summary', '其他 AI 导入记录'));
      for (const batch of profile.memory_imports) {
        const row = node('div', undefined, 'profile-notice'); row.dataset.importBatchId = batch.id;
        row.append(node('p', `${batch.recorded_at} · 新写入 ${batch.added_count} 条`),
          button('撤销这次导入', () => undoMemoryImport(batch.id))); imports.append(row);
      }
      content.append(imports);
    }
    for (const update of profile.updates || []) {
      const notice = node('div', undefined, 'profile-notice');
      notice.append(node('strong', '已更新 · ' + update.subject + ' · ' + (fieldNames[update.field] || update.field)), node('p', factValue({value: update.previous_value, proficiency: update.previous_proficiency}) + ' → ' + factValue(update)));
      notice.append(button('撤销更新', () => mutate(() => request('/api/profile/facts/' + encodeURIComponent(update.fact_id) + '/undo-update', {expected_revision: update.revision}, 'POST'), '已撤销这次自动更新。')));
      content.append(notice);
    }
    const facts = profile.facts || []; if (!facts.length) content.append(node('p', '还没有已整理的信息。你可以直接补充，或在聊天中介绍自己的经历。', 'profile-muted'));
    renderFactGroups([...facts, ...(profile.preferences || [])]);
    const currentSession = currentProfileSession();
    if (currentSession) {
      const create = button('保存当前岗位版本', () => {
        if (focusInlineForm(content, 'job')) return;
        const form = node('form', undefined, 'profile-card profile-form'); form.dataset.profileForm = 'job'; const name = inputField(form, '岗位版本名称'); const save = node('button', '保存岗位版本', 'profile-button'); save.type = 'submit'; form.append(save, button('取消', renderProfile));
        form.addEventListener('submit', event => { event.preventDefault(); if (form.reportValidity()) mutate(() => request('/api/profile/jobs', {session_id: currentSession, name: name.value.trim()}, 'POST'), '已保存岗位版本。'); }); content.prepend(form); name.focus();
        create.setAttribute('aria-expanded', 'true');
      }); create.setAttribute('aria-expanded', 'false'); content.append(create);
    }
    if (profile.jobs?.length) {
      content.append(node('h2', '岗位简历', 'profile-section-title'));
      for (const job of profile.jobs) { const row = node('article', undefined, 'profile-card'); row.append(node('h3', job.name || '未命名岗位'), node('p', job.stale ? '档案已有更正，请在该对话核对并同步。' : '当前引用未标记待同步。', job.stale ? 'profile-eyebrow' : 'profile-muted')); const link = node('a', '打开岗位对话'); link.href = '/chat?session=' + encodeURIComponent(job.session_id); const rename = button('改名', () => {
        if (focusInlineForm(row, 'name')) return;
        const form = node('form', undefined, 'profile-form'); form.dataset.profileForm = 'name'; const name = inputField(form, '岗位版本名称', job.name); const save = node('button', '保存名称', 'profile-button'); save.type = 'submit'; form.append(save, button('取消', renderProfile)); form.addEventListener('submit', event => { event.preventDefault(); if (form.reportValidity()) mutate(() => request('/api/profile/jobs/' + encodeURIComponent(job.id), {name: name.value.trim(), expected_revision: job.revision}, 'PATCH'), '名称已更新。'); }); row.append(form); name.focus(); rename.setAttribute('aria-expanded', 'true');
      }); rename.setAttribute('aria-expanded', 'false'); row.append(link, rename); content.append(row); }
    }
    content.append(node('p', '档案属于当前账号。这里的“用户提供”不表示已经独立核实；AI 建议和 JD 不作为本人事实。', 'profile-muted'));
  }
  async function loadProfile() {
    const version = ++loadVersion, connecting = profileView === 'connections';
    say(connecting ? '正在读取 AI 助手连接…' : '正在读取个人档案…');
    try {
      if (connecting) {
        const tokens = await request('/api/account/mcp/tokens');
        if (version !== loadVersion) return;
        connections = tokens;
      } else {
        const [value, suggestions] = await Promise.all([request('/api/profile'), request('/api/account/mcp/inbox')]);
        if (version !== loadVersion) return;
        profile = value; inbox = suggestions;
      }
      renderProfile(); say(connecting ? '已读取 AI 助手连接。' : '已读取最新档案。');
    }
    catch (error) { if (version === loadVersion) { if (error.status === 401) { account.authenticated = false; profile = null; renderLogin(); } say(error.message, true); } }
  }
  function mount() {
    opener = document.getElementById('btn-account-profile'); if (!opener) return;
    overlay = node('div'); overlay.id = 'profile-overlay'; overlay.hidden = true;
    const backdrop = button('关闭个人档案', close); backdrop.className = 'profile-backdrop'; backdrop.tabIndex = -1;
    const drawer = node('aside'); drawer.id = 'profile-drawer'; drawer.setAttribute('role', 'dialog'); drawer.setAttribute('aria-modal', 'true'); drawer.setAttribute('aria-labelledby', 'profile-heading');
    const head = node('header'); const title = node('h1', '登录账号'); title.id = 'profile-heading'; const dismiss = button('关闭', close); dismiss.id = 'btn-close-profile'; head.append(title, dismiss);
    status = node('p', '', 'profile-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); content = node('div'); content.id = 'profile-content'; drawer.append(head, status, content); overlay.append(backdrop, drawer); document.body.append(overlay);
    opener.setAttribute('aria-controls', 'profile-drawer'); opener.addEventListener('click', () => open());
    document.addEventListener('keydown', event => {
      if (overlay.hidden) return;
      if (event.key === 'Escape') { close(); return; }
      if (event.key !== 'Tab') return;
      const focusables = [...drawer.querySelectorAll('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],summary')].filter(n => n.getClientRects().length);
      if (!drawer.contains(document.activeElement)) { event.preventDefault(); focusables[0]?.focus(); }
      else if (event.shiftKey && document.activeElement === focusables[0]) { event.preventDefault(); focusables.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === focusables.at(-1)) { event.preventDefault(); focusables[0]?.focus(); }
    });
    syncAccountPresentation(); ready.then(() => {
      syncAccountPresentation();
      if (account.authenticated && new URLSearchParams(location.search).get('profile') === 'inbox') open();
      if (pendingClaim) {
        document.querySelectorAll('main').forEach(main => { main.inert = true; });
        window.dispatchEvent(new Event('huhua-account-claim-pending'));
        open();
      }
    });
  }
  window.HuhuaAccount = {ready, logout, clearPrivateCache, refreshAccount, authenticated: () => Boolean(account.authenticated && !pendingClaim), guest: isGuest, claimPending: () => Boolean(pendingClaim), guestNotice, rememberedSession, rememberSession, requireLogin, requiresLogin: () => Boolean(account.require_account && (!account.authenticated || pendingClaim)), refreshIfOpen: () => { if (overlay && !overlay.hidden && account.authenticated && !busy) { if (content.querySelector('form')) say('聊天已保存。完成当前填写后可刷新档案，查看整理进度。'); else loadProfile(); } }, open};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
})();
