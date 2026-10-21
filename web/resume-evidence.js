/* Read-only evidence cards for the main workspace's opaque A4 preview. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const list = value => Array.isArray(value) ? value : [];
  const text = value => typeof value === 'string' ? value : '';
  const unique = values => [...new Set(values)];
  const FLAGS = {transferable: '这句借用了你的相关经历，确认一下这样说是否准确。'};
  const LABELS = {supported: '有原话依据', pending: '待你确认', manual: '手动编辑'};
  let callbacks = {}, workspace = {}, rows = [], session = null, preference = null;
  let enabled = false, available = false, current = false, visiblePaths = null;
  let selected = null, pendingIndex = -1, revealAfterPaint = null;
  const frame = () => $('live-sheet');
  const send = message => frame()?.contentWindow?.postMessage(message, '*');
  function node(tag, value, className) {
    const el = document.createElement(tag);
    if (value !== undefined) el.textContent = value;
    if (className) el.className = className;
    return el;
  }
  function button(label, action, className = 'evidence-link') {
    const el = node('button', label, className); el.type = 'button'; el.addEventListener('click', action); return el;
  }
  function classify(records) {
    const metadata = records.filter(record => record && Object.keys(record).length);
    const factIds = unique(metadata.flatMap(record => list(record.fact_ids)));
    const facts = factIds.map(id => workspace.tailor?.evidence?.facts?.[id]);
    const resolved = facts.filter(fact => fact?.active === true && (text(fact.source_quote).trim() || text(fact.text).trim()));
    const inactive = facts.some(fact => fact?.active === false);
    const missing = facts.some(fact => !fact || (!text(fact.source_quote).trim() && !text(fact.text).trim()));
    const flags = unique(metadata.flatMap(record => list(record.flags)));
    const metrics = metadata.filter(record => record.needs_metric);
    const partial = metadata.length > 0 && metadata.length < records.length;
    const state = !metadata.length ? 'manual' : flags.length || metrics.length || inactive || missing || !resolved.length || partial ? 'pending' : 'supported';
    return {state, metadata, facts: facts.filter(Boolean), inactive, missing: missing || (!factIds.length && metadata.length > 0),
      flags, metrics, partial, reqIds: unique(metadata.flatMap(record => list(record.req_ids)))};
  }
  function buildRows(data) {
    const result = [], meta = workspace.tailor?.resume_meta || {};
    const sections = Array.isArray(data?.sections) ? new Set(data.sections.map(section => section.kind)) : null;
    for (const section of ['work_experience', 'projects', 'campus', 'open_source', 'awards']) {
      if (sections && !sections.has(section)) continue;
      list(data?.[section]).forEach((item, index) => {
        if (!item || item.hidden === true) return;
        const base = `/${section}/${index}`, field = section === 'projects' ? 'polished_bullets' : 'bullets';
        if (['projects', 'work_experience'].includes(section) && list(item.tech_stack).length) {
          const records = item.tech_stack.map((_, i) => meta.tech_stack?.[item.item_id]?.[i] || {});
          result.push({path: base + '/tech_stack', text: '技术栈：' + item.tech_stack.join('、'), ...classify(records)});
        }
        list(item[field]).forEach((value, i) => {
          if (text(value).trim()) result.push({path: `${base}/${field}/${i}`, text: value,
            ...classify([meta.bullets?.[item.item_id]?.[i] || {}])});
        });
      });
    }
    return result;
  }
  const visibleRows = () => visiblePaths ? rows.filter(row => visiblePaths.has(row.path)) : rows;
  function sync() {
    const shown = visibleRows();
    available = current && shown.some(row => row.metadata.length);
    enabled = available && preference !== false;
    const toggle = $('evidence-toggle'), summary = $('evidence-summary');
    if (!toggle || !summary) return;
    toggle.disabled = !available; toggle.setAttribute('aria-pressed', String(enabled));
    summary.replaceChildren();
    if (!available) summary.textContent = '这份稿是手动编辑的，暂无可追溯的原话';
    else {
      const supported = shown.filter(row => row.state === 'supported').length;
      const count = shown.filter(row => row.state === 'pending').length;
      const manual = shown.filter(row => row.state === 'manual').length;
      summary.append(node('span', `${shown.length} 条要点 · ${supported} 条能对上你的原话`));
      if (count) {
        summary.append(node('span', ' · '));
        summary.append(button(`${count} 条待你确认`, nextPending, 'evidence-pending-link'));
      }
      if (manual) summary.append(node('span', ` · ${manual} 条是你手动写的`));
    }
    send({type: 'huhua-evidence-state', enabled, rows: shown.map(row => ({path: row.path, state: row.state}))});
  }
  function close(restoreFocus = true) {
    const hadCard = selected !== null;
    selected = null;
    const card = $('evidence-card');
    if (card) { card.hidden = true; card.replaceChildren(); }
    if (hadCard && restoreFocus) frame()?.focus({preventScroll: true});
  }
  function choose(value) {
    preference = value; revealAfterPaint = null;
    try { localStorage.setItem('huhua_resume_evidence:' + session, String(value)); } catch (_) { /* Optional preference. */ }
    close(); sync();
  }
  function nextPending() {
    const candidates = visibleRows().filter(row => row.state === 'pending');
    if (!candidates.length) return;
    choose(true);
    pendingIndex = (pendingIndex + 1) % candidates.length;
    // Reveal inside the iframe, then scroll its scaled parent viewport too.
    send({type: 'huhua-evidence-reveal', path: candidates[pendingIndex].path});
  }
  function update(value, data, nextSession, isCurrent = true) {
    if (session !== nextSession) {
      session = nextSession; preference = null; visiblePaths = null;
      try {
        const saved = localStorage.getItem('huhua_resume_evidence:' + session);
        if (saved === 'true' || saved === 'false') preference = saved === 'true';
      } catch (_) { /* Blocked storage does not block evidence. */ }
    }
    workspace = value || {}; current = Boolean(data && isCurrent);
    rows = current ? buildRows(data) : []; pendingIndex = -1; revealAfterPaint = null;
    close(); sync();
  }
  function attach() {
    close(); visiblePaths = null;
    send({type: 'huhua-evidence-describe'});
    sync();
  }
  function screenRect(rect) {
    const bounds = frame().getBoundingClientRect();
    const scale = bounds.width / (frame().clientWidth || 794);
    return {left: bounds.left + rect.left * scale, right: bounds.left + rect.right * scale,
      top: bounds.top + rect.top * scale, bottom: bounds.top + rect.bottom * scale};
  }
  function place(card, rect) {
    const anchor = screenRect(rect), gap = 12, margin = 12;
    card.style.left = ''; card.style.top = ''; card.style.maxHeight = '';
    if (window.innerWidth < 768) return; // CSS owns the bottom drawer.
    const width = 320, height = Math.min(card.getBoundingClientRect().height, window.innerHeight - margin * 2);
    let left, top, room = window.innerHeight - margin * 2;
    if (anchor.right + gap + width <= window.innerWidth - margin) {
      left = anchor.right + gap; top = Math.max(margin, Math.min(anchor.top, window.innerHeight - height - margin));
    } else {
      left = Math.max(margin, Math.min(anchor.left, window.innerWidth - width - margin));
      const below = window.innerHeight - anchor.bottom - gap - margin, above = anchor.top - gap - margin;
      if (below >= Math.min(height, 180) || below >= above) { top = anchor.bottom + gap; room = below; }
      else { room = above; top = anchor.top - gap - Math.min(height, room); }
    }
    card.style.left = left + 'px'; card.style.top = Math.max(margin, top) + 'px';
    card.style.maxHeight = Math.max(40, Math.min(room, window.innerHeight - top - margin)) + 'px';
  }
  function fill(value) {
    close(false); callbacks.fill?.(value);
  }
  function show(row, rect) {
    if (!enabled) return;
    if (selected === row.path) { close(); return; }
    close(false); selected = row.path;
    const card = $('evidence-card'); card.hidden = false;
    const head = node('div', undefined, 'evidence-head');
    head.append(node('h2', '这句的依据'), node('span', LABELS[row.state], 'evidence-badge evidence-' + row.state));
    const dismiss = button('×', () => close(), 'evidence-close'); dismiss.setAttribute('aria-label', '关闭依据');
    head.append(dismiss); card.append(head);
    if (row.state === 'manual') card.append(node('p', '这句是你手动改的，没有关联原话', 'evidence-note'));
    else {
      const sources = node('section', undefined, 'evidence-section'); sources.append(node('h3', '你说过的'));
      const quotes = new Map();
      for (const fact of row.facts) {
        const quote = text(fact.source_quote).trim(), body = quote || text(fact.text).trim();
        if (!body) continue;
        const previous = quotes.get(body);
        // Prefer an original quote over its normalized fallback when identical.
        quotes.set(body, {body, quote: quote || previous?.quote || '',
          inactive: fact.active === false || previous?.inactive === true});
      }
      let more;
      [...quotes.values()].forEach(({inactive, quote, body}, index) => {
        if (index === 3) {
          more = node('details', undefined, 'evidence-more');
          more.append(node('summary', `再看 ${quotes.size - 3} 条`)); sources.append(more);
          more.addEventListener('toggle', () => { if (selected === row.path) place(card, rect); });
        }
        const block = node('blockquote'); block.append(node('p', quote ? `「${body}」` : body));
        if (!quote) block.append(node('small', '整理自你的材料'));
        if (inactive) block.append(node('small', '依据已更新，待确认', 'evidence-warning'));
        (index < 3 ? sources : more).append(block);
      });
      if (!quotes.size || row.missing) sources.append(node('p', '未找到依据', 'evidence-note'));
      card.append(sources);
    }
    if (row.reqIds.length) {
      const requirements = list(workspace.jd?.info?.role_profile?.requirements);
      const matches = list(workspace.tailor?.match_plan?.requirements);
      const section = node('section', undefined, 'evidence-section'); section.append(node('h3', '对应岗位要求'));
      for (const id of row.reqIds) {
        const requirement = requirements.find(req => req.id === id);
        const line = node('p', text(requirement?.text) || '这条岗位要求已更新', 'evidence-requirement');
        const status = callbacks.statusLabels?.[matches.find(req => req.req_id === id)?.status];
        if (status) line.append(node('span', status, 'evidence-req-badge'));
        section.append(line);
      }
      card.append(section);
    }
    if (row.state === 'pending') {
      const notes = node('section', undefined, 'evidence-confirm'); notes.append(node('h3', '待你确认'));
      for (const question of unique(row.metrics.map(record => text(record.metric_question).trim() || '这件事有没有可以确认的数量或结果？'))) {
        notes.append(node('p', '可以补一个数字：' + question), button('回答这个问题', () => fill(question)));
      }
      if (row.inactive) notes.append(node('p', '你后来更正过这里的说法，建议核对这句'));
      if (row.partial) notes.append(node('p', '这行有手动调整的技术，暂未关联原话。'));
      const knownFlags = unique(row.flags.map(flag => Object.hasOwn(FLAGS, flag) ? FLAGS[flag] : '').filter(Boolean));
      knownFlags.forEach(label => notes.append(node('p', label)));
      // Generic fallback only when nothing more specific was said above.
      if (notes.children.length === 1) notes.append(node('p', '这句还有待核对的地方，可以在对话里补充或改一下。'));
      card.append(notes);
    }
    const actions = node('div', undefined, 'evidence-actions');
    actions.append(button('在对话里改这句', () => fill(`把这句改一下：「${row.text}」`), 'workspace-button workspace-secondary'),
      button('定位到写简历', () => {
        close(false); revealAfterPaint = row.path;
        callbacks.locate?.(row.text); frame()?.focus({preventScroll: true});
      }));
    card.append(actions);
    place(card, rect); card.focus({preventScroll: true});
    // Expansion stays inside the already positioned, scrollable card.
  }
  function validRect(rect) {
    return rect && ['left', 'right', 'top', 'bottom'].every(key => Number.isFinite(rect[key])) && rect.right >= rect.left && rect.bottom >= rect.top;
  }
  function receive(event) {
    if (!frame() || event.source !== frame().contentWindow) return;
    const message = event.data;
    if (!message || typeof message !== 'object') return;
    if (message.type === 'huhua-evidence-ready') {
      visiblePaths = new Set(list(message.paths).filter(path => typeof path === 'string'));
      sync();
      // Existing locate repaints the preview. Resolve the exact field after
      // that swap too: technical-line markup and repeated text cannot mislocate.
      if (revealAfterPaint && enabled) {
        send({type: 'huhua-evidence-reveal', path: revealAfterPaint});
        revealAfterPaint = null;
      }
      return;
    }
    if (message.type === 'huhua-evidence-dismiss') { close(); return; }
    if (!enabled || !['huhua-evidence-select', 'huhua-evidence-revealed'].includes(message.type) || !validRect(message.rect)) return;
    const row = visibleRows().find(row => row.path === message.path);
    if (!row) return;
    if (message.type === 'huhua-evidence-revealed') {
      const rect = screenRect(message.rect), host = $('workspace-body'), bounds = host.getBoundingClientRect();
      host.scrollTop += rect.top - bounds.top - 32;
      // Scrolling closes cards consistently; focus the located text instead.
      frame()?.focus({preventScroll: true});
      return;
    }
    show(row, message.rect);
  }
  function init(options) {
    callbacks = options;
    $('evidence-toggle').addEventListener('click', () => choose(!enabled));
    window.addEventListener('message', receive);
    window.addEventListener('resize', () => close());
    document.addEventListener('scroll', event => { if (!$('evidence-card').contains(event.target)) close(); }, true);
    document.addEventListener('pointerdown', event => {
      if (!$('evidence-card').contains(event.target) && !$('evidence-bar').contains(event.target)) close();
    });
    document.addEventListener('keydown', event => {
      if (!selected) return;
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
    }, true);
    $('evidence-card').addEventListener('keydown', event => {
      if (event.key !== 'Tab') return;
      const focusable = [...$('evidence-card').querySelectorAll('button,summary')].filter(el => !el.disabled && el.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && (document.activeElement === first || document.activeElement === $('evidence-card'))) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    });
  }
  window.HuhuaEvidence = {init, update, attach, close,
    // Opening a card moves focus from the iframe back to this window.
    isOpen: () => selected !== null,
    reset() { update({}, null, null, false); visiblePaths = null; },
    decorate(html) {
      const bridge = '<script src="/static/resume-evidence-preview.js?v=20261022-19a"></script>';
      return /<\/body>/i.test(html) ? html.replace(/<\/body>/i, bridge + '</body>') : html + bridge;
    }};
})();
