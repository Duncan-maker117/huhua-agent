/* Workspace projections and explicit, one-click answers to the current question. */
(() => {
  'use strict';
  const tabs = [
    ['jd', '读岗位', 'JD_INPUT'], ['experiences', '挖经历', 'COLLECTING'],
    ['resume', '写简历', 'BUILDING'], ['review', '核对', 'EVALUATING'],
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
  let hasResume = false, paintedVersion = null, status = '', resumeData = null;
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
    return JSON.stringify([callbacks.session?.(), guidance?.turn_id, guidance?.question, guidance?.options, guidance?.structure_plan]);
  }
  async function answer(value, key) {
    // Claim this question synchronously: double clicks, keyboard repeats and
    // detached old buttons must never enqueue another turn.
    if (streaming || choicePending || answeredGuidance.has(key) || key !== guidanceKey() || !value) return;
    if (value === '导出当前版本') {
      setMobileOpen(true); openTab('export', true); return;
    }
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
  const STATUS_LABEL = {direct: '直接证据', transferable: '可迁移', gap: '缺口'};
  const REQ_TEXT = () => new Map(list(workspace.jd?.info?.role_profile?.requirements).filter(row => row && row.id).map(row => [row.id, plain(row.text)]));
  // Every visible bullet of the saved draft with its model evidence (aligned by position; {} when hand-edited).
  function draftBullets() {
    const rows = [], evidence = workspace.tailor?.resume_meta?.bullets || {};
    for (const [section, field] of [['projects', 'polished_bullets'], ['work_experience', 'bullets'], ['campus', 'bullets'], ['open_source', 'bullets'], ['awards', 'bullets']]) {
      for (const item of list(resumeData?.[section])) {
        if (!item || item.hidden === true) continue;
        const records = list(evidence[item.item_id]);
        list(item[field]).forEach((text, index) => {
          if (plain(text).trim()) rows.push({itemId: item.item_id, itemName: plain(item.name || item.company) || '经历', text: plain(text), meta: records[index] || {}});
        });
      }
    }
    return rows;
  }
  function locate(text) {
    if (!plain(text)) return;
    callbacks.highlight?.(text);
    openTab('resume', true);
  }
  function bulletButton(text, className = 'match-bullet') {
    const el = button(text, () => locate(text), className);
    el.title = '在「写简历」中定位这一条';
    return el;
  }
  function renderMatch(panel) {
    const requirements = list(workspace.tailor?.match_plan?.requirements).filter(row => row && row.req_id);
    if (!requirements.length) return;
    const texts = REQ_TEXT(), bullets = draftBullets();
    const group = node('section', undefined, 'workspace-group match-table');
    group.setAttribute('aria-label', '岗位要求对照');
    group.append(node('h3', '岗位要求 · 你的证据'), node('p', '对照当前简历里已有的经历，不是 ATS 评分，也不代表录用概率。', 'workspace-description'));
    for (const row of requirements) {
      const state = STATUS_LABEL[row.status] ? row.status : 'gap';
      const card = node('article', undefined, 'match-row match-' + state);
      const head = node('div', undefined, 'match-head');
      head.append(node('p', texts.get(row.req_id) || row.req_id, 'match-req'), node('span', STATUS_LABEL[state], 'match-badge'));
      card.append(head);
      if (state === 'gap') card.append(node('p', '暂无经历支持', 'match-none'));
      else {
        if (plain(row.angle)) card.append(node('p', row.angle, 'match-angle'));
        const hits = bullets.filter(item => list(item.meta.req_ids).includes(row.req_id));
        if (hits.length) {
          const ul = node('ul', undefined, 'match-bullets');
          hits.forEach(item => { const li = node('li'); li.append(node('span', item.itemName, 'match-item-name'), bulletButton(item.text)); ul.append(li); });
          card.append(ul);
        } else card.append(node('p', '已有相关资料，当前稿还没有写入对应的一条。', 'match-none'));
      }
      group.append(card);
    }
    panel.append(group);
  }
  function renderJd() {
    const panel = $('workspace-panel-jd'); panel.replaceChildren();
    const jd = workspace.jd || {}, info = jd.info || {};
    heading(panel, '目标岗位', '招聘要求保留原句，方便对照你的经历。');
    renderWebSources(panel);
    const hasMatch = list(workspace.tailor?.match_plan?.requirements).length > 0;
    if (!hasMatch && !plain(jd.raw_text) && !Object.values(info).some(v => plain(v) || list(v).length) && !list(jd.keywords).length) {
      if (currentWebSources().length) empty(panel, '来源资料已保留', '可打开来源核对公开资料，或继续粘贴具体 JD。');
      else empty(panel, '先放进一份 JD', '粘贴招聘原文，或在输入框上传岗位截图、PDF。解析结果会出现在这里。');
      return;
    }
    if (!plain(jd.raw_text) && !Object.values(info).some(v => plain(v) || list(v).length) && !list(jd.keywords).length) { renderMatch(panel); return; }
    const card = node('article', undefined, 'workspace-card');
    card.append(node('h3', info.job_title || info.target_role || '当前岗位'));
    facts(card, [['公司', info.company], ['学历', info.education], ['经验', info.experience_years], ['薪资', info.salary_range]]);
    const tags = [...new Set([...list(jd.keywords), ...list(info.keyword_cloud?.core_keywords)].map(readable).filter(Boolean))];
    if (tags.length) {
      const row = node('div', undefined, 'workspace-tags'); tags.forEach(tag => row.append(node('span', tag))); card.append(row);
    }
    panel.append(card);
    renderMatch(panel);
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
    facts(panel, [['姓名', basic.name], ['求职方向', basic.objective || basic.target_role || basic.job_intention], ['学校', basic.school], ['学历', basic.degree], ['邮箱', basic.email], ['电话', basic.phone], ['可实习时间', basic.availability]]);
    facts(panel, list(basic.links).map(link => [link.text, link.url]));
    for (const education of list(experiences.education)) {
      const card = node('article', undefined, 'workspace-card');
      card.append(node('h3', education.school || '教育经历'));
      facts(card, [['专业', education.major], ['学历', education.degree], ['时间', [education.start_date, education.end_date].filter(Boolean).join(' — ')]]);
      if (education.highlights) card.append(node('p', education.highlights));
      panel.append(card);
    }
    if (!items.length) empty(panel, '从一件做过的事开始', '项目、实习、课程作业或自己做的小工具都可以。先说做了什么，再一起补细节。', {label: '从一个项目开始', value: '我想先补充一个项目经历：'});
    for (const item of items) {
      const card = node('article', undefined, 'workspace-card');
      card.append(node('h3', item.name || '待命名经历'));
      facts(card, [['类型', ({project:'项目',work:'工作 / 实习',education:'教育',campus:'校园经历',open_source:'开源贡献',awards:'竞赛荣誉'})[item.kind] || item.kind], ['职责', item.role], ['时间', item.period]]);
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
  function renderTailorChecks(panel) {
    const rows = draftBullets(), texts = REQ_TEXT();
    const transferable = rows.filter(row => list(row.meta.flags).includes('transferable'));
    const metrics = rows.filter(row => row.meta.needs_metric === true && plain(row.meta.metric_question).trim());
    if (transferable.length) {
      const group = node('section', undefined, 'workspace-group review-transferable');
      group.append(node('h3', '可迁移表达 · 请确认是否属实'), node('p', '这些句子借你已有的相关经历来回应岗位要求，不是直接做过同类工作。点击可在简历里定位。', 'workspace-description'));
      for (const row of transferable) {
        const card = node('article', undefined, 'workspace-card review-check');
        const requirement = list(row.meta.req_ids).map(id => texts.get(id)).find(Boolean);
        card.append(node('p', `由「${row.itemName}」经历迁移表达${requirement ? `「${requirement}」` : '相关'}要求`, 'workspace-emphasis'));
        card.append(bulletButton(row.text, 'match-bullet review-bullet'));
        group.append(card);
      }
      panel.append(group);
    }
    if (metrics.length) {
      const group = node('section', undefined, 'workspace-group review-metrics');
      group.append(node('h3', '缺数字 · 补一个更有说服力'), node('p', '点击问题会填进输入框，你补上真实数字后发送；没有就不用补，不会替你估算。', 'workspace-description'));
      for (const row of metrics) {
        const card = node('article', undefined, 'workspace-card review-check');
        card.append(node('p', `「${row.itemName}」：${row.text}`));
        const ask = button(row.meta.metric_question, () => fill(row.meta.metric_question), 'workspace-button workspace-secondary review-ask');
        ask.title = '填进输入框';
        card.append(ask);
        group.append(card);
      }
      panel.append(group);
    }
    return transferable.length + metrics.length;
  }
  function renderReview() {
    const panel = $('workspace-panel-review'); panel.replaceChildren();
    heading(panel, '投递前核对', '先解决影响真实性和岗位表达的问题。');
    const items = list(workspace.review?.items);
    const reply = plain(workspace.review?.reply);
    const extras = renderTailorChecks(panel);
    if (reply) {
      const report = node('article', undefined, 'workspace-card workspace-review-reply');
      if (window.HuhuaMarkdown) window.HuhuaMarkdown.render(report, reply);
      else report.textContent = reply;
      panel.append(report);
    }
    if (!items.length) {
      if (reply || extras) return;
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
  // Follow-up questions the interviewer has put to the user. Any message the user sends closes the ones shown.
  const closedKey = () => 'huhua_closed_questions:' + (callbacks.session?.() || '');
  function closedQuestions() {
    try { const rows = JSON.parse(localStorage.getItem(closedKey()) || '[]'); return new Set(Array.isArray(rows) ? rows : []); }
    catch (_) { return new Set(); }
  }
  function openQuestions() {
    const closed = closedQuestions();
    return list(workspace.tailor?.questions).filter(row => row && plain(row.question_id) && plain(row.q) && !closed.has(row.question_id)
      && list(row.options).some(option => plain(option?.label || option))).slice(0, 3);
  }
  function dismissQuestions() {
    const shown = openQuestions().map(row => row.question_id);
    if (shown.length) {
      const closed = closedQuestions(); shown.forEach(id => closed.add(id));
      try { localStorage.setItem(closedKey(), JSON.stringify([...closed].slice(-60))); } catch (_) { /* The dock only hides; the server keeps no answer state. */ }
    }
    renderGuidance();
  }
  function renderQuestions(dock, questions) {
    dock.append(node('p', '想让它更强，回答任意一个就行', 'guidance-label'));
    for (const row of questions) {
      const block = node('div', undefined, 'guidance-question-block');
      block.append(node('h3', row.q, 'guidance-question-text'));
      const hint = [plain(row.location_label) && '会改进：' + plain(row.location_label), plain(row.why)].filter(Boolean).join(' · ');
      if (hint) block.append(node('p', hint, 'guidance-why'));
      const choices = node('div', undefined, 'guidance-options'); choices.setAttribute('aria-label', '选择一个回答，也可以自由输入');
      for (const option of list(row.options)) {
        const label = plain(option?.label ?? option), value = plain(option?.value ?? option) || label;
        if (!label) continue;
        const chip = button(label, () => { if (!streaming && !choicePending) answerQuestion(row, value); }, 'guidance-option');
        chip.dataset.questionId = row.question_id;
        choices.append(chip);
      }
      block.append(choices); dock.append(block);
    }
    const hint = node('p', '点击即发送完整的回答，也可以直接在下方输入。', 'guidance-hint'); hint.setAttribute('role', 'status'); dock.append(hint);
  }
  async function answerQuestion(row, value) {
    choicePending = true; renderGuidance();
    try { await callbacks.sendChoice?.(`关于「${plain(row.q)}」：${value}`); }
    catch (_) { /* send() keeps the turn recoverable. */ }
    finally { choicePending = false; renderGuidance(); }
  }
  function renderGuidance() {
    const dock = $('guidance-dock'); dock.replaceChildren();
    const guidance = workspace.guidance;
    const key = guidanceKey();
    if (guidance?.kind === 'structure_plan') {
      dock.hidden = streaming || choicePending || answeredGuidance.has(key);
      if (!dock.hidden) renderStructurePlan(dock, guidance, key);
      return;
    }
    const questions = openQuestions();
    if (questions.length) {
      dock.hidden = streaming || choicePending;
      if (!dock.hidden) renderQuestions(dock, questions);
      return;
    }
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
  function renderStructurePlan(dock, guidance, key) {
    const card = guidance.structure_plan;
    const labels = {education: '教育经历', work_experience: '工作/实习经历', projects: '项目经历', campus: '校园经历', open_source: '开源贡献', awards: '竞赛荣誉', skills: '技能', certificates: '证书/活动'};
    const treatments = {lead: '写（重点）', keep: '写', brief: '压缩', backup: '不写'};
    function content(panel, plan) {
      const statement = plain(plan.profile_statement) || plain(plan.positioning);
      if (statement) panel.append(node('p', '将写进简历的个人定位：' + statement, 'guidance-why'));
      if (plain(plan.thesis)) panel.append(node('p', '主线：' + plan.thesis, 'guidance-why'));
      panel.append(node('p', '栏目：' + list(plan.section_order).map(id => labels[id] || id).join(' → '), 'guidance-why'));
      const entries = node('ul', undefined, 'workspace-list');
      for (const row of list(plan.experience_plan)) entries.append(node('li', `${plain(row.name) || row.item_id} · ${treatments[row.treatment] || row.treatment}：${plain(row.reason)}`));
      if (entries.childElementCount) panel.append(entries);
    }
    dock.append(node('p', '定方案', 'guidance-label'), node('h2', '推荐：' + card.recommended.label));
    content(dock, card.recommended);
    const styles = node('div', undefined, 'guidance-options');
    styles.append(node('span', '写法：'));
    for (const [value, label] of [['labeled', '问题-决策-结果'], ['plain', '普通']]) {
      const choice = button(label, () => answer('写法：' + label, key), 'guidance-option');
      choice.setAttribute('aria-pressed', String((card.recommended.bullet_style || 'plain') === value));
      styles.append(choice);
    }
    dock.append(styles);
    for (const alternative of list(card.alternatives)) {
      const details = node('details', undefined, 'guidance-question-block');
      details.append(node('summary', '备选：' + alternative.label + '（展开看差异）'));
      content(details, alternative);
      if (!list(alternative.experience_plan).length) details.append(node('p', '经历取舍沿用推荐方案。', 'guidance-why'));
      dock.append(details);
    }
    const choices = node('div', undefined, 'guidance-options');
    for (const option of list(guidance.options)) choices.append(button(option.label, () => answer(option.value, key), 'guidance-option'));
    dock.append(choices, node('p', '也可以直接说想怎么改', 'guidance-hint'));
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
      tab.classList.toggle('active', active === id); tab.classList.toggle('current', stage === stageId || (id === 'resume' && stage === 'EXPORT'));
      tab.setAttribute('aria-selected', String(active === id)); tab.tabIndex = active === id ? 0 : -1;
      $('workspace-panel-' + id).hidden = active !== id;
    }
  }
  function openTab(id, user = false) {
    const downloading = id === 'export';
    if (downloading) id = 'resume'; // Old saved workspace projections remain usable.
    if (!tabs.some(([key]) => key === id)) return;
    active = id; if (user && streaming) interactedDuringTurn = true;
    renderTabs(); $('workspace-body').scrollTop = 0;
    if (id === 'resume') requestAnimationFrame(() => callbacks.resize?.());
    if (downloading) window.HuhuaResumeActions?.focusDownload();
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
    if (changed) { renderJd(); renderExperiences(); renderReview(); renderSuggestions(); renderGuidance(); }
    if ((initial || options.focus) && !interactedDuringTurn && value.focus) openTab(value.focus_download ? 'export' : value.focus);
    if (!hasResume) status = plain(workspace.jd?.raw_text) ? '岗位与经历已同步' : '资料已同步';
    updateStatus();
  }
  function reset() {
    webSourceSession = null;
    resumeData = null; workspace = {}; active = 'jd'; stage = 'JD_INPUT'; hasWorkspace = false; hasResume = false;
    paintedVersion = null; status = ''; streaming = false; interactedDuringTurn = false; paintedDuringTurn = false;
    renderJd(); renderExperiences(); renderReview(); renderSuggestions(); renderGuidance(); renderTabs(); updateStatus();
  }
  function canvasResult(body) {
    hasResume = Boolean(body.has_data && body.data);
    resumeData = hasResume ? body.data : null;
    const version = body.workspace?.resume?.version ?? body.revision ?? null;
    const changed = hasResume && version !== paintedVersion;
    status = hasResume ? (changed ? '简历已更新 · 已同步到预览' : '当前简历已同步') : (hasWorkspace ? '资料已同步 · 补充经历后逐步成稿' : '补充经历，简历会逐步成稿');
    paintedVersion = version;
    if (streaming) paintedDuringTurn = true;
    renderJd(); renderReview(); renderSuggestions(); updateStatus();
  }
  function setStreaming(value) {
    streaming = value;
    if (value) { interactedDuringTurn = false; paintedDuringTurn = false; status = ''; }
    renderGuidance(); renderSuggestions(); updateStatus();
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
  window.HuhuaWorkspace = {refresh: () => callbacks.refresh?.(), dismissQuestions, init, update, reset, setWebSources, commitWebSources, setStreaming, canvasResult, openTab, setMobileOpen,
    setStage(value) {stage = value; if (!hasWorkspace) active = value === 'EXPORT' ? 'resume' : tabs.find(([, , id]) => id === value)?.[0] || 'jd'; renderTabs();},
    canvasError() {status = '预览同步失败，请刷新重试；当前内容已保留'; updateStatus();},
  };
})();
