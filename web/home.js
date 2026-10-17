(() => {
  'use strict';
  const command = document.getElementById('mcp-command');
  const copy = document.getElementById('copy-command');
  const status = document.getElementById('copy-status');
  command.textContent = `claude mcp add --transport http huhua ${location.origin}/mcp --header "Authorization: Bearer <你的令牌>"`;
  function bindCopy(copy, source, status, success, failure) {
    let feedbackTimer;
    copy.addEventListener('click', async () => {
      clearTimeout(feedbackTimer);
      copy.disabled = true;
      try {
        await navigator.clipboard.writeText(source.textContent);
        copy.textContent = '已复制';
        status.textContent = success;
        feedbackTimer = setTimeout(() => { copy.textContent = '复制'; status.textContent = ''; }, 4000);
      } catch (_) {
        copy.textContent = '复制';
        status.textContent = failure;
      } finally { copy.disabled = false; }
    });
  }
  bindCopy(copy, command, status, '已复制，请将 <你的令牌> 替换为自己的令牌。', '复制未完成，请选中上方命令手动复制。');
  for (const task of ['tailor', 'project', 'check']) {
    bindCopy(document.getElementById('copy-task-' + task), document.getElementById('mcp-task-' + task),
      document.getElementById('copy-task-' + task + '-status'), '已复制，可粘贴到你的 AI 助手里。', '复制未完成，请选中示例话术手动复制。');
  }

  const menu = document.getElementById('site-nav');
  const toggle = document.getElementById('menu-toggle');
  function setMenu(open) {
    menu.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? '关闭导航菜单' : '打开导航菜单');
  }
  toggle.addEventListener('click', () => setMenu(toggle.getAttribute('aria-expanded') !== 'true'));
  menu.addEventListener('click', event => { if (event.target.closest('a')) setMenu(false); });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') { setMenu(false); toggle.focus(); }
  });

  const previews = [
    {name: 'chat', caption: '聊几句经历，右侧实时长出一页简历。图中内容为虚构样例。'},
    {name: 'editor', caption: '从聊过的经历，到可以逐条核对的一页简历。图中内容为虚构样例。'},
  ];
  function selectPreview(index, focus = false) {
    previews.forEach(({name}, position) => {
      const tab = document.getElementById('preview-tab-' + name);
      const selected = position === index;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      document.getElementById('preview-panel-' + name).hidden = !selected;
      if (selected && focus) tab.focus();
    });
    document.getElementById('preview-caption').textContent = previews[index].caption;
  }
  previews.forEach(({name}, index) => {
    const tab = document.getElementById('preview-tab-' + name);
    tab.addEventListener('click', () => selectPreview(index));
    tab.addEventListener('keydown', event => {
      const next = event.key === 'ArrowRight' ? (index + 1) % previews.length
        : event.key === 'ArrowLeft' ? (index + previews.length - 1) % previews.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? previews.length - 1 : null;
      if (next === null) return;
      event.preventDefault(); selectPreview(next, true);
    });
  });
  selectPreview(0);

  // Native details/summary also works without JavaScript. Open a linked answer.
  function openAnswer() {
    if (location.hash === '#privacy') document.getElementById('privacy').open = true;
  }
  window.addEventListener('hashchange', openAnswer);
  openAnswer();

  function renderNavigation(account) {
    const authenticated = account && account.authenticated === true;
    document.getElementById('nav-account').textContent = authenticated ? '我的档案' : '登录';
    document.getElementById('nav-account-mobile').textContent = authenticated ? '我的档案' : '登录';
    document.getElementById('nav-workspace-label').textContent = authenticated ? '进入工作台' : '开始写简历';
    document.getElementById('nav-mobile-label').textContent = authenticated ? '工作台' : '开始';
  }
  async function syncNavigation() {
    try {
      const response = await fetch('/api/account/me', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) return;
      renderNavigation(await response.json());
    } catch (_) { /* The public page and guest entry remain usable offline. */ }
  }
  if (window.HuhuaHomeAuth) window.HuhuaHomeAuth.onChange(renderNavigation);
  else syncNavigation();
  window.addEventListener('pageshow', event => { if (event.persisted) syncNavigation(); });

  // Play the sample conversation once when it scrolls into view.
  const sample = document.querySelector('.conversation-sample');
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (sample && 'IntersectionObserver' in window && !reduceMotion) {
    sample.classList.add('will-play');
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      sample.classList.add('is-playing');
      observer.disconnect();
    }, {threshold: .35});
    observer.observe(sample);
  }

  // Hover a template thumbnail to see it larger (mouse only; touch taps go straight to the editor).
  const strip = document.querySelector('.template-strip');
  const finePointer = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  if (strip && finePointer) {
    const zoom = document.createElement('div');
    zoom.className = 'template-zoom';
    zoom.setAttribute('aria-hidden', 'true');
    const zoomImage = document.createElement('img');
    zoomImage.alt = '';
    const zoomCaption = document.createElement('p');
    const zoomName = document.createElement('strong');
    const zoomHint = document.createElement('span');
    zoomHint.textContent = '点击用这个模板';
    zoomCaption.append(zoomName, zoomHint);
    zoom.append(zoomImage, zoomCaption);
    document.body.append(zoom);
    let current = null;
    function place(link) {
      const card = link.querySelector('.template-image').getBoundingClientRect();
      const header = document.querySelector('.site-header')?.getBoundingClientRect().bottom || 0;
      const gap = 14, edge = 12, chrome = 56; // padding + caption under the image
      const spaceAbove = card.top - gap - Math.max(edge, header + edge);
      const spaceBelow = window.innerHeight - card.bottom - gap - edge;
      const above = spaceAbove >= spaceBelow;
      const room = Math.max(above ? spaceAbove : spaceBelow, 200);
      const width = Math.max(220, Math.min(440, window.innerWidth - 32, (room - chrome) / (777 / 788) + 20));
      zoom.style.width = width + 'px';
      const height = zoom.offsetHeight || width + chrome;
      const left = Math.max(16, Math.min(card.left + card.width / 2 - width / 2, window.innerWidth - width - 16));
      zoom.style.left = left + 'px';
      zoom.style.top = (above ? card.top - gap - height : card.bottom + gap) + 'px';
      zoom.style.setProperty('--zoom-origin', (card.left + card.width / 2 - left) + 'px ' + (above ? '100%' : '0'));
    }
    function show(link) {
      const image = link.querySelector('img');
      if (!image) return;
      current = link;
      zoomImage.src = image.currentSrc || image.src;
      zoomName.textContent = link.querySelector(':scope > span')?.textContent || '';
      place(link);
      zoom.classList.add('is-visible');
    }
    function hide() { current = null; zoom.classList.remove('is-visible'); }
    zoomImage.addEventListener('load', () => { if (current) place(current); });
    for (const link of strip.querySelectorAll('a')) {
      link.addEventListener('mouseenter', () => show(link));
      link.addEventListener('mouseleave', hide);
    }
    const follow = () => { if (current) place(current); };
    window.addEventListener('scroll', follow, {passive: true});
    strip.addEventListener('scroll', follow, {passive: true});
    window.addEventListener('resize', hide);
  }
})();
