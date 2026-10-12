/* Keep the chat mounted while the session's editor and downloads are in use. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const overlay = $('resume-editor-overlay');
  let callbacks = {}, session = null, hasData = false, revision = null;
  let frame = null, ready = false, idle = null, returnFocus = null, wasInert = false;
  let exportRequest = null, exportObjectUrl = null;

  function renderActions() {
    $('btn-edit-resume').disabled = !hasData;
    for (const format of ['pdf', 'docx']) {
      const button = $('btn-export-' + format);
      button.disabled = !hasData || Boolean(exportRequest);
      button.textContent = exportRequest?.format === format ? '正在生成…' : '下载 ' + (format === 'pdf' ? 'PDF' : 'Word');
    }
    for (const id of ['btn-edit-resume', 'btn-export-pdf', 'btn-export-docx']) $(id).title = hasData ? '' : '先生成简历';
    $('resume-actions-hint').textContent = !hasData ? '先生成简历' : window.HuhuaAccount?.guest()
      ? '登录后即可下载，并保留这份简历与对话。' : 'PDF 使用当前所选模板；下载前请核对内容。';
  }
  function post(message) {
    if (ready) frame?.contentWindow?.postMessage(message, location.origin);
  }
  function cancelPreload() {
    if (idle === null) return;
    if (window.requestIdleCallback) window.cancelIdleCallback(idle);
    else clearTimeout(idle);
    idle = null;
  }
  function ensureFrame() {
    cancelPreload();
    if (frame || !hasData || !session) return;
    frame = document.createElement('iframe');
    frame.id = 'resume-editor-frame'; frame.title = '简历精细编辑';
    frame.src = '/resume?session_id=' + encodeURIComponent(session) + '&embedded=1';
    $('resume-editor-loading').hidden = false;
    overlay.append(frame);
  }
  function preload() {
    if (!hasData || !session || frame || idle !== null) return;
    const target = session;
    const load = () => { idle = null; if (session === target) ensureFrame(); };
    idle = window.requestIdleCallback ? window.requestIdleCallback(load, {timeout: 2000}) : setTimeout(load, 500);
  }
  function open() {
    if (!hasData) return;
    ensureFrame();
    if (!frame) return;
    if (overlay.hidden) {
      returnFocus = document.activeElement; wasInert = document.querySelector('main').inert;
      document.querySelector('main').inert = true;
    }
    overlay.hidden = false;
    frame.focus();
    post({type: 'resume-editor-open', template: callbacks.template?.()});
  }
  function close() {
    if (overlay.hidden) return;
    overlay.hidden = true;
    document.querySelector('main').inert = wasInert;
    returnFocus?.focus({preventScroll: true});
  }
  function clearExport() {
    if (exportObjectUrl) URL.revokeObjectURL(exportObjectUrl);
    exportObjectUrl = null;
    $('workspace-export-result').hidden = true;
    for (const id of ['workspace-export-download', 'workspace-export-open']) { $(id).hidden = true; $(id).removeAttribute('href'); }
  }
  function reset() {
    cancelPreload(); close(); frame?.remove(); frame = null; ready = false;
    session = null; revision = null; hasData = false;
    exportRequest?.controller.abort(); exportRequest = null; clearExport(); renderActions();
  }
  function sync(body) {
    const currentSession = callbacks.session?.();
    if (session !== currentSession) { reset(); session = currentSession; }
    hasData = Boolean(body.has_data && body.data);
    const changed = revision !== body.revision;
    revision = body.revision;
    renderActions();
    if (hasData) { preload(); if (changed) post({type: 'resume-refresh', revision}); }
    else { cancelPreload(); close(); frame?.remove(); frame = null; ready = false; }
  }
  function exportStatus(message, error = false) {
    $('workspace-export-result').hidden = false;
    $('workspace-export-result').classList.toggle('error', error);
    $('workspace-export-status').textContent = message;
  }
  // Match the standalone editor's login gate, deadline, validation and errors.
  async function exportResume(format) {
    if (!hasData || exportRequest) return;
    if (window.HuhuaAccount?.requireLogin('登录后即可导出这份简历，同时保留当前对话和个人信息。')) return;
    const request = {session, format, template: callbacks.template?.(), controller: new AbortController()};
    exportRequest = request;
    const label = format === 'pdf' ? 'PDF' : 'Word';
    clearExport(); renderActions(); exportStatus('正在生成 ' + label + '…');
    let timer;
    try {
      if (!await callbacks.refresh?.()) throw new Error('暂时无法读取最新简历，请重试。');
      if (exportRequest !== request) return;
      const data = callbacks.data?.();
      if (!data) throw new Error('先生成简历');
      timer = setTimeout(() => request.controller.abort(), 60000);
      const response = await fetch(`/api/resume/export/${format}/${encodeURIComponent(request.template)}?session_id=${encodeURIComponent(request.session)}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data), signal: request.controller.signal,
      });
      if (!response.ok) {
        let detail;
        try { detail = (await response.json()).detail; } catch (error) { if (error.name === 'AbortError') throw error; }
        throw new Error(typeof detail === 'string' ? detail : detail?.message || '导出失败，请稍后重试');
      }
      const blob = await response.blob();
      const signature = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
      if (exportRequest !== request) return;
      const valid = format === 'pdf' ? new TextDecoder().decode(signature) === '%PDF-' : signature[0] === 80 && signature[1] === 75 && signature[2] === 3 && signature[3] === 4;
      if (!valid) throw new Error(label + ' 文件内容异常，请重试；当前简历仍已保存。');
      let filename = format === 'pdf' ? '简历.pdf' : '简历-通用Word.docx';
      const match = (response.headers.get('Content-Disposition') || '').match(/filename\*=UTF-8''([^;]+)/i);
      if (match) { try { filename = decodeURIComponent(match[1]).replace(/[\x00-\x1f/\\]/g, '_'); } catch (_) { /* Use default filename. */ } }
      exportObjectUrl = URL.createObjectURL(blob);
      const link = $('workspace-export-download');
      link.href = exportObjectUrl; link.download = filename; link.textContent = '下载 ' + label; link.hidden = false;
      $('workspace-export-open').href = exportObjectUrl; $('workspace-export-open').hidden = false;
      exportStatus(label + ' 文件已生成。若未出现下载，请点击下方下载，或打开文件后保存。后续修改需重新导出。');
      link.click();
    } catch (error) {
      if (exportRequest !== request) return;
      exportStatus(error.name === 'AbortError' ? '导出等待超时，已保存的简历仍在。请重试或选择另一种格式。' : error.message.includes('fetch') ? '连接已断开，下载未完成。请检查网络后重试。' : error.message, true);
    } finally {
      clearTimeout(timer);
      if (exportRequest === request) { exportRequest = null; renderActions(); }
    }
  }
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || !frame || event.source !== frame.contentWindow || session !== callbacks.session?.()) return;
    const message = event.data;
    if (!message || typeof message !== 'object') return;
    if (message.type === 'resume-editor-ready') {
      ready = true;
      $('resume-editor-loading').hidden = true;
      post({type: 'resume-account-changed'});
      if (revision && revision !== message.revision) post({type: 'resume-refresh', revision});
      if (!overlay.hidden) post({type: 'resume-editor-open', template: callbacks.template?.()});
    } else if (message.type === 'resume-editor-close') close();
    else if (message.type === 'resume-saved' && typeof message.revision === 'string') callbacks.refresh?.();
    else if (message.type === 'resume-account-changed') window.HuhuaAccount?.refreshAccount().then(renderActions).catch(() => {});
  });
  window.addEventListener('huhua-account-reset', reset);
  window.addEventListener('huhua-account-changed', () => { renderActions(); post({type: 'resume-account-changed'}); });
  window.addEventListener('pagehide', event => { if (!event.persisted) clearExport(); });
  window.HuhuaResumeActions = {
    init(options) {
      callbacks = options; renderActions();
      $('btn-edit-resume').addEventListener('click', open);
      $('btn-cancel-editor-load').addEventListener('click', close);
      for (const format of ['pdf', 'docx']) $('btn-export-' + format).addEventListener('click', () => exportResume(format));
    },
    reset, sync, open,
    focusDownload() {
      requestAnimationFrame(() => {
        const button = $('btn-export-pdf');
        button.scrollIntoView({block: 'nearest'});
        if (!button.disabled) button.focus({preventScroll: true});
      });
    },
  };
})();
