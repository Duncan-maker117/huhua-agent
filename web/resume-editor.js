(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const main = $('resume-main');
  const editor = $('form-editor');
  const frame = $('preview-frame');
  const previewScroll = $('preview-scroll');
  const previewPage = $('preview-page');
  const status = $('render-status');
  const controls = new Map();
  const pendingValues = new Map();
  const builtinSections = [
    {id: 'education', kind: 'education', title: '教育背景'},
    {id: 'work_experience', kind: 'work_experience', title: '实习经历'},
    {id: 'projects', kind: 'projects', title: '项目经历'},
    {id: 'open_source', kind: 'open_source', title: '开源贡献'},
    {id: 'awards', kind: 'awards', title: '竞赛荣誉'},
    {id: 'skills', kind: 'skills', title: '技能证书'},
    {id: 'certificates', kind: 'certificates', title: '证书'},
    {id: 'self_evaluation', kind: 'self_evaluation', title: '自我评价'},
  ];
  const state = {
    data: null, templates: [], template: null, revision: 0,
    request: 0, controller: null, timer: null, ready: false,
    frameRevision: -1, structureRevision: 0, height: 1123, previewHover: null,
    editorHover: null, focused: null, exportBusy: false, exportObjectUrl: null, exportFormat: null,
    draggedSection: null, undoSection: null,
    session: null, mode: null, serverRevision: null, canSave: false,
    savedVersion: 0, saveTimer: null, saving: null, saveFailed: false,
    conflict: false, recovery: null, backupAvailable: true,
    sessionInvalid: false, requireAccount: true, sampleSource: null, creatingDraft: false, createdDraftSession: null,
  };
  const removedSections = new Map();
  const itemGroups = ['projects', 'education', 'work_experience', 'open_source', 'awards'];
  const pendingRemovedItems = new Map();
  let trackedItemIds = new Set(), removalSequence = 0;
  const sampleReadOnly = () => state.mode === 'sample' && state.requireAccount;
  const itemIds = (data) => new Set(itemGroups.flatMap(group => (data?.[group] || []).map(item => item.item_id).filter(id => typeof id === 'string' && id)));
  function trackItemChanges() {
    const current = itemIds(state.data);
    for (const id of trackedItemIds) if (!current.has(id)) pendingRemovedItems.set(id, ++removalSequence);
    for (const id of current) pendingRemovedItems.delete(id);
    trackedItemIds = current;
  }
  function resumeRequestUrl(path, {interactive = false, pending = false, exporting = false} = {}) {
    const query = new URLSearchParams();
    if (interactive) query.set('interactive', 'true');
    if (exporting) query.set('export', 'true');
    if (state.mode === 'personal' && state.session) {
      query.set('session_id', state.session);
      if (pending) for (const id of pendingRemovedItems.keys()) query.append('removed_item_ids', id);
    }
    const suffix = query.toString();
    return path + (suffix ? '?' + suffix : '');
  }
  const requestData = () => sampleReadOnly() ? state.sampleSource : state.data;
  async function fetchWithTimeout(url, options, readResponse, timeout = 30000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try { return await readResponse(await fetch(url, {...options, signal: controller.signal})); }
    finally { clearTimeout(timer); }
  }
  function mergeReturnedItemIds(returned, submitted, references) {
    // Attach only server metadata to the same live objects. A response must not
    // replace text typed after its request, or revive an item deleted meanwhile.
    for (const group of itemGroups) for (const [index, sent] of (submitted[group] || []).entries()) {
      if (sent.item_id) continue;
      const matches = (returned?.[group] || []).filter(item => typeof item.item_id === 'string' && item.item_id && Object.keys(sent).filter(key => key !== 'item_id').every(key => JSON.stringify(item[key]) === JSON.stringify(sent[key])));
      if (matches.length !== 1) continue;
      const id = matches[0].item_id, live = references[group][index];
      if ((state.data[group] || []).includes(live) && !live.item_id) {
        live.item_id = id; trackedItemIds.add(id); pendingRemovedItems.delete(id);
      } else if (!(state.data[group] || []).includes(live) && !itemIds(state.data).has(id)) {
        pendingRemovedItems.set(id, ++removalSequence);
      }
    }
  }
  const escapeKey = (key) => String(key).replace(/~/g, '~0').replace(/\//g, '~1');
  const pointer = (...keys) => '/' + keys.map(escapeKey).join('/');
  const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  const element = (tag, className, content) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = content;
    return node;
  };
  const button = (label, className, action) => {
    const node = element('button', className, label);
    node.type = 'button';
    node.addEventListener('click', action);
    return node;
  };
  const setStatus = (message, error = false) => {
    status.textContent = message;
    status.classList.toggle('error', error);
  };

  function setSaveStatus(message, error = false) {
    $('save-status').textContent = message;
    $('save-bar').classList.toggle('error', error);
    $('btn-retry-save').hidden = !state.saveFailed || state.conflict || !state.canSave;
    $('btn-load-latest').hidden = !state.conflict;
    $('btn-download-draft').hidden = !state.data || state.mode !== 'personal' || (!state.saveFailed && state.savedVersion === state.revision);
  }

  // Recovery is deliberately memory-only. Leaving with unsaved changes warns below.
  function keepBackup() {
    if (state.mode !== 'personal' || !state.session || !state.data || state.sessionInvalid) return;
    state.recovery = {session: state.session, base_revision: state.serverRevision,
      data: structuredClone(state.data), removed_item_ids: [...pendingRemovedItems.keys()], saved_at: new Date().toISOString()};
  }
  function clearBackup() { state.recovery = null; }

  function queueSave() {
    if (state.mode !== 'personal') return;
    keepBackup();
    if (window.HuhuaAccount?.claimPending()) { setSaveStatus('当前体验待保存到账号，编辑内容仍在本页，请重试保留当前对话。', true); return; }
    state.saveFailed = false;
    setSaveStatus(state.canSave ? '有修改，正在保存到当前会话…' : '暂时不能保存到会话，请下载草稿备份。', !state.canSave);
    clearTimeout(state.saveTimer);
    if (state.canSave && !state.conflict) state.saveTimer = setTimeout(flushSave, 500);
    else { state.saveFailed = true; setSaveStatus(state.conflict ? '会话内容已更新；你的修改仍在本页，请先下载备份。' : '暂时不能保存到会话，请下载草稿备份。', true); }
  }

  async function flushSave() {
    if (window.HuhuaAccount?.claimPending()) return false;
    clearTimeout(state.saveTimer);
    if (state.mode !== 'personal' || state.savedVersion === state.revision) return true;
    if (state.saving) return state.saving;
    if (!state.canSave || state.conflict) return false;
    state.saving = (async () => {
      try {
        while (state.savedVersion < state.revision) {
          const version = state.revision;
          const session = state.session;
          const snapshot = JSON.parse(JSON.stringify(state.data));
          const references = Object.fromEntries(itemGroups.map(group => [group, [...(state.data[group] || [])]]));
          const removedSnapshot = new Map(pendingRemovedItems);
          if (removedSnapshot.size > 300) throw new Error('本次删除的经历条目过多，请减少删除数量后再保存。');
          setSaveStatus('正在保存到当前会话…');
          // Saves are serial and are never aborted by another keystroke.
          const {response, result} = await fetchWithTimeout('/api/resume/current', {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({session_id: session, expected_revision: state.serverRevision, resume_data: snapshot, removed_item_ids: [...removedSnapshot.keys()]}),
          }, async response => {
            let result;
            try { result = await response.json(); } catch (error) { if (error.name === 'AbortError') throw error; result = {}; }
            return {response, result};
          });
          if (!response.ok) {
            state.conflict = response.status === 409;
            if (response.status === 404) { state.canSave = false; state.sessionInvalid = true; }
            throw new Error(result.detail?.message || (state.conflict ? '会话内容已更新，请保留草稿后载入最新内容。' : '保存失败，请重试或下载草稿备份。'));
          }
          if (state.session !== session || state.mode !== 'personal' || !state.data) return false;
          if (!result.saved || !result.revision) throw new Error('保存结果未确认，请重试或下载草稿备份。');
          for (const [id, sequence] of removedSnapshot) if (pendingRemovedItems.get(id) === sequence) pendingRemovedItems.delete(id);
          if (result.data) mergeReturnedItemIds(result.data, snapshot, references);
          state.serverRevision = result.revision;
          state.savedVersion = version;
          state.saveFailed = false;
          if (state.savedVersion < state.revision) keepBackup();
        }
        clearBackup();
        setSaveStatus(window.HuhuaAccount?.guest() ? '当前修改已临时保存。' + window.HuhuaAccount.guestNotice() : '已保存到当前会话，聊天核对和导出使用这份内容。');
        return true;
      } catch (error) {
        state.saveFailed = true;
        if (state.sessionInvalid) clearBackup();
        else keepBackup();
        setSaveStatus(error.name === 'AbortError' ? '保存等待超时，结果尚未确认。当前修改仍在本页，请重试或下载备份。' : error.message.includes('fetch') ? '连接已断开，当前修改尚未保存，仅留在本页。关闭前请重试或下载备份。' : error.message, true);
        return false;
      } finally { state.saving = null; }
    })();
    return state.saving;
  }

  function downloadDraft() {
    if (window.HuhuaAccount?.requireLogin('登录后可以下载简历，并保留当前草稿和对话。')) return false;
    if (!state.data) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(state.data, null, 2)], {type: 'application/json'}));
    const link = element('a');
    link.href = url;
    link.download = '简历-未保存草稿.json';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return true;
  }
  $('btn-download-draft').addEventListener('click', downloadDraft);
  $('btn-retry-save').addEventListener('click', flushSave);
  $('btn-load-latest').addEventListener('click', () => {
    // Preserve a concrete copy before deliberately replacing the current page.
    if (!downloadDraft()) return;
    clearBackup();
    state.savedVersion = state.revision;
    location.reload();
  });
  $('back-to-chat').addEventListener('click', async (event) => {
    if (state.mode !== 'personal' || state.savedVersion === state.revision) return;
    event.preventDefault();
    if (await flushSave()) location.href = $('back-to-chat').href;
  });
  window.addEventListener('huhua-account-reset', () => { clearExportFile(); $('export-result').hidden = true; state.mode = null; state.data = null; state.recovery = null; state.createdDraftSession = null; pendingRemovedItems.clear(); trackedItemIds.clear(); clearTimeout(state.saveTimer); });
  window.addEventListener('beforeunload', (event) => {
    if (state.mode !== 'personal' || state.savedVersion === state.revision) return;
    keepBackup();
    event.preventDefault(); event.returnValue = '';
  });

  function renderVerificationNotes() {
    const card = $('verification-card');
    const notes = state.data?.verification_notes || [];
    card.replaceChildren();
    card.hidden = !notes.length;
    if (!notes.length) return;
    card.append(element('strong', '', '仍为待核对草稿'), element('p', '', '以下信息尚待确认。请核对并修改对应字段；提示不会打印进简历。'));
    notes.forEach((note, index) => {
      const item = element('div', 'verification-item');
      item.append(element('p', '', note), button('已核对，移除此提示', 'text-button', () => {
        state.data.verification_notes.splice(index, 1);
        renderVerificationNotes();
        changed();
      }));
      card.append(item);
    });
  }

  function normaliseData(data) {
    const copy = JSON.parse(JSON.stringify(data || {}));
    if (!copy.basic_info || typeof copy.basic_info !== 'object') copy.basic_info = {};
    for (const key of ['education', 'work_experience', 'projects', 'open_source', 'awards', 'skills', 'certificates']) {
      if (!Array.isArray(copy[key])) copy[key] = [];
    }
    if (!copy.skill_groups || Array.isArray(copy.skill_groups) || typeof copy.skill_groups !== 'object') copy.skill_groups = {};
    for (const key of Object.keys(copy.skill_groups)) {
      if (!Array.isArray(copy.skill_groups[key])) delete copy.skill_groups[key];
    }
    for (const item of copy.work_experience) if (!Array.isArray(item.bullets)) item.bullets = [];
    for (const item of copy.projects) if (!Array.isArray(item.polished_bullets)) item.polished_bullets = [];
    for (const kind of ['open_source', 'awards']) for (const item of copy[kind]) {
      if (!Array.isArray(item.bullets)) item.bullets = [];
      if (!Array.isArray(item.links)) item.links = [];
    }
    if (!Array.isArray(copy.basic_info.links)) copy.basic_info.links = [];
    if (!Array.isArray(copy.verification_notes)) copy.verification_notes = [];
    if (!Array.isArray(copy.sections)) {
      copy.sections = builtinSections.map((section) => ({...section, content: '', title: section.kind === 'projects' ? copy.experience_section_title || section.title : section.title}));
    }
    return copy;
  }

  function setValue(path, value) {
    if (sampleReadOnly()) return;
    const keys = path.slice(1).split('/').map((key) => key.replace(/~1/g, '/').replace(/~0/g, '~'));
    let parent = state.data;
    for (const key of keys.slice(0, -1)) {
      if (!parent || !own(parent, key)) return;
      parent = parent[key];
    }
    if (!parent || typeof parent !== 'object') return;
    Object.defineProperty(parent, keys[keys.length - 1], {value, writable: true, enumerable: true, configurable: true});
  }

  function post(message) {
    if (state.ready) frame.contentWindow.postMessage(message, '*');
  }

  function changed(path, value) {
    if (sampleReadOnly()) return;
    trackItemChanges();
    state.revision += 1;
    state.controller?.abort();
    setStatus('正在更新');
    if (path) {
      pendingValues.set(path, {revision: state.revision, value});
      post({type: 'resume-field-value', path, value});
    }
    clearTimeout(state.timer);
    state.timer = setTimeout(renderPreview, 180);
    queueSave();
  }

  function changeStructure(action) {
    if (sampleReadOnly()) return;
    post({type: 'resume-field-active', path: null, reveal: false});
    state.ready = false;
    state.structureRevision = state.revision + 1;
    action();
    pendingValues.clear();
    state.previewHover = null;
    state.editorHover = null;
    state.focused = null;
    buildForm();
    changed();
  }

  function field(container, label, path, value, options = {}) {
    const wrapper = element('div', 'field' + (options.full ? ' full' : ''));
    wrapper.dataset.fieldPath = path;
    const name = element('label', '', label);
    const input = element(options.multiline ? 'textarea' : 'input');
    input.id = 'resume-field-' + controls.size;
    input.dataset.inputPath = path;
    input.value = typeof value === 'string' ? value : '';
    if (!options.multiline) input.type = 'text';
    else input.rows = options.rows || 3;
    if (options.placeholder) input.placeholder = options.placeholder;
    if (options.autocomplete) input.autocomplete = options.autocomplete;
    if (options.maxLength) input.maxLength = options.maxLength;
    name.htmlFor = input.id;
    wrapper.append(name, input);
    container.append(wrapper);
    controls.set(path, {wrapper, input});
    input.addEventListener('input', () => {
      setValue(input.dataset.inputPath, input.value);
      options.onInput?.(input.value);
      changed(input.dataset.inputPath, input.value);
    });
    return wrapper;
  }

  function section(title, meta, index, openStates) {
    const details = element('details', 'edit-section');
    const id = meta?.id || 'basic-info';
    details.dataset.sectionId = id;
    details.open = openStates?.get(id) ?? true;
    const summary = element('summary', 'section-summary');
    const caption = element('span', 'section-caption', title || '未命名栏目');
    if (meta) {
      const handle = button('⠿', 'section-drag-handle', () => {});
      handle.draggable = true;
      handle.setAttribute('aria-label', '拖拽调整栏目顺序');
      handle.title = '拖拽调整栏目顺序';
      summary.append(handle);
      const actions = element('span', 'section-tools');
      const rename = button('改名', 'section-tool', () => {
        details.open = true;
        revealControl(pointer('sections', index, 'title'), true);
        controls.get(pointer('sections', index, 'title')).input.select();
      });
      const up = button('↑', 'section-tool', () => moveSection(id, -1));
      const down = button('↓', 'section-tool', () => moveSection(id, 1));
      up.setAttribute('aria-label', '上移栏目');
      down.setAttribute('aria-label', '下移栏目');
      up.disabled = index === 0;
      down.disabled = index === state.data.sections.length - 1;
      const remove = button('×', 'section-tool section-remove', () => {
        changeStructure(() => {
          state.undoSection = {section: {...meta}, index};
          if (meta.kind !== 'custom') removedSections.set(meta.kind, {...meta});
          state.data.sections.splice(index, 1);
        });
      });
      remove.setAttribute('aria-label', '删除栏目');
      remove.title = '删除此栏目';
      actions.append(rename, up, down, remove);
      summary.append(caption, actions);
      for (const control of [handle, rename, up, down, remove]) {
        control.addEventListener('click', (event) => { event.preventDefault(); event.stopPropagation(); });
      }
      handle.addEventListener('dragstart', (event) => {
        state.draggedSection = id;
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', id);
        details.classList.add('section-dragging');
      });
      handle.addEventListener('dragend', clearSectionDrag);
      details.addEventListener('dragover', (event) => {
        if (!state.draggedSection || state.draggedSection === id) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        const below = event.clientY > summary.getBoundingClientRect().top + summary.offsetHeight / 2;
        for (const node of editor.querySelectorAll('.drop-before, .drop-after')) node.classList.remove('drop-before', 'drop-after');
        details.classList.add(below ? 'drop-after' : 'drop-before');
      });
      details.addEventListener('dragleave', (event) => {
        if (!details.contains(event.relatedTarget)) details.classList.remove('drop-before', 'drop-after');
      });
      details.addEventListener('drop', (event) => {
        if (!state.draggedSection) return;
        event.preventDefault();
        const draggedId = state.draggedSection;
        const below = details.classList.contains('drop-after');
        clearSectionDrag();
        if (draggedId === id) return;
        changeStructure(() => {
          const sections = state.data.sections;
          const source = sections.findIndex((item) => item.id === draggedId);
          if (source < 0) return;
          const [moving] = sections.splice(source, 1);
          const target = sections.findIndex((item) => item.id === id);
          sections.splice(target + (below ? 1 : 0), 0, moving);
        });
        focusSection(draggedId);
      });
    } else summary.append(caption);
    details.append(summary);
    const body = element('div', 'section-body');
    details.append(body);
    editor.append(details);
    if (meta) {
      field(body, '栏目标题', pointer('sections', index, 'title'), meta.title, {
        maxLength: 100, placeholder: meta.kind === 'custom' ? '留空只显示正文内容' : '填写栏目名称',
        onInput: (value) => { caption.textContent = value || '未命名栏目'; },
      });
    }
    return body;
  }

  function clearSectionDrag() {
    state.draggedSection = null;
    for (const node of editor.querySelectorAll('.section-dragging, .drop-before, .drop-after')) node.classList.remove('section-dragging', 'drop-before', 'drop-after');
  }

  function focusSection(id, editTitle = false) {
    const index = state.data.sections.findIndex((item) => item.id === id);
    if (index < 0) return;
    const details = [...editor.querySelectorAll('.edit-section')].find((node) => node.dataset.sectionId === id);
    if (editTitle) {
      details.open = true;
      revealControl(pointer('sections', index, 'title'), true);
      controls.get(pointer('sections', index, 'title')).input.select();
    } else {
      details.querySelector('.section-drag-handle').focus({preventScroll: true});
      const box = details.querySelector('summary').getBoundingClientRect();
      const viewport = editor.getBoundingClientRect();
      if (box.top < viewport.top || box.bottom > viewport.bottom) editor.scrollTop += box.top - viewport.top - 20;
    }
  }

  function moveSection(id, offset) {
    const index = state.data.sections.findIndex((item) => item.id === id);
    const target = index + offset;
    if (index < 0 || target < 0 || target >= state.data.sections.length) return;
    changeStructure(() => {
      const [moving] = state.data.sections.splice(index, 1);
      state.data.sections.splice(target, 0, moving);
    });
    focusSection(id);
  }

  function buildSectionActions() {
    const footer = element('div', 'section-actions');
    footer.append(element('p', 'section-instructions', '拖动 ⠿ 调整栏目顺序，也可用 ↑ ↓ 移动。'));
    if (state.undoSection) {
      const notice = element('div', 'section-undo');
      notice.setAttribute('role', 'status');
      notice.append(element('span', '', `已删除「${state.undoSection.section.title || '未命名栏目'}」`));
      notice.append(button('撤销', 'text-button', () => {
        if (state.data.sections.length >= 30) { setStatus('最多添加 30 个栏目，请先移除一个', true); return; }
        const removed = state.undoSection;
        if (state.data.sections.some((item) => item.id === removed.section.id || (item.kind !== 'custom' && item.kind === removed.section.kind))) {
          state.undoSection = null;
          buildForm();
          return;
        }
        changeStructure(() => {
          state.data.sections.splice(Math.min(removed.index, state.data.sections.length), 0, removed.section);
          state.undoSection = null;
        });
        focusSection(removed.section.id);
      }));
      footer.append(notice);
    }
    const custom = button('＋ 添加自定义栏目', 'add-button', () => {
      const id = 'custom-' + crypto.randomUUID();
      changeStructure(() => state.data.sections.push({id, kind: 'custom', title: '自定义栏目', content: ''}));
      focusSection(id, true);
    });
    custom.disabled = state.data.sections.length >= 30;
    footer.append(custom);
    const missing = builtinSections.filter((builtin) => !state.data.sections.some((item) => item.kind === builtin.kind));
    if (missing.length) {
      const restore = element('details', 'section-restore');
      restore.append(element('summary', '', '添加已有栏目'));
      const options = element('div', 'section-restore-options');
      for (const builtin of missing) {
        const option = button(builtin.title, 'secondary-button', () => {
          changeStructure(() => {
            const restored = removedSections.get(builtin.kind) || {...builtin, content: '', title: builtin.kind === 'projects' ? state.data.experience_section_title || builtin.title : builtin.title};
            state.data.sections.push({...restored});
            if (state.undoSection?.section.kind === builtin.kind) state.undoSection = null;
          });
          focusSection(builtin.id, true);
        });
        option.disabled = state.data.sections.length >= 30;
        options.append(option);
      }
      restore.append(options);
      footer.append(restore);
    }
    editor.append(footer);
  }

  function itemEditor(container, title, removeAction) {
    const item = element('div', 'item-editor');
    const heading = element('div', 'item-heading');
    heading.append(element('span', 'item-title', title), button('删除', 'text-button remove', () => changeStructure(removeAction)));
    item.append(heading);
    container.append(item);
    return item;
  }

  function stringList(container, values, keys, label, multiline = false, afterRemove = () => {}) {
    const list = element('div', 'list-editor');
    values.forEach((value, index) => {
      const row = element('div', 'list-field-row');
      field(row, `${label} ${index + 1}`, pointer(...keys, index), value, {multiline, rows: 3});
      const remove = button('×', 'remove-line', () => changeStructure(() => { values.splice(index, 1); afterRemove(); }));
      remove.setAttribute('aria-label', `删除${label} ${index + 1}`);
      row.append(remove);
      list.append(row);
    });
    list.append(button(`＋ 添加${label}`, 'add-button', () => changeStructure(() => values.push(''))));
    container.append(list);
  }

  function buildForm() {
    const scrollTop = editor.scrollTop;
    const openStates = new Map([...editor.querySelectorAll('.edit-section')].map((node) => [node.dataset.sectionId, node.open]));
    controls.clear();
    editor.replaceChildren();
    const basic = section('基本信息', null, -1, openStates);
    buildBasicContent(basic);
    const builders = {
      education: buildEducationContent, work_experience: buildWorkContent,
      projects: buildProjectsContent, skills: buildSkillsContent,
      open_source: body => buildContributionContent(body, 'open_source'),
      awards: body => buildContributionContent(body, 'awards'),
      certificates: buildCertificatesContent, self_evaluation: buildEvaluationContent,
    };
    state.data.sections.forEach((meta, index) => {
      const body = section(meta.title, meta, index, openStates);
      if (meta.kind === 'custom') {
        field(body, '正文内容', pointer('sections', index, 'content'), meta.content, {
          multiline: true, rows: 6, maxLength: 20000,
          placeholder: '写下竞赛获奖、校园活动、开源贡献或其他想展示的内容，可换行。',
        });
      } else builders[meta.kind]?.(body);
    });
    buildSectionActions();
    if (sampleReadOnly()) {
      editor.querySelectorAll('input,textarea,select,button').forEach(control => { control.disabled = true; });
      editor.querySelectorAll('[draggable]').forEach(control => { control.draggable = false; });
    }
    editor.scrollTop = scrollTop;
  }

  function buildBasicContent(basic) {
    const data = state.data;
    const basicGrid = element('div', 'field-grid');
    basic.append(basicGrid);
    for (const [key, label, full, autocomplete] of [
      ['name', '姓名', false, 'name'], ['phone', '电话', false, 'tel'],
      ['email', '邮箱', true, 'email'], ['location', '所在城市'],
      ['hometown', '籍贯'], ['objective', '求职意向', true],
      ['availability', '可实习时间', true],
      ['gender', '性别'], ['birthday', '出生年月'], ['age', '年龄'],
      ['ethnicity', '民族'], ['political', '政治面貌'], ['height', '身高'],
    ]) field(basicGrid, label, pointer('basic_info', key), data.basic_info[key], {full, autocomplete});
    buildLinksContent(basic, data.basic_info.links, ['basic_info', 'links']);
    if (data.basic_info.photo) {
      const actions = element('div', 'photo-actions');
      actions.append(button('移除头像', 'text-button remove', () => changeStructure(() => { data.basic_info.photo = ''; })));
      basic.append(actions);
    }
  }

  function buildEducationContent(education) {
    const data = state.data;
    data.education.forEach((item, index) => {
      const box = itemEditor(education, `教育经历 ${index + 1}`, () => data.education.splice(index, 1));
      const grid = element('div', 'field-grid');
      box.append(grid);
      for (const [key, label, full] of [['school', '学校', true], ['major', '专业'], ['degree', '学历'], ['start_date', '开始时间'], ['end_date', '结束时间']]) {
        field(grid, label, pointer('education', index, key), item[key], {full});
      }
      field(grid, '课程、成绩与荣誉', pointer('education', index, 'highlights'), item.highlights, {full: true, multiline: true});
    });
    education.append(button('＋ 添加教育经历', 'add-button', () => changeStructure(() => data.education.push({school: '', major: '', degree: '', start_date: '', end_date: '', highlights: ''}))));
  }

  function buildWorkContent(work) {
    const data = state.data;
    data.work_experience.forEach((item, index) => {
      const box = itemEditor(work, `经历 ${index + 1}`, () => data.work_experience.splice(index, 1));
      const grid = element('div', 'field-grid');
      box.append(grid);
      for (const [key, label, full] of [['company', '公司 / 组织', true], ['title', '岗位', true], ['start_date', '开始时间'], ['end_date', '结束时间']]) {
        field(grid, label, pointer('work_experience', index, key), item[key], {full});
      }
      stringList(box, item.bullets, ['work_experience', index, 'bullets'], '经历要点', true);
    });
    work.append(button('＋ 添加工作 / 实习经历', 'add-button', () => changeStructure(() => data.work_experience.push({company: '', title: '', start_date: '', end_date: '', bullets: ['']}))));
  }

  function buildProjectsContent(projects) {
    const data = state.data;
    data.projects.forEach((item, index) => {
      const box = itemEditor(projects, `项目 ${index + 1}`, () => data.projects.splice(index, 1));
      const grid = element('div', 'field-grid');
      box.append(grid);
      for (const [key, label, full] of [['name', '项目名称', true], ['role', '担任角色', true], ['start_date', '开始时间'], ['end_date', '结束时间']]) {
        field(grid, label, pointer('projects', index, key), item[key], {full});
      }
      if (item.polished_bullets.length) {
        stringList(box, item.polished_bullets, ['projects', index, 'polished_bullets'], '项目要点', true, () => {
          if (!item.polished_bullets.length) item.description = '';
        });
        box.append(button('改为整段描述', 'text-button', () => changeStructure(() => {
          item.description = item.polished_bullets.join('\n');
          item.polished_bullets = [];
        })));
      } else {
        field(grid, '项目描述', pointer('projects', index, 'description'), item.description, {full: true, multiline: true, rows: 4});
        box.append(button('改为分条要点', 'text-button', () => changeStructure(() => {
          item.polished_bullets = item.description ? [item.description] : [''];
          item.description = '';
        })));
      }
    });
    projects.append(button('＋ 添加项目', 'add-button', () => changeStructure(() => data.projects.push({name: '', role: '', start_date: '', end_date: '', description: '', polished_bullets: []}))));
  }

  function buildLinksContent(container, links, keys) {
    links.forEach((link, index) => {
      const box = itemEditor(container, `链接 ${index + 1}`, () => links.splice(index, 1));
      const grid = element('div', 'field-grid'); box.append(grid);
      field(grid, '链接名称', pointer(...keys, index, 'text'), link.text);
      field(grid, '网址 / 账号', pointer(...keys, index, 'url'), link.url, {full: true});
    });
    container.append(button('＋ 添加链接', 'add-button', () => changeStructure(() => links.push({text: '', url: ''}))));
  }

  function buildContributionContent(container, kind) {
    const rows = state.data[kind], openSource = kind === 'open_source';
    rows.forEach((item, index) => {
      const box = itemEditor(container, `${openSource ? '开源贡献' : '竞赛荣誉'} ${index + 1}`, () => rows.splice(index, 1));
      const grid = element('div', 'field-grid'); box.append(grid);
      const fields = openSource ? [['name', '仓库 / 项目名'], ['summary', '简介（如星数）'], ['pr', 'PR 号或链接'], ['start_date', '开始时间'], ['end_date', '结束时间']]
        : [['name', '名称'], ['level', '级别 / 名次'], ['date', '时间（可选）']];
      for (const [key, label] of fields) field(grid, label, pointer(kind, index, key), item[key], {full: true});
      stringList(box, item.bullets, [kind, index, 'bullets'], openSource ? '本人贡献与结果' : '补充说明', true);
      buildLinksContent(box, item.links, [kind, index, 'links']);
    });
    container.append(button(`＋ 添加${openSource ? '开源贡献' : '竞赛荣誉'}`, 'add-button', () => changeStructure(() => rows.push(
      openSource ? {name: '', summary: '', pr: '', start_date: '', end_date: '', bullets: [], links: []}
        : {name: '', level: '', date: '', bullets: [], links: []}))));
  }

  function buildSkillsContent(skills) {
    const data = state.data;
    const groups = Object.entries(data.skill_groups);
    if (groups.length) {
      for (const [initialName, values] of groups) {
        let name = initialName;
        const group = element('div', 'group-editor');
        let path = pointer('skill_groups', name);
        group.dataset.fieldPath = path;
        const heading = element('div', 'item-heading');
        heading.append(element('span', 'item-title', '技能分组'), button('删除分组', 'text-button remove', () => changeStructure(() => {
          delete data.skill_groups[name];
          if (!Object.keys(data.skill_groups).length) data.skills = [];
        })));
        group.append(heading);
        const nameField = element('div', 'field');
        nameField.dataset.fieldPath = path;
        const nameLabel = element('label', '', '分组名称');
        const nameInput = element('input');
        nameInput.type = 'text';
        nameInput.id = 'resume-field-' + controls.size;
        nameInput.value = name;
        nameInput.setAttribute('aria-label', '分组名称');
        nameLabel.htmlFor = nameInput.id;
        nameField.append(nameLabel, nameInput);
        group.append(nameField);
        controls.set(path, {wrapper: nameField, input: nameInput});
        nameInput.addEventListener('input', () => {
          const next = nameInput.value;
          if (!next.trim() || (next !== name && own(data.skill_groups, next))) {
            nameInput.setCustomValidity(!next.trim() ? '请填写分组名称' : '分组名称已存在');
            return;
          }
          nameInput.setCustomValidity('');
          if (next === name) return;
          const newGroups = {};
          for (const [key, items] of Object.entries(data.skill_groups)) {
            Object.defineProperty(newGroups, key === name ? next : key, {value: items, writable: true, enumerable: true, configurable: true});
          }
          data.skill_groups = newGroups;
          const nextPath = pointer('skill_groups', next);
          for (const [oldPath, control] of [...controls]) {
            if (oldPath !== path && !oldPath.startsWith(path + '/')) continue;
            const newPath = nextPath + oldPath.slice(path.length);
            controls.delete(oldPath);
            controls.set(newPath, control);
            control.wrapper.dataset.fieldPath = newPath;
            if (control.input.dataset.inputPath) control.input.dataset.inputPath = newPath;
          }
          group.dataset.fieldPath = nextPath;
          state.focused = nextPath;
          if (state.editorHover === path || state.editorHover?.startsWith(path + '/')) state.editorHover = nextPath + state.editorHover.slice(path.length);
          name = next;
          path = nextPath;
          pendingValues.clear();
          state.ready = false;
          state.structureRevision = state.revision + 1;
          changed();
        });
        nameInput.addEventListener('blur', () => { if (!nameInput.checkValidity()) { nameInput.value = name; nameInput.setCustomValidity(''); } });
        stringList(group, values, ['skill_groups', name], '技能');
        skills.append(group);
      }
      skills.append(button('改为不分组技能', 'text-button', () => changeStructure(() => {
        data.skills = Object.entries(data.skill_groups).flatMap(([name, values]) => values.map((value) => `${name}：${value}`));
        data.skill_groups = {};
      })));
    } else {
      stringList(skills, data.skills, ['skills'], '技能');
    }
    skills.append(button('＋ 添加技能分组', 'add-button', () => {
      let name = '新分组';
      let index = 2;
      while (own(data.skill_groups, name)) name = `新分组 ${index++}`;
      changeStructure(() => {
        if (!Object.keys(data.skill_groups).length && data.skills.length) {
          Object.defineProperty(data.skill_groups, '技能', {value: [...data.skills], writable: true, enumerable: true, configurable: true});
        }
        data.skills = [];
        Object.defineProperty(data.skill_groups, name, {value: [''], writable: true, enumerable: true, configurable: true});
      });
    }));
  }

  function buildCertificatesContent(certificates) {
    const data = state.data;
    stringList(certificates, data.certificates, ['certificates'], '证书');
  }

  function buildEvaluationContent(evaluation) {
    const data = state.data;
    field(evaluation, '自我评价', pointer('self_evaluation'), data.self_evaluation, {multiline: true, rows: 4});
  }

  function revealControl(path, focus = false) {
    const control = controls.get(path);
    if (!control) return;
    for (let node = control.wrapper.parentElement; node && node !== editor; node = node.parentElement) {
      if (node.tagName === 'DETAILS') node.open = true;
    }
    if (focus) {
      main.classList.add('show-data');
      $('btn-toggle-data').textContent = '收起编辑';
      $('btn-toggle-data').setAttribute('aria-expanded', 'true');
      if (matchMedia('(max-width: 700px)').matches) mobileMode(true);
      control.input.focus({preventScroll: true});
    }
    const box = control.wrapper.getBoundingClientRect();
    const viewport = editor.getBoundingClientRect();
    if (box.top < viewport.top + 8 || box.bottom > viewport.bottom - 8) {
      editor.scrollTop += box.top - viewport.top - Math.min(60, viewport.height / 4);
    }
  }

  function highlightControls() {
    for (const [path, control] of controls) {
      control.wrapper.classList.toggle('linked', path === state.previewHover);
      control.wrapper.classList.toggle('focused', path === state.focused);
    }
  }

  function highlightPreview(reveal = false) {
    post({type: 'resume-field-active', path: state.editorHover || state.focused, reveal});
  }

  editor.addEventListener('mouseover', (event) => {
    const wrapper = event.target.closest('[data-field-path]');
    const path = wrapper?.dataset.fieldPath || null;
    if (path !== state.editorHover) {
      state.editorHover = path;
      highlightPreview();
    }
  });
  editor.addEventListener('mouseleave', () => { state.editorHover = null; highlightPreview(); });
  editor.addEventListener('focusin', (event) => {
    state.focused = event.target.closest('[data-field-path]')?.dataset.fieldPath || null;
    highlightControls();
    highlightPreview(true);
  });
  editor.addEventListener('focusout', () => {
    requestAnimationFrame(() => {
      state.focused = document.activeElement.closest?.('[data-field-path]')?.dataset.fieldPath || null;
      highlightControls();
      highlightPreview();
    });
  });

  window.addEventListener('message', (event) => {
    if (event.source !== frame.contentWindow || !event.data || typeof event.data !== 'object') return;
    const message = event.data;
    if (message.type === 'resume-preview-ready') {
      if (state.frameRevision < state.structureRevision) return;
      if (!Number.isFinite(message.height) || message.height < 1123 || message.height > 100000) return;
      state.ready = true;
      state.height = message.height;
      scalePreview();
      // Keystrokes can arrive while a new iframe document is loading.
      for (const [path, change] of pendingValues) {
        if (change.revision > state.frameRevision && controls.has(path)) {
          post({type: 'resume-field-value', path, value: change.value});
        }
      }
      highlightPreview();
      if (state.frameRevision === state.revision) setStatus('已实时更新');
    } else if (message.type === 'resume-field-hover') {
      if (!state.ready) return;
      if (message.path !== null && !controls.has(message.path)) return;
      state.previewHover = message.path;
      highlightControls();
      if (message.path) revealControl(message.path);
    } else if (message.type === 'resume-field-select' && state.ready && controls.has(message.path)) {
      revealControl(message.path, true);
    }
  });

  function scalePreview() {
    if (!previewScroll.clientWidth) return;
    const style = getComputedStyle(previewScroll);
    const width = previewScroll.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const scale = Math.min(1, Math.max(.1, width / 794));
    previewPage.style.width = `${794 * scale}px`;
    previewPage.style.height = `${state.height * scale}px`;
    frame.style.height = `${state.height}px`;
    frame.style.transform = `scale(${scale})`;
  }
  new ResizeObserver(scalePreview).observe(previewScroll);
  window.addEventListener('resize', scalePreview);

  async function responseError(response, fallback) {
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') return body.detail;
      if (body.detail?.message) return body.detail.message;
    } catch (_) { /* Non-JSON error responses use a plain, local message. */ }
    return fallback;
  }

  async function renderPreview() {
    if (window.HuhuaAccount?.claimPending()) return;
    if (!state.template || !state.data) return;
    clearTimeout(state.timer);
    state.controller?.abort();
    const controller = new AbortController();
    state.controller = controller;
    const revision = state.revision;
    const template = state.template.id;
    const request = ++state.request;
    setStatus('正在更新');
    try {
      const response = await fetch(resumeRequestUrl(`/api/resume/render/${encodeURIComponent(template)}`, {interactive:true, pending:true}), {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(requestData()), signal: controller.signal,
      });
      if (!response.ok) throw new Error(await responseError(response, '预览更新失败，请稍后重试'));
      const html = await response.text();
      if (revision !== state.revision || request !== state.request || template !== state.template.id) return;
      state.ready = false;
      state.previewHover = null;
      highlightControls();
      state.frameRevision = revision;
      frame.srcdoc = html;
    } catch (error) {
      if (error.name === 'AbortError' || revision !== state.revision || request !== state.request) return;
      setStatus('更新失败，继续编辑可重试', true);
      status.title = error.message;
    }
  }

  const templatePreferenceKey = () => 'huhua_resume_template:' + (state.session || 'sample');
  function restoreTemplate() {
    let selected;
    try { selected = localStorage.getItem(templatePreferenceKey()); } catch (_) { /* Presentation preference is optional. */ }
    return state.templates.find(template => template.id === selected) || state.templates[0];
  }
  function selectTemplate(template) {
    state.template = template;
    // Store presentation identifiers only, never resume text or account tokens.
    try { localStorage.setItem(templatePreferenceKey(), template.id); } catch (_) { /* Editing still works without browser storage. */ }
    $('current-tpl').textContent = template.name;
    for (const item of $('template-list').children) {
      const active = item.dataset.templateId === template.id;
      item.classList.toggle('active', active);
      item.setAttribute('aria-pressed', String(active));
    }
    renderPreview();
  }

  function mobileMode(edit) {
    main.classList.toggle('mobile-edit', edit);
    $('btn-mobile-preview').classList.toggle('active', !edit);
    $('btn-mobile-edit').classList.toggle('active', edit);
    $('btn-mobile-preview').setAttribute('aria-pressed', String(!edit));
    $('btn-mobile-edit').setAttribute('aria-pressed', String(edit));
    requestAnimationFrame(scalePreview);
  }
  $('btn-mobile-preview').addEventListener('click', () => mobileMode(false));
  $('btn-mobile-edit').addEventListener('click', () => mobileMode(true));
  $('btn-toggle-data').addEventListener('click', () => {
    const visible = main.classList.toggle('show-data');
    $('btn-toggle-data').textContent = visible ? '收起编辑' : '编辑内容';
    $('btn-toggle-data').setAttribute('aria-expanded', String(visible));
  });

  $('btn-upload-photo').addEventListener('click', () => $('photo-input').click());
  $('photo-input').addEventListener('change', async (event) => {
    const file = event.target.files[0];
    event.target.value = '';
    if (!file || !state.data || sampleReadOnly()) return;
    if (!['image/jpeg', 'image/png'].includes(file.type)) {
      setStatus('头像仅支持 JPG / PNG', true);
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setStatus('头像不能超过 5 MB', true);
      return;
    }
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      changeStructure(() => { state.data.basic_info.photo = dataUrl; });
    } catch (_) { setStatus('头像读取失败，请重新选择', true); }
  });

  const exportMenu = $('export-menu');
  function closeExportMenu() {
    exportMenu.hidden = true;
    $('btn-export').setAttribute('aria-expanded', 'false');
  }
  $('btn-export').addEventListener('click', () => {
    if (window.HuhuaAccount?.requireLogin('登录后即可导出这份简历，同时保留当前对话和个人信息。')) return;
    exportMenu.hidden = !exportMenu.hidden;
    $('btn-export').setAttribute('aria-expanded', String(!exportMenu.hidden));
  });
  document.addEventListener('click', (event) => { if (!event.target.closest('#export-wrap')) closeExportMenu(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeExportMenu(); });

  function clearExportFile() {
    if (state.exportObjectUrl) URL.revokeObjectURL(state.exportObjectUrl);
    state.exportObjectUrl = null;
    for (const id of ['export-download', 'export-open']) { $(id).hidden = true; $(id).removeAttribute('href'); }
  }
  function exportStatus(message, error = false) {
    $('export-result').hidden = false;
    $('export-result').classList.toggle('error', error);
    $('export-status').textContent = message;
  }
  $('btn-retry-export').addEventListener('click', () => exportResume(state.exportFormat));
  window.addEventListener('pagehide', event => { if (!event.persisted) clearExportFile(); });

  async function exportResume(format) {
    closeExportMenu();
    if (window.HuhuaAccount?.requireLogin('登录后即可导出这份简历，同时保留当前对话和个人信息。')) return;
    if (!state.data || !state.template || state.exportBusy || !['pdf', 'docx'].includes(format)) return;
    const template = encodeURIComponent(state.template.id);
    const session = state.session;
    const label = format === 'pdf' ? 'PDF' : 'Word';
    state.exportBusy = true;
    state.exportFormat = format;
    clearExportFile();
    $('btn-retry-export').hidden = true;
    $('btn-export').disabled = true;
    exportStatus('正在保存并生成 ' + label + '…');
    try {
      if (state.mode === 'personal' && !(await flushSave())) throw new Error('当前修改尚未保存。请重试保存或下载草稿备份后再导出。');
      const snapshot = JSON.stringify(requestData());
      const {response, blob} = await fetchWithTimeout(resumeRequestUrl(`/api/resume/export/${format}/${template}`), {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: snapshot,
      }, async response => {
        if (!response.ok) throw new Error(await responseError(response, '导出失败，请稍后重试'));
        return {response, blob: await response.blob()};
      }, 60000);
      if (state.session !== session || !state.data) return;
      const signature = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
      const valid = format === 'pdf' ? new TextDecoder().decode(signature) === '%PDF-' : signature[0] === 80 && signature[1] === 75 && signature[2] === 3 && signature[3] === 4;
      if (!valid) throw new Error(label + ' 文件内容异常，请重试；当前简历仍已保存。');
      let filename = format === 'pdf' ? '简历.pdf' : '简历-通用Word.docx';
      const match = (response.headers.get('Content-Disposition') || '').match(/filename\*=UTF-8''([^;]+)/i);
      if (match) { try { filename = decodeURIComponent(match[1]).replace(/[\x00-\x1f/\\]/g, '_'); } catch (_) { /* Use default filename. */ } }
      if (state.mode === 'sample') filename = '样例-' + filename;
      state.exportObjectUrl = URL.createObjectURL(blob);
      const link = $('export-download');
      link.href = state.exportObjectUrl; link.download = filename; link.textContent = '下载 ' + label; link.hidden = false;
      $('export-open').href = state.exportObjectUrl; $('export-open').hidden = false;
      exportStatus(label + ' 文件已生成。若未出现下载，请点击下方下载，或打开文件后保存。后续修改需重新导出。');
      link.click();
    } catch (error) {
      if (!state.data) return;
      exportStatus(error.name === 'AbortError' ? '导出等待超时，已保存的简历仍在。请重试或选择另一种格式。' : error.message.includes('fetch') ? '连接已断开，下载未完成。请检查网络后重试。' : error.message, true);
      $('btn-retry-export').hidden = false;
    } finally {
      state.exportBusy = false;
      $('btn-export').disabled = !state.data;
    }
  }
  for (const option of document.querySelectorAll('.export-opt')) option.addEventListener('click', () => exportResume(option.dataset.format));

  function activateData(data, mode) {
    state.data = normaliseData(data);
    state.mode = mode;
    state.sampleSource = mode === 'sample' ? structuredClone(data) : null;
    pendingRemovedItems.clear(); trackedItemIds = itemIds(state.data);
    state.revision += 1;
    state.savedVersion = state.revision;
    state.saveFailed = false;
    state.conflict = false;
    pendingValues.clear();
    removedSections.clear();
    state.undoSection = null;
    $('data-source').textContent = mode === 'sample' ? '样例' : '当前会话';
    $('btn-export').disabled = false;
    $('btn-export').textContent = mode === 'sample' ? '导出样例 ▾' : '导出 ▾';
    $('btn-upload-photo').disabled = sampleReadOnly();
    const notice = $('sample-notice');
    notice.hidden = mode !== 'sample';
    notice.replaceChildren();
    if (mode === 'sample') {
      notice.append(element('p', '', sampleReadOnly() ? '这是只读模板样例，可直接切换模板查看排版。新建个人草稿后填写自己的资料，登录后可导出。' : '这是样例，未保存到你的会话。这里的修改和导出只用于体验模板。'));
      const blank = button('新建我的空白草稿', 'text-button', startBlank);
      blank.disabled = !state.canSave && !state.requireAccount;
      notice.append(blank);
      setSaveStatus(sampleReadOnly() ? '只读样例：切换模板和预览不会保存个人简历。' : '样例模式：不会保存到你的会话。');
    } else setSaveStatus(state.canSave ? window.HuhuaAccount?.guest() ? window.HuhuaAccount.guestNotice() : '已读取当前会话，修改后自动保存。' : '会话保存暂时不可用；修改后请下载草稿备份。', !state.canSave);
    renderVerificationNotes();
    if (sampleReadOnly()) $('verification-card').querySelectorAll('button').forEach(control => { control.disabled = true; });
    buildForm();
    renderPreview();
  }

  async function startBlank() {
    if (state.creatingDraft) return;
    state.creatingDraft = true;
    try {
      if (!state.canSave) {
        if (!state.requireAccount) return;
        setStatus('正在新建个人草稿…');
        if (!state.createdDraftSession) {
          const created = await fetch('/api/chat/conversations', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
          if (!created.ok) throw new Error(await responseError(created, '新建对话失败，请重试。'));
          const conversation = await created.json();
          if (!conversation.session_id) throw new Error('新对话尚未确认，请重试。');
          state.createdDraftSession = conversation.session_id;
        }
        // Retrying a failed read reuses the explicitly created conversation.
        state.session = state.createdDraftSession;
        window.HuhuaAccount?.rememberSession(state.session);
        const query = new URLSearchParams(location.search); query.set('session', state.session);
        history.replaceState({}, '', location.pathname + '?' + query.toString());
        $('back-to-chat').href = '/?session=' + encodeURIComponent(state.session);
        const response = await fetch('/api/resume/current?session_id=' + encodeURIComponent(state.session));
        if (!response.ok) throw new Error(await responseError(response, '新对话已建立，草稿读取失败，请刷新后重试。'));
        const current = await response.json();
        state.serverRevision = current.revision || null; state.canSave = current.can_save === true && Boolean(state.serverRevision);
        if (!state.canSave) throw new Error('新对话暂时不能保存，请刷新后重试。');
        state.sessionInvalid = false;
      }
      activateData({verification_notes: []}, 'personal');
      if (state.template) selectTemplate(state.template);
      $('draft-recovery').hidden = true;
      // This explicit user action creates a saved draft; template preview does not.
      state.revision += 1; queueSave();
    } catch (error) { setStatus(error.message, true); }
    finally { state.creatingDraft = false; }
  }

  function showStartChoice() {
    state.data = null;
    state.mode = null;
    $('data-source').textContent = '尚无个人简历';
    $('btn-export').disabled = true;
    $('btn-upload-photo').disabled = true;
    setStatus('等待选择');
    setSaveStatus(state.canSave ? '当前会话还没有简历。请选择开始方式。' : '未连接可保存的会话。可查看样例，或回到聊天建立会话。', !state.canSave);
    const choice = element('div', 'start-choice');
    choice.append(element('h2', '', '开始编辑你的简历'), element('p', '', '样例只用于查看排版；空白草稿会保存到当前会话。'));
    const blank = button('新建空白草稿', 'secondary-button', startBlank);
    blank.disabled = !state.canSave && !state.requireAccount;
    choice.append(blank, button('查看模板样例', 'secondary-button', async () => {
      try {
        const response = await fetch('/api/resume/sample');
        if (!response.ok) throw new Error('样例加载失败');
        activateData(await response.json(), 'sample');
      } catch (error) { setStatus(error.message, true); }
    }));
    editor.replaceChildren(choice);
  }

  function offerRecovery() {
    if (!state.session || !state.canSave) return;
    if (!state.recovery?.data || state.recovery.session !== state.session) return;
    const notice = $('draft-recovery');
    notice.hidden = false;
    const matches = state.recovery.base_revision === state.serverRevision;
    notice.append(element('p', '', matches ? '发现本标签页尚未保存的草稿，可恢复后继续编辑。' : '发现未保存草稿，但会话已更新。请先下载备份，避免覆盖新内容。'));
    if (matches) notice.append(button('恢复未保存草稿', 'text-button', () => {
      const recovery = state.recovery;
      activateData(recovery.data, 'personal');
      for (const id of recovery.removed_item_ids || []) if (!trackedItemIds.has(id)) pendingRemovedItems.set(id, ++removalSequence);
      state.revision += 1;
      queueSave();
      notice.hidden = true;
    }));
    else notice.append(button('下载恢复草稿', 'text-button', () => {
      const current = state.data;
      state.data = state.recovery.data;
      downloadDraft();
      state.data = current;
    }));
    notice.append(button('放弃恢复', 'text-button', () => { clearBackup(); state.recovery = null; notice.hidden = true; }));
  }

  async function initialise() {
    try {
      const account = await window.HuhuaAccount?.ready;
      state.requireAccount = account?.require_account !== false;
      let session = new URLSearchParams(location.search).get('session');
      if (!session) session = window.HuhuaAccount?.rememberedSession();
      state.session = session;
      $('back-to-chat').href = session ? `/?session=${encodeURIComponent(session)}` : '/';
      const templateResponse = await fetch('/api/resume/templates');
      if (!templateResponse.ok) throw new Error('模板加载失败');
      state.templates = (await templateResponse.json()).templates;
      let currentData = null;
      if (session && !window.HuhuaAccount?.claimPending()) {
        const currentResponse = await fetch(`/api/resume/current?session_id=${encodeURIComponent(session)}`);
        if (currentResponse.ok) {
          const current = await currentResponse.json();
          state.serverRevision = current.revision || null;
          state.sessionInvalid = !state.serverRevision;
          if (state.sessionInvalid) clearBackup();
          state.canSave = current.can_save === true && Boolean(state.serverRevision);
          if (state.serverRevision) window.HuhuaAccount?.rememberSession(session);
          if (current.has_data && current.data) currentData = current.data;
        } else {
          // An expired or unrelated session must never prevent public template browsing.
          state.session = null; state.canSave = false; state.sessionInvalid = true;
          $('back-to-chat').href = '/';
        }
      }
      $('tpl-count').textContent = `(${state.templates.length})`;
      for (const template of state.templates) {
        const item = button('', 'tpl-item', () => selectTemplate(template));
        item.dataset.templateId = template.id;
        item.append(element('span', 'tpl-name', template.name), element('span', 'tpl-style', template.style || ''));
        if (template.fits_one_page === false) item.append(element('span', 'tpl-style tpl-two-page', '适合两页'));
        $('template-list').append(item);
      }
      if (currentData) activateData(currentData, 'personal');
      else if (window.HuhuaAccount?.guest() || !session) {
        const sample = await fetch('/api/resume/sample');
        if (sample.ok) activateData(await sample.json(), 'sample');
        else showStartChoice();
      } else showStartChoice();
      offerRecovery();
      if (state.templates.length) selectTemplate(restoreTemplate());
      else setStatus('暂无可用模板', true);
    } catch (error) {
      setStatus(error.message.includes('fetch') ? '连接已断开，请确认服务运行后刷新' : error.message, true);
      editor.replaceChildren(element('p', 'empty-section', '暂时无法加载简历内容，请刷新页面重试。'));
    }
  }
  window.addEventListener('huhua-account-claim-pending', () => {
    clearTimeout(state.saveTimer); clearTimeout(state.timer); state.controller?.abort();
    setSaveStatus('登录已成功，当前体验待保存；请重试保留当前对话。', true);
  });
  window.addEventListener('huhua-account-changed', event => {
    if (event.detail?.session_id && (!state.data || state.mode === 'sample')) {
      state.session = event.detail.session_id; window.HuhuaEditor.refreshCurrent().catch(error => setStatus(error.message, true));
    }
    if (state.session) window.HuhuaAccount?.rememberSession(state.session);
    setSaveStatus('已登录，当前简历与编辑内容已保留，可以继续编辑或导出。');
    if (state.mode === 'personal' && state.savedVersion !== state.revision) queueSave();
    renderPreview();
  });
  window.HuhuaEditor = {
    prepareProfileChange: async () => state.mode !== 'personal' || await flushSave(),
    async refreshCurrent() {
      const response = await fetch('/api/resume/current?session_id=' + encodeURIComponent(state.session));
      if (!response.ok) throw new Error('档案信息已保存，但编辑页读取失败。请刷新后核对最新简历。');
      const current = await response.json();
      if (!current.has_data || !current.data) throw new Error('档案信息已提交，请回到对话核对成稿。');
      state.serverRevision = current.revision;
      state.canSave = current.can_save !== false;
      clearBackup(); activateData(current.data, 'personal');
    },
  };
  initialise();
})();
