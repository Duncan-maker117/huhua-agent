(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const endpoint = '/api/chat/conversations';
  const overlay = $('conversation-overlay');
  const drawer = $('conversation-drawer');
  const list = $('conversation-list');
  const resumeLinks = [...document.querySelectorAll('a[href="/resume"], #btn-open-full')];
  const initialTarget = new URLSearchParams(location.search).get('session');
  const drafts = new Map();
  let conversations = [];
  let switchRequest = 0;
  let listRequest = 0;
  let creating = false;
  let deleting = false;
  let retryAction = null;
  let activeTitle = '新对话';
  const backupButton = document.createElement('button');
  backupButton.id = 'btn-chat-backup';
  backupButton.type = 'button';
  backupButton.textContent = '下载本页恢复稿';
  backupButton.hidden = true;
  $('conversation-bar').append(backupButton);

  function removeLocal(key) { try { localStorage.removeItem(key); } catch (_) { /* Storage may be blocked. */ } }
  function backupFor(id) { return chatBackups.get(id) || []; }
  function setStatus(message, error = false, retry = null) {
    $('conversation-status').textContent = message;
    $('conversation-status').classList.toggle('error', error);
    retryAction = retry;
    $('btn-history-retry').hidden = !retry;
    backupButton.hidden = !SESSION_ID || (!chatRecoveries.has(SESSION_ID) && (!error || !backupFor(SESSION_ID).length));
  }
  function setBusy(busy) {
    conversationBusy = busy;
    inputEl.disabled = busy;
    sendBtn.disabled = busy || !conversationReady;
    $('btn-new-chat').disabled = busy;
    $('btn-history-new').disabled = busy;
    updateFlowActions();
  }
  function closeDrawer() {
    overlay.hidden = true;
    $('btn-history').setAttribute('aria-expanded', 'false');
    $('btn-history').focus();
  }
  function showDrawer() {
    if (window.HuhuaAccount?.requireLogin('登录后保留当前对话，并从历史对话继续修改简历。')) return;
    overlay.hidden = false;
    $('btn-history').setAttribute('aria-expanded', 'true');
    drawer.focus();
    refreshList().catch(() => {});
  }
  function canNavigate() {
    if (creating || deleting || window.HuhuaAccount?.claimPending()) return false;
    if (currentController) { setStatus('请先点击停止，结束当前生成后再切换对话。'); return false; }
    if (pendingUploads) { setStatus('附件还在上传，请等待上传完成后再切换。'); return false; }
    return true;
  }
  async function request(url, options = {}) {
    let response;
    try { response = await fetch(url, options); }
    catch (_) { throw new Error('连接已断开，请确认服务运行后重试。'); }
    let body;
    try { body = await response.json(); } catch (_) { body = {}; }
    if (!response.ok) {
      const detail = body.detail;
      const error = new Error(typeof detail === 'string' ? detail : detail?.message || `暂时无法读取对话（${response.status}）`);
      error.status = response.status;
      throw error;
    }
    return body;
  }
  function renderMessages() {
    messagesEl.replaceChildren();
    emptyStateEl.classList.toggle('hidden', messages.length > 0);
    messagesEl.classList.toggle('hidden', messages.length === 0);
    for (const message of messages) {
      // Keep uploaded material readable when there was no separate typed text.
      const display = message.role === 'user' && message.content.includes('\n\n---\n\n')
        ? message.content.split('\n\n---\n\n').at(-1) : message.content;
      appendBubble(message.role, display, message.interrupted === true);
    }
  }
  function resetCanvas() {
    canvasReadRequest++;
    canvasPaintRequest++;
    canvasState.data = null;
    canvasState.hasData = false;
    canvasState.stage = 'JD_INPUT';
    canvasState.versionId = undefined;
    canvasState.highlight = null;
    window.HuhuaChangeCard?.reset();
    resetGenerateLink();
    $('verification-panel').classList.add('hidden');
    $('canvas-empty').classList.remove('hidden');
    $('canvas-sheet-wrap').classList.add('hidden');
    $('live-sheet').srcdoc = '';
    $('btn-export-docx').disabled = true;
    window.HuhuaWorkspace?.reset();
    renderStageRail();
  }
  function rememberDraft() {
    if (SESSION_ID) drafts.set(SESSION_ID, {text: inputEl.value, attachments: [...attachments]});
  }
  function activate(body) {
    rememberDraft();
    resetCanvas();
    SESSION_ID = body.session_id;
    activeTitle = body.title || '新对话';
    $('conversation-title').textContent = activeTitle;
    $('conversation-title').title = activeTitle;
    const recovered = (body.messages || []).filter(m => m && ['user', 'assistant'].includes(m.role) && typeof m.content === 'string');
    const previous = backupFor(SESSION_ID);
    const sameMessage = (a, b) => a?.role === b?.role && a?.content === b?.content;
    const matchingPrefix = recovered.every((m, index) => sameMessage(m, previous[index]));
    const partial = previous.at(-1);
    const recoverInterrupted = recovered.at(-1)?.role === 'user' && previous.length === recovered.length + 1 && matchingPrefix && partial?.role === 'assistant' && partial.interrupted === true;
    if (recoverInterrupted) recovered.push({...partial});
    const different = previous.length && previous.length >= recovered.length && !(previous.length === recovered.length && recovered.every((m, index) => sameMessage(m, previous[index])));
    if (different || recoverInterrupted) {
      chatRecoveries.set(SESSION_ID, previous);
    }
    messages.splice(0, messages.length, ...recovered);
    saveMessages();
    if (!different && !recoverInterrupted) unsavedChatSessions.delete(SESSION_ID);
    conversationReady = true;
    resetSelectedTask();
    clearAttachments();
    const draft = drafts.get(SESSION_ID);
    inputEl.value = draft?.text || '';
    if (draft?.attachments) { attachments.push(...draft.attachments); renderAttachments(); }
    autoResize();
    renderMessages();
    const url = new URL(location.href);
    url.searchParams.set('session', SESSION_ID);
    history.replaceState(null, '', url.pathname + url.search + url.hash);
    for (const link of resumeLinks) link.href = `/resume?session=${encodeURIComponent(SESSION_ID)}`;
    canvasState.stage = body.stage || 'JD_INPUT';
    if (body.workspace) window.HuhuaWorkspace?.update(body.workspace, {focus: true});
    renderStageRail();
    renderList();
    if (recoverInterrupted) setStatus('已恢复本页中断片段；该片段尚未保存到数据库，可下载备份。', true);
    else if (different || chatRecoveries.has(SESSION_ID)) setStatus('已读取保存的对话，另有本页恢复稿可下载核对。');
    else setStatus(window.HuhuaAccount?.guest() ? window.HuhuaAccount.guestNotice() : messages.length ? '已读取保存的对话，可继续修改。' : '新对话已创建，资料将独立保存。');
  }
  async function openConversation(id, options = {}) {
    if (!canNavigate()) return false;
    const turn = ++switchRequest;
    setBusy(true);
    setStatus('正在读取对话及简历…');
    try {
      const body = await request(`${endpoint}/${encodeURIComponent(id)}`);
      if (turn !== switchRequest) return false;
      if (body.session_id !== id || !Array.isArray(body.messages)) throw new Error('对话内容未完整返回，请重试。');
      activate(body);
      if (options.close !== false) closeDrawer();
      return true;
    } catch (error) {
      if (turn !== switchRequest) return false;
      setStatus(error.message + (conversationReady ? ' 当前对话仍保留。' : ' 请重试或新建对话。'), true, () => openConversation(id, options));
      if (!conversationReady && window.HuhuaAccount?.guest() && [401, 403, 404].includes(error.status)) { await createConversation(); return conversationReady; }
      return false;
    } finally {
      if (turn === switchRequest) {
        setBusy(false);
        if (conversationReady) refreshCanvas();
      }
    }
  }
  function renderList() {
    list.replaceChildren();
    for (const item of conversations) {
      const row = document.createElement('div');
      row.className = 'conversation-item' + (item.session_id === SESSION_ID ? ' active' : '');
      row.dataset.sessionId = item.session_id;
      const open = document.createElement('button');
      open.type = 'button';
      open.className = 'conversation-open';
      open.setAttribute('aria-current', item.session_id === SESSION_ID ? 'true' : 'false');
      const name = document.createElement('span');
      name.className = 'conversation-name';
      name.textContent = item.title || '新对话';
      name.title = name.textContent;
      const meta = document.createElement('span');
      meta.className = 'conversation-meta';
      const date = item.updated_at ? new Date(item.updated_at) : null;
      const dateText = date && !Number.isNaN(date.valueOf()) ? date.toLocaleString('zh-CN', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '';
      meta.textContent = [dateText, item.has_data ? '已有简历' : '整理资料中'].filter(Boolean).join(' · ');
      open.append(name, meta);
      open.addEventListener('click', () => openConversation(item.session_id));
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'conversation-delete';
      remove.textContent = '删除';
      remove.setAttribute('aria-label', `删除对话：${item.title || '新对话'}`);
      remove.addEventListener('click', () => deleteConversation(item, remove));
      row.append(open, remove);
      list.append(row);
    }
  }
  async function refreshList() {
    if (window.HuhuaAccount?.guest()) { conversations = []; renderList(); return; }
    const token = ++listRequest;
    $('history-list-status').textContent = '正在读取历史…';
    $('history-list-status').classList.remove('error');
    try {
      const body = await request(endpoint);
      if (token !== listRequest) return;
      if (!Array.isArray(body.conversations)) throw new Error('历史列表未完整返回，请重试。');
      conversations = body.conversations.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
      renderList();
      $('history-list-status').textContent = conversations.length ? '' : '还没有保存的对话。';
      $('history-retention').textContent = body.retention_days > 0
        ? `对话在最后更新 ${body.retention_days} 天后自动清理。`
        : window.HuhuaAccount?.authenticated() ? '聊天保存在你的账号下，可手动删除；个人档案独立管理。' : '对话保存在数据库中；未登录时由此浏览器识别，清除 Cookie 后无法访问历史。';
    } catch (error) {
      if (token !== listRequest) return;
      $('history-list-status').textContent = error.message;
      $('history-list-status').classList.add('error');
      throw error;
    }
  }
  async function createConversation() {
    if (creating || !canNavigate()) return false;
    creating = true;
    const turn = ++switchRequest;
    setBusy(true);
    setStatus('正在创建新对话…');
    try {
      const body = await request(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
      if (turn !== switchRequest) return false;
      if (!body.session_id) throw new Error('新对话尚未创建，请重试。');
      activate({...body, messages: []});
      closeDrawer();
      await refreshList().catch(() => {});
      return true;
    } catch (error) {
      if (turn === switchRequest) setStatus(error.message + ' 原对话仍保留。', true, createConversation);
      return false;
    } finally {
      creating = false;
      if (turn === switchRequest) { setBusy(false); inputEl.focus(); }
    }
  }
  async function deleteConversation(item, button) {
    if (!canNavigate() || conversationBusy) return;
    if (!confirm(`删除「${item.title || '新对话'}」？该对话的聊天、岗位资料和简历将一并删除，无法恢复。已归档的个人事实会保留，可在个人档案中单独删除。`)) return;
    deleting = true;
    setBusy(true);
    button.disabled = true;
    const deletingActive = item.session_id === SESSION_ID;
    try {
      await request(`/api/chat/session/${encodeURIComponent(item.session_id)}`, {method: 'DELETE'});
      for (const prefix of ['huhua_chat_backup:', 'huhua_chat_recovery:']) removeLocal(prefix + item.session_id);
      try { sessionStorage.removeItem('huhua_editor_draft:' + item.session_id); } catch (_) { /* Storage may be blocked. */ }
      unsavedChatSessions.delete(item.session_id);
      chatBackups.delete(item.session_id);
      chatRecoveries.delete(item.session_id);
      drafts.delete(item.session_id);
      conversations = conversations.filter(value => value.session_id !== item.session_id);
      deleting = false;
      if (deletingActive) {
        ++switchRequest;
        SESSION_ID = null;
        conversationReady = false;
        messages.length = 0;
        for (const key of [SESSION_KEY, MSG_KEY, SAVED_AT_KEY]) removeLocal(key);
        inputEl.value = '';
        clearAttachments();
        resetCanvas();
        renderMessages();
        $('conversation-title').textContent = '对话已删除';
        history.replaceState(null, '', location.pathname);
        setBusy(false);
        if (conversations[0]) await openConversation(conversations[0].session_id, {close: false});
        else await createConversation();
      }
      renderList();
      await refreshList().catch(() => {});
    } catch (error) { setStatus(`删除失败：${error.message}`, true); }
    finally { deleting = false; button.disabled = false; setBusy(false); }
  }
  async function afterTurn() {
    const id = SESSION_ID;
    const expected = messages.at(-1)?.content;
    try {
      const body = await request(`${endpoint}/${encodeURIComponent(id)}`);
      if (id !== SESSION_ID || currentController) return;
      if (body.workspace) window.HuhuaWorkspace?.update(body.workspace);
      activeTitle = body.title || activeTitle;
      $('conversation-title').textContent = activeTitle;
      $('conversation-title').title = activeTitle;
      const last = body.messages?.at(-1);
      if (last?.role === 'assistant' && last.content === expected) { unsavedChatSessions.delete(id); setStatus(window.HuhuaAccount?.guest() ? window.HuhuaAccount.guestNotice() : '已保存，可从历史对话继续。'); }
      else setStatus('本轮回复可能未完整保存，未保存内容仅留在本页，关闭或刷新前请下载恢复稿。', true, afterTurn);
    } catch (error) {
      if (id === SESSION_ID) setStatus('暂时无法确认保存，未保存内容仅留在本页，关闭或刷新前请下载恢复稿。' + error.message, true, afterTurn);
    }
    await refreshList().catch(() => {});
    window.HuhuaAccount?.refreshIfOpen();
  }
  async function initialise() {
    const token = ++switchRequest;
    setBusy(true);
    // Render an available recovery copy while waiting, but never claim it is saved.
    renderMessages();

    try {
      await window.HuhuaAccount?.ready;
      if (window.HuhuaAccount?.claimPending()) { setStatus('当前体验待保存到账号，请重试保留当前对话。'); return; }
      if (window.HuhuaAccount?.requiresLogin() && !window.HuhuaAccount?.guest()) {
        setStatus('请先登录，登录后读取本人的聊天与档案。');
        return;
      }
      await refreshList();
      if (token !== switchRequest) return;
      const target = initialTarget || window.HuhuaAccount?.rememberedSession() || (!window.HuhuaAccount?.guest() ? LEGACY_SESSION_ID || conversations[0]?.session_id : null);
      if (target) await openConversation(target, {close: false});
      else await createConversation();
    } catch (error) {
      if (token !== switchRequest) return;
      setStatus(error.message + ' 请重试；未保存内容仅留在当前页面。', true, initialise);
    } finally {
      if (token === switchRequest) setBusy(Boolean(window.HuhuaAccount?.claimPending()));
    }
  }

  $('btn-history').addEventListener('click', showDrawer);
  $('btn-close-history').addEventListener('click', closeDrawer);
  $('conversation-backdrop').addEventListener('click', closeDrawer);
  $('btn-new-chat').addEventListener('click', createConversation);
  $('btn-history-new').addEventListener('click', createConversation);
  $('btn-refresh-history').addEventListener('click', () => refreshList().catch(() => {}));
  $('btn-history-retry').addEventListener('click', () => retryAction?.());
  overlay.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeDrawer();
    if (event.key !== 'Tab') return;
    const buttons = [...drawer.querySelectorAll('button:not(:disabled)')];
    if (event.shiftKey && (document.activeElement === buttons[0] || document.activeElement === drawer)) { event.preventDefault(); buttons.at(-1)?.focus(); }
    else if (!event.shiftKey && document.activeElement === buttons.at(-1)) { event.preventDefault(); buttons[0]?.focus(); }
  });
  backupButton.addEventListener('click', () => {
    if (window.HuhuaAccount?.requireLogin('登录后可下载恢复稿，并保留当前对话。')) return;
    const content = {session_id: SESSION_ID, title: activeTitle, messages: chatRecoveries.get(SESSION_ID) || backupFor(SESSION_ID)};
    const url = URL.createObjectURL(new Blob([JSON.stringify(content, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = url; link.download = '对话-本页恢复稿.json';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  window.HuhuaHistory = {
    afterTurn,
    prepareLogin: async () => !currentController && !pendingUploads,
    showConnectionProblem: () => setStatus(conversationBusy ? '正在读取对话，请稍候。' : '尚未连接可保存的对话，请重试或新建对话。', !conversationBusy, conversationBusy ? null : initialise),
  };
  window.addEventListener('huhua-account-claim-pending', () => {
    setBusy(true); setStatus('登录已成功，当前体验待保存；请在登录窗口重试保留当前对话。');
  });
  window.addEventListener('huhua-account-changed', () => {
    setBusy(false);
    if (SESSION_ID) window.HuhuaAccount?.rememberSession(SESSION_ID);
    setStatus('已登录，当前对话已保留；可以继续聊天或导出简历。');
    refreshList().catch(() => {});
    if (!conversationReady) initialise();
  });
  initialise();
})();
