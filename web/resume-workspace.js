/* Workspace projections and explicit, one-click answers to the current question. */
(() => {
  'use strict';
  const tabs = [
    ['jd', '读岗位', 'JD_INPUT'], ['experiences', '挖经历', 'COLLECTING'],
    ['resume', '写简历', 'BUILDING'], ['review', '核对', 'EVALUATING'], ['export', '导出', 'EXPORT'],
  ];
  const $ = id => document.getElementById(id);
  const list = value => Array.isArray(value) ? value : [];
  const plain = value => typeof value === 'string' || typeof value === 'number' ? String(value) : '';
  const readable = value => plain(value) || plain(value?.text) || plain(value?.title) || plain(value?.name);
  function node(tag, text, className) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = plain(text);
    if (className) el.className = className;
    return el;
  }
  let callbacks = {}, workspace = {}, active = 'jd', stage = 'JD_INPUT';
  let streaming = false, interactedDuringTurn = false, hasWorkspace = false, paintedDuringTurn = false;
  let hasResume = false, paintedVersion = null, status = '';
  const webSourceCache = new Map();
  let webSourceSession = null;
  const answeredGuidance = new Set();
  let choicePending = false;
  function button(text, handler, className = 'workspace-button') {
    const el = node('button', text, className);
    el.type = 'button'; el.addEventListener('click', handler);
    return el;
  }
  function heading(panel, title, description) {
    panel.append(node('h2', title, 'workspace-heading'));
    if (description) panel.append(node('p', description, 'workspace-description'));
  }
  function empty(panel, title, description, action) {
    const box = node('div', undefined, 'workspace-empty');
    box.append(node('h3', title), node('p', description));
    if (action) box.append(button(action.label, () => fill(action.value)));
    panel.append(box);
  }
  function bulletList(panel, values, className = 'workspace-list') {
    const lines = list(values).map(readable).filter(Boolean);
    if (!lines.length) return;
    const ul = node('ul', undefined, className);
    lines.forEach(text => ul.append(node('li', text)));
    panel.append(ul);
  }
  function section(panel, title, values) {
    if (!list(values).some(readable)) return;
    const group = node('section', undefined, 'workspace-group');
    group.append(node('h3', title)); bulletList(group, values); panel.append(group);
  }
  function facts(panel, entries) {
    const present = entries.filter(([, value]) => plain(value));
    if (!present.length) return;
    const dl = node('dl', undefined, 'workspace-facts');
    present.forEach(([label, value]) => dl.append(node('dt', label), node('dd', value)));
    panel.append(dl);
  }
  function fill(value) {
    if (streaming || !plain(value)) return;
    callbacks.fillInput?.(plain(value));
    setMobileOpen(false);
  }
  function guidanceKey() {
    const guidance = workspace.guidance;
    return JSON.stringify([callbacks.session?.(), guidance?.turn_id, guidance?.question, guidance?.options]);
  }
  async function answer(value, key) {
    // Claim this question synchronously: double clicks, keyboard repeats and
    // detached old buttons must never enqueue another turn.
    if (streaming || choicePending || answeredGuidance.has(key) || key !== guidanceKey() || !value) return;
    choicePending = true;
    answeredGuidance.add(key);
    renderGuidance();
    try {
      if (!await callbacks.sendChoice?.(value)) answeredGuidance.delete(key);
    } catch {
      answeredGuidance.delete(key);
    } finally {
      choicePending = false;
      renderGuidance();
    }
  }
  function safeSourceUrl(value) {
    if (typeof value !== 'string' || !/^https?:\/\//i.test(value)) return null;
    try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password ? url.href : null; }
    catch (_) { return null; }
  }
  function normalizeSources(sources) {
    return sources.slice(0, 12).map(value => {
      const source = value && typeof value === 'object' ? value : {};
      const normalized = {};
      for (const field of ['title', 'url', 'kind', 'fetched_at', 'published_at', 'content']) {
        if (typeof source[field] === 'string') normalized[field] = source[field];
      }
      if (typeof source.content_truncated === 'boolean') normalized.content_truncated = source.content_truncated;
      if (['public_page_text', 'github_repository_metadata', 'github_profile_and_public_repositories'].includes(source.read_scope)) normalized.read_scope = source.read_scope;
      if (Number.isInteger(source.request_count) && source.request_count >= 1 && source.request_count <= 4) normalized.request_count = source.request_count;
      return normalized;
    });
  }
  function sourceScope(source) {
    if (/search|snippet/.test(plain(source.kind).toLowerCase())) return '仅基于搜索返回的摘要分析，尚未读取这些结果网页的正文。';
    if (['job_page', 'public_page'].includes(source.kind) && source.content_truncated === true) return '提取的正文较长，仅分析前 12,000 字；请打开原页核对其余内容。';
    if (source.read_scope === 'github_repository_metadata') return '读取了该仓库的公开元数据，不代表已逐文件审阅代码。';
    if (source.read_scope === 'github_profile_and_public_repositories') return '读取了主页信息与最多 5 条公开自有仓库摘要（可能含 fork），不代表完整仓库列表或逐文件代码审阅。';
    return '基于本次提取的网页资料分析，不代表已完整读取网站或页面的全部内容。';
  }
  function acceptWebSources(sources, session, {pending = false, commit = false} = {}) {
    if (!session || !Array.isArray(sources)) return false;
    // Refreshes may still contain the previous turn's group while the model is running.
    if (webSourceCache.get(session)?.pending && !pending && !commit) return false;
    webSourceCache.set(session, {sources: normalizeSources(sources), pending});
    return true;
  }
  function currentWebSources() {
    return webSourceSession === callbacks.session?.() ? list(webSourceCache.get(webSourceSession)?.sources) : [];
  }
  function commitWebSources(value, session) {
    if (session !== callbacks.session?.() || !value || !Object.prototype.hasOwnProperty.call(value, 'web_sources')) return;
    if (acceptWebSources(value.web_sources, session, {commit:true})) { webSourceSession = session; renderJd(); }
  }
  function sourceTime(value) {
    const text = plain(value);
    if (!text) return '';
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
    const time = new Date(text);
    return Number.isNaN(time.getTime()) ? text.slice(0, 100) : time.toLocaleString('zh-CN', {hour12:false});
  }
  function renderWebSources(panel) {
    const sources = currentWebSources();
    if (!sources.length) return;
    const section = node('section', undefined, 'workspace-web-sources');
    section.setAttribute('aria-label', '联网资料来源');
    section.append(node('h3', '联网资料来源'), node('p', '这里只展示最近获取的一组资料。[1] 等编号仅对应这组资料的分析，不对应更早回复。请按下方获取时间核对；外部资料不作为你的本人经历。', 'workspace-description'));
    for (const [index, source] of sources.entries()) {
      const card = node('article', undefined, 'workspace-web-source');
      const url = safeSourceUrl(source.url), title = plain(source.title) || (url ? new URL(url).hostname : '来源资料');
      const heading = node('h4'), numberedTitle = `[${index + 1}] ${title.slice(0, 300)}`;
      if (url) { const link = node('a', numberedTitle); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; heading.append(link); }
      else heading.append(node('span', numberedTitle));
      card.append(heading);
      const kind = plain(source.kind).toLowerCase();
      const meta = node('div', undefined, 'workspace-web-source-meta');
      meta.append(node('span', /search|snippet/.test(kind) ? '搜索结果摘要' : kind === 'public_page' ? '公开网页资料' : '网页资料'));
      if (url) meta.append(node('span', new URL(url).hostname));
      meta.append(node('span', source.fetched_at ? '获取时间：' + sourceTime(source.fetched_at) : '获取时间：未提供'));
      if (source.published_at) meta.append(node('span', '页面发布日期：' + sourceTime(source.published_at)));
      card.append(meta, node('p', sourceScope(source), 'workspace-web-source-scope'));
      if (plain(source.content)) {
        const details = node('details', undefined, 'workspace-source');
        const excerpt = plain(source.content).slice(0, 1800);
        details.append(node('summary', plain(source.content).length > 1800 ? '查看内容摘录（前 1,800 字）' : '查看内容摘录'), node('p', excerpt));
        if (plain(source.content).length > 1800) details.append(node('p', '这里仅缩短卡片展示，不改变本轮用于分析的已获取资料范围。', 'workspace-web-source-scope'));
        card.append(details);
      }
      section.append(card);
    }
    panel.append(section);
  }
  function setWebSources(sources, session) {
    if (!session || session !== callbacks.session?.() || !Array.isArray(sources)) return;
    webSourceSession = session;
    acceptWebSources(sources, session, {pending:true});
    renderJd();
    if (sources.length) openTab('jd');
  }
  function renderJd() {
    const panel = $('workspace-panel-jd'); panel.replaceChildren();
    const jd = workspace.jd || {}, info = jd.info || {};
    heading(panel, '目标岗位', '招聘要求保留原句，方便对照你的经历。');
    renderWebSources(panel);
    if (!plain(jd.raw_text) && !Object.values(info).some(v => plain(v) || list(v).length) && !list(jd.keywords).length) {
      if (currentWebSources().length) empty(panel, '来源资料已保留', '可打开来源核对公开资料，或继续粘贴具体 JD。');
      else empty(panel, '先放进一份 JD', '粘贴招聘原文，或在输入框上传岗位截图、PDF。解析结果会出现在这里。');
      return;
    }
    const card = node('article', undefined, 'workspace-card');
    card.append(node('h3', info.job_title || info.target_role || '当前岗位'));
    facts(card, [['公司', info.company], ['学历', info.education], ['经验', info.experience_years], ['薪资', info.salary_range]]);
    const tags = [...new Set([...list(jd.keywords), ...list(info.keyword_cloud?.core_keywords)].map(readable).filter(Boolean))];
    if (tags.length) {
      const row = node('div', undefined, 'workspace-tags'); tags.forEach(tag => row.append(node('span', tag))); card.append(row);
    }
    panel.append(card);
    if (plain(info.summary) || list(info.decoded_items).length) {
      const interpretation = node('section', undefined, 'workspace-group');
      interpretation.append(node('h3', '岗位解读'));
      if (plain(info.summary)) interpretation.append(node('p', info.summary, 'workspace-description'));
      for (const item of list(info.decoded_items)) {
        const row = node('div', undefined, 'workspace-evidence');
        if (item.keyword) row.append(node('p', item.keyword, 'workspace-emphasis'));
        if (item.surface_meaning) row.append(node('p', item.surface_meaning));
        if (item.real_meaning) row.append(node('p', item.real_meaning));
        interpretation.append(row);
      }
      panel.append(interpretation);
    }
    section(panel, '必要条件', info.hard_requirements);
    section(panel, '需要的技能', info.required_skills);
    section(panel, '工作内容', info.key_responsibilities);
    section(panel, '加分项', info.preferred_qualities);
    if (list(info.requirement_evidence).length) {
      const evidence = node('section', undefined, 'workspace-group'); evidence.append(node('h3', '原句依据'));
      for (const item of info.requirement_evidence) {
        const row = node('div', undefined, 'workspace-evidence');
        if (item.text) row.append(node('p', item.text, 'workspace-emphasis'));
        if (item.source_quote) row.append(node('blockquote', item.source_quote));
        if (item.verification_question) row.append(node('p', '待确认：' + item.verification_question, 'workspace-missing'));
        evidence.append(row);
      }
      panel.append(evidence);
    }
    if (plain(jd.raw_text)) {
      const details = node('details', undefined, 'workspace-source');
      details.append(node('summary', '查看 JD 原文'), node('p', jd.raw_text)); panel.append(details);
    }
  }
  function renderExperiences() {
    const panel = $('workspace-panel-experiences'); panel.replaceChildren();
    const experiences = workspace.experiences || {}, items = list(experiences.items);
    heading(panel, '已收集的经历', '来自你提供的资料；缺少的细节单独标出。');
    const basic = experiences.basic_info || workspace.basic_info || {};
    facts(panel, [['姓名', basic.name], ['求职方向', basic.objective || basic.target_role || basic.job_intention], ['学校', basic.school], ['学历', basic.degree], ['邮箱', basic.email], ['电话', basic.phone]]);
    for (const education of list(experiences.education)) {
      const card = node('article', undefined, 'workspace-card');
      card.append(node('h3', education.school || '教育经历'));
      facts(card, [['专业', education.major], ['学历', education.degree], ['时间', [education.start_date, education.end_date].filter(Boolean).join(' — ')]]);
      panel.append(card);
    }
    if (!items.length) empty(panel, '从一件做过的事开始', '项目、实习、课程作业或自己做的小工具都可以。先说做了什么，再一起补细节。', {label: '从一个项目开始', value: '我想先补充一个项目经历：'});
    for (const item of items) {
      const card = node('article', undefined, 'workspace-card');
      card.append(node('h3', item.name || '待命名经历'));
      facts(card, [['类型', ({project:'项目',work:'工作 / 实习',education:'教育'})[item.kind] || item.kind], ['职责', item.role], ['时间', item.period]]);
      bulletList(card, item.bullets);
      if (list(item.missing).length) {
        const missing = node('div', undefined, 'workspace-missing-box');
        missing.append(node('h4', '还需要你补充')); bulletList(missing, item.missing); card.append(missing);
      }
      panel.append(card);
    }
    const skills = experiences.skills || workspace.skills;
    if (Array.isArray(skills)) section(panel, '已提供的技能', skills);
    else if (skills && typeof skills === 'object') {
      for (const [label, values] of Object.entries(skills)) section(panel, label, Array.isArray(values) ? values : [values]);
    }
    section(panel, '已提供的奖项与证书', experiences.certificates);
    section(panel, '资料待核对', experiences.verification_notes);
  }
  function renderReview() {
    const panel = $('workspace-panel-review'); panel.replaceChildren();
    heading(panel, '投递前核对', '先解决影响真实性和岗位表达的问题。');
    const items = list(workspace.review?.items);
    const reply = plain(workspace.review?.reply);
    if (reply) {
      const report = node('article', undefined, 'workspace-card workspace-review-reply');
      if (window.HuhuaMarkdown) window.HuhuaMarkdown.render(report, reply);
      else report.textContent = reply;
      panel.append(report);
    }
    if (!items.length) {
      if (reply) return;
      empty(panel, hasResume ? '可以检查当前简历' : '有草稿后再一起核对', hasResume ? '检查会指出具体位置、原因和修改方向，待核实的内容由你确认。' : '补充经历后，先在「写简历」查看草稿。', hasResume ? {label: '准备检查当前简历', value: '请检查当前保存的简历，指出需要核实或补充的具体位置。'} : undefined);
      return;
    }
    for (const item of items) {
      const card = node('article', undefined, 'workspace-card');
      if (typeof item === 'string') card.append(node('p', item));
      else {
        card.append(node('h3', item.title || item.location || item.field || '需要核对'));
        for (const key of ['detail', 'issue', 'text', 'reason', 'message']) if (plain(item[key])) card.append(node('p', item[key]));
        if (item.action) card.append(node('p', '建议动作：' + item.action, 'workspace-emphasis'));
        if (item.question) card.append(node('p', '请你确认：' + item.question, 'workspace-missing'));
      }
      panel.append(card);
    }
  }
  function renderExport() {
    const panel = $('workspace-panel-export'); panel.replaceChildren();
    heading(panel, '导出这份简历', window.HuhuaAccount?.guest() ? '先免费聊天和查看模板；登录后即可导出，并保留这份简历与对话。' : '导出读取当前保存的内容。补充信息后，先在「写简历」核对最新稿。');
    if (!hasResume) {
      empty(panel, '还没有可导出的草稿', '先补充真实经历，草稿会逐步出现在「写简历」中。'); return;
    }
    const card = node('article', undefined, 'workspace-card');
    card.append(node('h3', '选择交付格式'), node('p', 'Word 使用通用排版；PDF 在全屏模板页选择样式后生成下载文件。'));
    const actions = node('div', undefined, 'workspace-actions');
    const word = button('下载通用 Word', () => $('btn-export-docx').click()); word.disabled = streaming; actions.append(word);
    const pdf = node('a', '打开模板 / 导出 PDF', 'workspace-button workspace-secondary');
    pdf.href = '/resume?session=' + encodeURIComponent(callbacks.session?.() || ''); actions.append(pdf);
    card.append(actions); panel.append(card);
  }
  function renderSuggestions() {
    const panel = $('workspace-suggestions'); panel.replaceChildren();
    const suggestions = list(workspace.suggestions);
    panel.hidden = !suggestions.length;
    if (panel.hidden) return;
    panel.append(node('h2', '我的建议', 'workspace-heading'), node('p', '这些是修改方向，尚未作为本人事实写入简历。想改哪里，直接在对话里说。', 'workspace-description'));
    suggestions.forEach(item => {
      const row = node('div', undefined, 'workspace-suggestion');
      if (typeof item === 'string') row.append(node('p', item));
      else {
        if (item.title) row.append(node('h3', item.title));
        if (item.detail) {
          const detail = node('div', undefined, 'workspace-suggestion-detail');
          if (window.HuhuaMarkdown) window.HuhuaMarkdown.render(detail, plain(item.detail));
          else detail.textContent = plain(item.detail);
          row.append(detail);
        }
      }
      panel.append(row);
    });
  }
  function renderGuidance() {
    const dock = $('guidance-dock'); dock.replaceChildren();
    const guidance = workspace.guidance;
    const key = guidanceKey();
    dock.hidden = streaming || choicePending || answeredGuidance.has(key) || !guidance || !plain(guidance.question);
    if (dock.hidden) return;
    dock.append(node('p', guidance.title || '待你补充', 'guidance-label'));
    const question = node('h2', guidance.question); question.id = 'guidance-question'; dock.append(question);
    if (guidance.why) dock.append(node('p', guidance.why, 'guidance-why'));
    const choices = node('div', undefined, 'guidance-options'); choices.setAttribute('aria-label', '选择一个回答，也可以自由输入');
    for (const option of list(guidance.options)) {
      const label = plain(option.label), value = plain(option.value) || label;
      if (!label) continue;
      choices.append(button(label, () => answer(value, key), 'guidance-option'));
    }
    if (choices.childElementCount) dock.append(choices);
    const hint = node('p', choices.childElementCount ? guidance.kind === 'next_action' ? '点击即发送所选下一步，也可以直接输入。' : '点击选项即发送，也可以直接输入。' : '这题适合直接描述，请在下方输入。', 'guidance-hint'); hint.id = 'guidance-choice-hint'; hint.setAttribute('role', 'status'); dock.append(hint);
  }
  function renderTabs() {
    const rail = $('stage-rail');
    if (!rail.childElementCount) for (const [id, label] of tabs) {
      const tab = button(label, () => openTab(id, true), 'stage-chip');
      tab.id = 'workspace-tab-' + id; tab.dataset.tab = id;
      tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', 'workspace-panel-' + id);
      tab.addEventListener('keydown', event => {
        const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']; if (!keys.includes(event.key)) return;
        event.preventDefault(); const index = tabs.findIndex(([key]) => key === id);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
        openTab(tabs[next][0], true); $('workspace-tab-' + tabs[next][0]).focus();
      });
      rail.append(tab);
    }
    for (const [id, , stageId] of tabs) {
      const tab = $('workspace-tab-' + id);
      tab.classList.toggle('active', active === id); tab.classList.toggle('current', stage === stageId);
      tab.setAttribute('aria-selected', String(active === id)); tab.tabIndex = active === id ? 0 : -1;
      $('workspace-panel-' + id).hidden = active !== id;
    }
  }
  function openTab(id, user = false) {
    if (!tabs.some(([key]) => key === id)) return;
    active = id; if (user && streaming) interactedDuringTurn = true;
    renderTabs(); $('workspace-body').scrollTop = 0;
    if (id === 'resume') requestAnimationFrame(() => callbacks.resize?.());
  }
  function updateStatus() {
    $('workspace-status').textContent = streaming
      ? (paintedDuringTurn ? status + '，正在回复…' : '正在整理本轮资料，完成后同步到这里…')
      : status || '把岗位、经历和简历放在一起';
  }
  function update(value, options = {}) {
    if (!value || typeof value !== 'object') return;
    const initial = !hasWorkspace;
    const changed = JSON.stringify(workspace) !== JSON.stringify(value);
    workspace = value; hasWorkspace = true; webSourceSession = callbacks.session?.() || null;
    if (Object.prototype.hasOwnProperty.call(value, 'web_sources')) acceptWebSources(value.web_sources, webSourceSession);
    if (typeof value.resume?.has_data === 'boolean') hasResume = value.resume.has_data;
    if (changed) { renderJd(); renderExperiences(); renderReview(); renderExport(); renderSuggestions(); renderGuidance(); }
    if ((initial || options.focus) && !interactedDuringTurn && value.focus) openTab(value.focus);
    if (!hasResume) status = plain(workspace.jd?.raw_text) ? '岗位与经历已同步' : '资料已同步';
    updateStatus();
  }
  function reset() {
    webSourceSession = null;
    workspace = {}; active = 'jd'; stage = 'JD_INPUT'; hasWorkspace = false; hasResume = false;
    paintedVersion = null; status = ''; streaming = false; interactedDuringTurn = false; paintedDuringTurn = false;
    renderJd(); renderExperiences(); renderReview(); renderExport(); renderSuggestions(); renderGuidance(); renderTabs(); updateStatus();
  }
  function canvasResult(body) {
    hasResume = Boolean(body.has_data && body.data);
    const version = body.workspace?.resume?.version ?? body.revision ?? null;
    const changed = hasResume && version !== paintedVersion;
    status = hasResume ? (changed ? '简历已更新 · 已同步到预览' : '当前简历已同步') : (hasWorkspace ? '资料已同步 · 补充经历后逐步成稿' : '补充经历，简历会逐步成稿');
    paintedVersion = version;
    if (streaming) paintedDuringTurn = true;
    renderReview(); renderExport(); renderSuggestions(); updateStatus();
  }
  function setStreaming(value) {
    streaming = value;
    if (value) { interactedDuringTurn = false; paintedDuringTurn = false; status = ''; }
    renderGuidance(); renderExport(); renderSuggestions(); updateStatus();
  }
  function setMobileOpen(value) {
    const pane = $('canvas-pane'); pane.classList.toggle('is-open', value);
    $('btn-toggle-canvas').setAttribute('aria-expanded', String(value));
    $('btn-toggle-canvas').setAttribute('aria-controls', 'canvas-pane');
    if (matchMedia('(max-width: 1023px)').matches) {
      $('chat-pane').inert = value;
      if (value) { pane.setAttribute('role', 'dialog'); pane.setAttribute('aria-modal', 'true'); $('btn-close-workspace').focus(); }
      else { pane.removeAttribute('role'); pane.removeAttribute('aria-modal'); $('chat-pane').inert = false; $('input').focus(); }
    }
    requestAnimationFrame(() => callbacks.resize?.());
  }
  function init(options = {}) {
    callbacks = options; reset();
    window.addEventListener('huhua-account-changed', renderExport);
    window.addEventListener('huhua-account-reset', () => { webSourceCache.clear(); });
    $('btn-close-workspace').addEventListener('click', () => setMobileOpen(false));
    $('canvas-pane').addEventListener('keydown', event => {
      if (!$('canvas-pane').classList.contains('is-open') || !matchMedia('(max-width: 1023px)').matches) return;
      if (event.key === 'Escape') { event.preventDefault(); setMobileOpen(false); return; }
      if (event.key === 'Tab') {
        const focusables = [...$('canvas-pane').querySelectorAll('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],[tabindex="0"],summary')].filter(el => el.getClientRects().length && !el.closest('[hidden]'));
        const first = focusables[0], last = focusables.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    });
    window.addEventListener('resize', () => {
      if (!matchMedia('(max-width: 1023px)').matches) {
        $('chat-pane').inert = false;
        $('canvas-pane').classList.remove('is-open');
        $('canvas-pane').removeAttribute('role'); $('canvas-pane').removeAttribute('aria-modal');
        $('btn-toggle-canvas').setAttribute('aria-expanded', 'false');
      }
    });
  }
  window.HuhuaWorkspace = {refresh: () => callbacks.refresh?.(), init, update, reset, setWebSources, commitWebSources, setStreaming, canvasResult, openTab, setMobileOpen,
    setStage(value) {stage = value; if (!hasWorkspace) active = tabs.find(([, , id]) => id === value)?.[0] || 'jd'; renderTabs();},
    canvasError() {status = '预览同步失败，请刷新重试；当前内容已保留'; updateStatus();},
  };
})();
