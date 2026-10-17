/* Explicit, narrow web requests. Composer drafts and attachments are never used as search terms. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let callbacks = {}, active = '', busy = false;
  let capabilities = {read_url:false, search:false}, capabilityError = '';
  const toolNotices = {
    read_url: '读取成功后，此链接会替换当前目标 JD。工具开始执行后，即使失败也计入尝试次数。',
    search: '仅基于搜索结果摘要分析，不逐个读取网页全文，也不替换当前目标 JD。工具开始执行后，即使失败也计入尝试次数。',
  };
  function syncUsageNotice() {
    const notice = $('web-tool-usage-notice');
    if (notice) { notice.textContent = toolNotices[active] || ''; notice.hidden = !active || !capabilities[active]; }
    const direct = $('web-direct-link-notice');
    if (direct) {
      const url = safeUrl(callbacks.input?.());
      direct.hidden = busy || !capabilities.read_url || !url;
      direct.textContent = url && isGitHub(url)
        ? '发送后读取此 GitHub 公开资料，用于核对；不会替换目标 JD。工具开始执行后计入尝试次数。'
        : '单独发送此链接（不带附件），读取成功后会替换当前目标 JD；工具开始执行后，即使失败也计入尝试次数。';
    }
  }
  const safeUrl = value => {
    if (typeof value !== 'string') return null;
    value = value.trim();
    if (/^(?:www\.)?github\.com\/\S+$/i.test(value)) value = 'https://' + value;
    if (!/^https?:\/\/\S+$/i.test(value)) return null;
    try {
      const url = new URL(value.trim());
      return ['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password ? url.href : null;
    } catch (_) { return null; }
  };
  const isGitHub = url => /^(?:www\.)?github\.com$/i.test(new URL(url).hostname);
  const say = (message, error = false) => {
    $('web-research-status').textContent = message;
    $('web-research-status').classList.toggle('error', error);
  };
  function sync() {
    if (active && !capabilities[active]) active = '';
    $('web-read-toggle').setAttribute('aria-expanded', String(active === 'read_url'));
    $('web-search-toggle').setAttribute('aria-expanded', String(active === 'search'));
    $('web-read-panel').hidden = active !== 'read_url';
    $('web-search-panel').hidden = active !== 'search';
    $('web-research-panel').hidden = !active;
    $('web-read-submit').disabled = busy || !capabilities.read_url;
    $('web-search-submit').disabled = busy || !capabilities.search;
    $('web-read-toggle').hidden = !capabilities.read_url;
    $('web-search-toggle').hidden = !capabilities.search;
    $('web-search-toggle').textContent = '查公司岗位';
    if ($('web-tool-actions')) $('web-tool-actions').hidden = !capabilities.read_url && !capabilities.search;
    for (const id of ['web-read-url', 'web-search-company', 'web-search-role']) $(id).disabled = busy;
    syncUsageNotice();
  }
  function open(action, tool = null) {
    active = active === action && !tool ? '' : action;
    if (action === 'read_url' && active) {
      const source = tool?.url || safeUrl(callbacks.input?.());
      if (source) $('web-read-url').value = source;
    }
    if (action === 'search' && tool) {
      $('web-search-company').value = tool.company || '';
      $('web-search-role').value = tool.role || '';
    }
    sync();
    if (!active) return;
    if (capabilityError) say(capabilityError, true);
    else if (!capabilities[active]) say(active === 'search' ? '公司岗位搜索尚未开通。可以粘贴招聘原文、读取已有招聘链接，或上传截图。' : '链接读取暂不可用。请粘贴招聘原文，或上传截图。', true);
    else say(active === 'search' ? '只将这里填写的公司、岗位关键词发给搜索服务，不发送简历或对话全文。' : '只读取你提交的链接。网页内容作为岗位参考，不会当作你的本人经历。');
    if (!busy) $(action === 'search' ? 'web-search-company' : 'web-read-url').focus();
  }
  async function submit(action) {
    if (busy || callbacks.busy?.() || !capabilities[action]) return;
    let tool, prompt;
    if (action === 'read_url') {
      if (!$('web-read-panel').reportValidity()) return;
      const url = safeUrl($('web-read-url').value);
      if (!url) { say('请填写一个完整的 http:// 或 https:// 招聘链接，不要混入个人资料。', true); return; }
      tool = {action, url}; prompt = '请读取这个招聘链接，并解读岗位要求：' + url;
    } else {
      if (!$('web-search-panel').reportValidity()) return;
      const company = $('web-search-company').value.trim(), role = $('web-search-role').value.trim();
      if (!company && !role) { say('请至少填写公司名称或岗位关键词。', true); return; }
      tool = {action, company, role}; prompt = `请搜索 ${[company, role].filter(Boolean).join(' ')} 的招聘信息，区分招聘原文和搜索摘要。`;
    }
    busy = true; sync(); say(action === 'search' ? '正在搜索公司岗位…' : '正在读取招聘链接…');
    try {
      const complete = await callbacks.send?.(prompt, {webTool:tool, keepDraft:true});
      if (complete) say(action === 'search' ? '基于搜索摘要的分析已完成。请在右侧「读岗位」核对来源原页。' : '本轮处理完成。当前目标 JD 及来源可在右侧「读岗位」查看。');
      else say('本轮未完成，填写内容已保留；重试会发起一次新尝试，也可以粘贴 JD 或上传截图。', true);
    } catch (_) { say('连接中断，填写内容已保留；重试会发起一次新尝试，也可以粘贴 JD 或上传截图。', true); }
    finally { busy = false; sync(); }
  }
  async function loadCapabilities() {
    try {
      const response = await fetch('/api/chat/tools');
      if (!response.ok) throw new Error('unavailable');
      const value = await response.json();
      capabilities = {read_url:value.read_url === true, search:value.search === true}; capabilityError = '';
    } catch (_) {
      capabilities = {read_url:false, search:false};
      capabilityError = '暂时无法连接网页工具。请粘贴 JD 原文或上传截图，稍后可重新检查。';
    }
    sync();
    if (active) {
      const mode = active; active = ''; open(mode);
    }
  }
  function init(options = {}) {
    callbacks = options;
    const notice = document.createElement('p'); notice.id = 'web-tool-usage-notice'; notice.className = 'web-tool-usage-notice'; notice.hidden = true;
    $('web-research-panel').querySelector('.web-research-heading').after(notice);
    const direct = document.createElement('p'); direct.id = 'web-direct-link-notice'; direct.className = 'web-tool-usage-notice web-direct-link-notice'; direct.hidden = true;
    direct.textContent = '单独发送此链接（不带附件），读取成功后会替换当前目标 JD；工具开始执行后，即使失败也计入尝试次数。';
    $('web-research-panel').after(direct);
    $('input')?.addEventListener('input', syncUsageNotice);
    $('web-read-toggle').addEventListener('click', () => open('read_url'));
    $('web-search-toggle').addEventListener('click', () => open('search'));
    $('web-research-close').addEventListener('click', () => { active = ''; sync(); });
    $('web-tools-retry').addEventListener('click', loadCapabilities);
    $('web-read-panel').addEventListener('submit', event => { event.preventDefault(); submit('read_url'); });
    $('web-search-panel').addEventListener('submit', event => { event.preventDefault(); submit('search'); });
    window.addEventListener('huhua-account-reset', () => {
      active = ''; for (const id of ['web-read-url','web-search-company','web-search-role']) $(id).value = ''; say(''); sync();
    });
    loadCapabilities();
  }
  window.HuhuaWebResearch = {
    init, safeUrl,
    infer(text, attachmentCount = 0) { const url = !attachmentCount && safeUrl(text); return url ? {action:isGitHub(url) ? 'read_public_url' : 'read_url',url} : null; },
    setStreaming(value) { busy = value; if ($('web-research-panel')) sync(); },
    offerRetry(tool) { if (tool && ['read_url','search'].includes(tool.action)) { open(tool.action, tool); say('本轮未完成，链接或搜索词已保留；重试会发起一次新尝试，也可粘贴 JD 或上传截图。', true); } },
    toolStatus(value) { if (value && typeof value.message === 'string') say(value.message); },
  };
})();
