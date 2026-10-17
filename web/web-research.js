/* 岗位情报只在读岗位面板展示；联网识别由服务端统一完成。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let callbacks = {}, busy = false;
  const safeUrl = value => {
    if (typeof value !== 'string') return null;
    value = value.trim();
    if (/^(?:www\.)?github\.com\/\S+$/i.test(value)) value = 'https://' + value;
    if (!/^https?:\/\/\S+$/i.test(value)) return null;
    try {
      const url = new URL(value);
      return ['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password ? url.href : null;
    } catch (_) { return null; }
  };
  const node = (tag, text, cls) => {
    const el = document.createElement(tag);
    if (typeof text === 'string') el.textContent = text;
    if (cls) el.className = cls;
    return el;
  };
  const list = value => Array.isArray(value) ? value : [];
  const text = value => typeof value === 'string' ? value : '';
  const link = (parent, url, label) => {
    const href = safeUrl(url);
    if (!href) return;
    const a = node('a', label || href, 'intel-source');
    a.href = href; a.target = '_blank'; a.rel = 'noopener'; parent.append(a);
  };
  // 只显示抓取日期（本地时区），不暴露原始时间戳。
  function fetchedOn(value) {
    const date = new Date(text(value));
    return Number.isNaN(date.getTime()) ? '' : `${date.getMonth() + 1} 月 ${date.getDate()} 日读取`;
  }
  function items(parent, values, total) {
    const ul = node('ul', undefined, 'intel-list');
    for (const value of list(values)) {
      const li = node('li', typeof value === 'string' ? value : text(value?.text));
      if (Number.isInteger(value?.count) && Number.isInteger(total)) {
        li.append(node('span', `${value.count}/${total}`, 'intel-count'));
      }
      const members = list(value?.members).map(text).filter(Boolean);
      if (members.length && (members.length > 1 || members[0] !== value.text)) {
        li.append(node('span', members.join(' / '), 'intel-members'));
      }
      ul.append(li);
    }
    parent.append(ul);
  }
  function profileItems(parent, values, profile) {
    const rows = [...list(values)].sort((a, b) => (b?.count || 0) - (a?.count || 0));
    const total = profile.frequency_basis === 'company' ? profile.company_count : profile.sample_count;
    const visible = [], more = [];
    for (const row of rows) {
      if (visible.length >= 6 || (profile.sample_count >= 6 && row?.count === 1)) more.push(row);
      else visible.push(row);
    }
    items(parent, visible, total);
    if (more.length) {
      const details = node('details', undefined, 'intel-more');
      details.append(node('summary', `其他（${more.length} 项）`));
      items(details, more, total); parent.append(details);
    }
  }
  function render(parent, info = {}) {
    const job = info.job_card;
    if (job && typeof job === 'object') {
      const card = node('article', undefined, 'intel-card intel-job');
      card.append(node('h3', [job.job_title, job.company].filter(Boolean).join(' · ') || '岗位信息', 'intel-title'));
      card.append(node('p', [job.location, job.salary, fetchedOn(job.fetched_at)].filter(Boolean).join(' / '), 'intel-meta'));
      if (list(job.requirements).length) { card.append(node('h4', '岗位要求')); items(card, job.requirements); }
      if (list(job.responsibilities).length) { card.append(node('h4', '职责摘要')); items(card, job.responsibilities); }
      if (list(job.bonuses).length) { card.append(node('h4', '加分项')); items(card, job.bonuses); }
      const details = node('details', undefined, 'intel-raw');
      details.append(node('summary', '展开原文'), node('p', text(job.raw_text)));
      card.append(details); link(card, job.url, '原招聘链接'); parent.append(card);
    }
    const profile = info.role_profile;
    if (['pending', 'failed'].includes(profile?.status)) {
      const card = node('article', undefined, 'intel-card intel-profile');
      card.dataset.state = profile.status;
      const count = Number.isInteger(profile.candidate_count) ? profile.candidate_count : 0;
      card.append(node('h3', profile.status === 'pending'
        ? (count > 0 ? `正在整理 ${count} 条真实岗位…` : '正在查找真实岗位…')
        : '岗位画像暂未完成', 'intel-title'));
      card.append(node('p', profile.status === 'pending' ? '可以继续聊经历，整理完成后会出现在这里。'
        : text(profile.message) || '可以继续聊经历，或直接提供 JD。', 'intel-meta'));
      parent.append(card);
    } else if (profile?.source === 'market_sample') {
      const card = node('article', undefined, 'intel-card intel-profile');
      card.dataset.state = 'ready';
      const sampleNote = profile.low_sample ? ` · 仅基于 ${profile.sample_count} 条岗位` : '';
      card.append(node('h3', `${text(profile.direction)} · 岗位画像${sampleNote}`, 'intel-title'));
      card.append(node('p', `基于 ${profile.sample_count} 条真实岗位 · ${fetchedOn(profile.fetched_at)}`, 'intel-meta'));
      if (profile.weighting_note) card.append(node('p', text(profile.weighting_note), 'intel-meta'));
      for (const [key, title] of [['responsibilities', '高频职责'], ['skills', '高频技能'], ['bonuses', '加分项']]) {
        const group = node('section', undefined, 'intel-group'); group.append(node('h4', title));
        profileItems(group, profile[key], profile); card.append(group);
      }
      const details = node('details', undefined, 'intel-sources'); details.append(node('summary', '岗位来源'));
      const ul = node('ul', undefined, 'intel-list');
      for (const source of list(profile.sources)) { const li = node('li'); link(li, source.url, [source.job_title, source.company].filter(Boolean).join(' · ')); ul.append(li); }
      details.append(ul); card.append(details); parent.append(card);
    }
    const company = info.company;
    if (company && typeof company === 'object' && company.source === 'company_search') {
      const card = node('article', undefined, 'intel-card intel-company');
      card.append(node('h3', text(company.name), 'intel-title'));
      for (const [key, label] of [['industry', '行业'], ['description', '简介']]) {
        card.append(node('p', `${label}：${text(company[key]?.text) || '暂未查到'}`));
        if (company[key]) link(card, company[key].url, `${label}来源${company[key].source_type === '百科' ? '（百科）' : ''}`);
      }
      if (company.official_site) { link(card, company.official_site.text, '官网'); link(card, company.official_site.url, '官网来源'); }
      else card.append(node('p', '官网：暂未查到'));
      parent.append(card);
    }
    if (info.intel_notice) parent.append(node('p', text(info.intel_notice)));
  }
  function syncNotice() {
    const notice = $('web-direct-link-notice');
    if (!notice) return;
    notice.hidden = busy || !/https?:\/\//i.test(callbacks.input?.() || '');
    notice.textContent = '发送后自动识别公开链接；读不到的招聘页可上传截图或复制正文。网页内容只作参考。';
  }
  window.HuhuaWebResearch = {
    safeUrl, render,
    init(options = {}) {
      callbacks = options;
      if (!$('web-direct-link-notice') && $('input')) {
        const notice = node('p', '', 'web-tool-usage-notice web-direct-link-notice');
        notice.id = 'web-direct-link-notice'; notice.hidden = true;
        $('command-surface')?.append(notice);
      }
      $('input')?.addEventListener('input', syncNotice);
      syncNotice();
    },
    setStreaming(value) { busy = value; syncNotice(); },
    toolStatus(value) { const el = $('request-status'); if (el && typeof value?.message === 'string') el.textContent = value.message; },
  };
})();
