/* "本次修改" card under an assistant reply: per-experience before/after bullets, per-op receipts, one-click undo. */
(() => {
  'use strict';
  const FIELDS = {tech_stack: '技术栈', name: '名称', role: '角色', positioning: '项目定位', project_type: '项目性质', company: '公司', position: '职位', title: '职位', start_date: '开始时间', end_date: '结束时间', school: '学校', degree: '学历', major: '专业', highlights: '补充信息', summary: '说明', pr: 'PR', level: '等级', date: '日期'};
  const SECTIONS = {projects: '项目', work_experience: '工作 / 实习', education: '教育', skills: '技能', skill_groups: '技能', basic_info: '基本信息', certificates: '证书', self_evaluation: '个人总结', sections: '栏目设置', campus: '校园经历', open_source: '开源贡献', awards: '竞赛荣誉', summary: '定位', layout: '排版'};
  const MARKER = /^\s*(✅|⚠️?|❌)\s*/u;
  const cards = [];
  const text = value => typeof value === 'string' || typeof value === 'number' ? String(value) : '';
  const normalized = value => text(value).normalize('NFC').replace(/[\u200b\ufeff]/g, '').replace(/\s+/g, ' ').trim();
  function visible(value) {
    if (typeof value === 'string') return normalized(value) || null;
    if (Array.isArray(value)) { const rows = value.map(visible).filter(row => row !== null); return rows.length ? rows : null; }
    if (value == null || value === false) return null;
    if (typeof value !== 'object') return value;
    const internal = new Set(['item_id', 'source', 'sources', 'profile_refs', 'fact_ids', 'raw_notes', 'raw_description', 'facts']);
    const rows = Object.keys(value).sort().filter(key => !internal.has(key) && !key.startsWith('_')
      && !(key === 'description' && value.polished_bullets?.length)).map(key => [key, visible(value[key])]).filter(([, row]) => row !== null);
    return rows.length ? Object.fromEntries(rows) : null;
  }
  const node = (tag, content, className) => {
    const el = document.createElement(tag);
    if (content !== undefined) el.textContent = text(content);
    if (className) el.className = className;
    return el;
  };
  function bulletsOf(section, item) {
    if (!item || typeof item !== 'object') return [];
    const primary = section === 'projects' ? item.polished_bullets : item.bullets;
    const rows = Array.isArray(primary) ? primary : Array.isArray(item.polished_bullets) ? item.polished_bullets : Array.isArray(item.bullets) ? item.bullets : [];
    return rows.filter(row => typeof row === 'string' && row.trim());
  }
  const titleOf = (before, after) => {
    const item = after || before || {};
    return text(item.name || item.company || item.school) || '经历';
  };
  function receiptRows(summary) {
    return (Array.isArray(summary) ? summary : []).map(text).filter(Boolean).map(line => {
      const match = line.match(MARKER);
      const kind = !match ? 'note' : match[1] === '✅' ? 'ok' : match[1].startsWith('⚠') ? 'warn' : 'fail';
      return {kind, mark: match ? match[1] : '', body: match ? line.slice(match[0].length) : line};
    });
  }
  function describeItem(entry) {
    const section = entry.section, before = entry.before || null, after = entry.after || null;
    let tag = '改写';
    if (!before && after) tag = '新增';
    else if (before && !after) tag = '移除';
    else if (after?.hidden && !before?.hidden) tag = '转为备用';
    else if (!after?.hidden && before?.hidden) tag = '恢复展示';
    const old = bulletsOf(section, before), next = bulletsOf(section, after);
    const remaining = [...next];
    const removed = old.filter(line => {
      const index = remaining.findIndex(value => normalized(value) === normalized(line));
      if (index >= 0) { remaining.splice(index, 1); return false; }
      return true;
    });
    const pool = [...old];
    const rows = next.map(line => {
      const index = pool.findIndex(value => normalized(value) === normalized(line));
      if (index >= 0) { pool.splice(index, 1); return {kind: 'same', line}; }
      return {kind: 'add', line};
    });
    const fields = [];
    for (const [key, label] of Object.entries(FIELDS)) {
      const from = key === 'tech_stack' ? (before?.[key] || []).join('、') : text(before?.[key]);
      const to = key === 'tech_stack' ? (after?.[key] || []).join('、') : text(after?.[key]);
      if (normalized(from) !== normalized(to) && (before && after)) fields.push(`${label}：${from || '空'} → ${to || '空'}`);
    }
    return {tag, title: titleOf(before, after), removed, rows, fields};
  }
  function itemNode(entry, open) {
    const info = describeItem(entry);
    const details = node('details', undefined, 'change-item');
    if (open) details.open = true;
    const summary = node('summary');
    summary.append(node('span', info.title, 'change-item-title'), node('span', info.tag, 'change-item-tag change-tag-' + (info.tag === '新增' ? 'add' : info.tag === '移除' ? 'del' : 'edit')));
    details.append(summary);
    const body = node('div', undefined, 'change-item-body');
    info.fields.forEach(line => body.append(node('p', line, 'change-field')));
    const list = node('ul', undefined, 'change-bullets');
    info.removed.forEach(line => {
      const li = node('li', undefined, 'change-bullet change-bullet-removed');
      li.append(node('span', '删', 'change-sign'), node('del', line));
      list.append(li);
    });
    info.rows.forEach(row => {
      const li = node('li', undefined, 'change-bullet change-bullet-' + row.kind);
      li.append(node('span', row.kind === 'add' ? '新' : '', 'change-sign'), node('span', row.line));
      list.append(li);
    });
    if (list.childElementCount) body.append(list);
    details.append(body);
    return details;
  }
  function extraNotes(diff) {
    const notes = [];
    for (const entry of diff) {
      if (entry.item_id && ['projects', 'work_experience', 'education'].includes(entry.section)) continue;
      if (entry.field === 'order') notes.push(`${SECTIONS[entry.section] || '栏目'}顺序已调整`);
      else notes.push(`${SECTIONS[entry.section] || entry.section}已调整`);
    }
    return [...new Set(notes)];
  }
  function create(meta, options = {}) {
    if (!meta || typeof meta !== 'object') return null;
    const diff = (Array.isArray(meta.diff) ? meta.diff : []).filter(entry => entry && typeof entry === 'object'
      && JSON.stringify(visible(entry.before)) !== JSON.stringify(visible(entry.after)));
    const receipts = receiptRows(meta.change_summary).filter(row => diff.length || ['warn', 'fail'].includes(row.kind));
    const itemEntries = diff.filter(entry => entry.item_id && ['projects', 'work_experience', 'education'].includes(entry.section));
    const notes = extraNotes(diff);
    if (!itemEntries.length && !receipts.length && !notes.length) return null;
    const card = node('section', undefined, 'change-card');
    card.setAttribute('aria-label', '本次修改');
    const head = node('div', undefined, 'change-card-head');
    head.append(node('strong', '本次修改'), node('span', itemEntries.length ? `涉及 ${itemEntries.length} 段经历` : '', 'change-card-count'));
    card.append(head);
    if (receipts.length) {
      const ul = node('ul', undefined, 'change-receipts');
      receipts.forEach(row => {
        const li = node('li', undefined, 'change-receipt change-receipt-' + row.kind);
        if (row.mark) li.append(node('span', row.mark, 'change-receipt-mark'));
        li.append(node('span', row.body));
        ul.append(li);
      });
      card.append(ul);
    }
    itemEntries.forEach((entry, index) => card.append(itemNode(entry, index === 0)));
    if (notes.length) card.append(node('p', notes.join('；'), 'change-card-note'));
    const foot = node('div', undefined, 'change-card-foot');
    const status = node('span', undefined, 'change-card-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const state = {card, button: null, status, done: false, busy: false};
    if (meta.can_undo !== false && options.session && itemEntries.length + notes.length) {
      const button = node('button', '撤销这次修改', 'change-undo'); button.type = 'button';
      state.button = button;
      button.addEventListener('click', () => undo(state, options));
      foot.append(button);
    }
    foot.append(status);
    card.append(foot);
    cards.forEach(old => supersede(old));
    cards.push(state);
    return card;
  }
  function supersede(state) {
    if (state.done || !state.button || state.button.dataset.superseded) return;
    state.button.dataset.superseded = '1'; state.button.disabled = true;
    state.status.textContent = '之后又有新的修改，只能撤销最近一次。';
  }
  async function undo(state, options) {
    if (state.busy || state.done || state.button?.disabled) return;
    if (options.busy?.()) { state.status.textContent = '正在回复中，稍后再撤销。'; return; }
    const session = options.session();
    state.busy = true; state.button.disabled = true; state.status.textContent = '正在撤销…';
    try {
      const current = await fetch('/api/resume/current?session_id=' + encodeURIComponent(session));
      if (!current.ok) throw Object.assign(new Error('read'), {code: current.status});
      const revision = (await current.json()).revision;
      const response = await fetch('/api/resume/session/' + encodeURIComponent(session) + '/versions/undo', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expected_revision: revision}),
      });
      if (!response.ok) throw Object.assign(new Error('undo'), {code: response.status});
      state.done = true; state.card.classList.add('change-card-undone');
      state.button.remove(); state.button = null;
      state.status.textContent = '已撤销，右侧预览已恢复到修改前。';
      await options.onUndone?.();
    } catch (error) {
      const code = error.code;
      state.status.textContent = code === 409 ? '简历在此期间有变化，已载入最新版本，请确认后再撤销。'
        : code === 503 ? '撤销暂时失败，当前版本未更改，请稍后重试。'
        : code === 404 ? '会话不存在或已清除。' : '撤销没有成功，当前版本未更改，请重试。';
      if (code === 409) options.refresh?.();
      if (state.button) state.button.disabled = code === 404 || Boolean(state.button.dataset.superseded);
    } finally { state.busy = false; }
  }
  function reset() { cards.length = 0; }
  window.HuhuaChangeCard = {create, reset};
})();
