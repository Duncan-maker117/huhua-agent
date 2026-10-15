(() => {
  'use strict';
  const command = document.getElementById('mcp-command');
  const copy = document.getElementById('copy-command');
  const status = document.getElementById('copy-status');
  command.textContent = `claude mcp add --transport http huhua ${location.origin}/mcp --header "Authorization: Bearer <你的令牌>"`;
  let feedbackTimer;
  copy.addEventListener('click', async () => {
    clearTimeout(feedbackTimer);
    copy.disabled = true;
    try {
      await navigator.clipboard.writeText(command.textContent);
      copy.textContent = '已复制';
      status.textContent = '已复制，请将 <你的令牌> 替换为自己的令牌。';
      feedbackTimer = setTimeout(() => { copy.textContent = '复制'; status.textContent = ''; }, 4000);
    } catch (_) {
      copy.textContent = '复制';
      status.textContent = '复制未完成，请选中上方命令手动复制。';
    } finally { copy.disabled = false; }
  });

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

  async function syncNavigation() {
    try {
      const response = await fetch('/api/account/me', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) return;
      const account = await response.json();
      const authenticated = account.authenticated === true;
      document.getElementById('nav-account').textContent = authenticated ? '我的档案' : '登录/注册';
      document.getElementById('nav-account-mobile').textContent = authenticated ? '我的档案' : '登录/注册';
      document.getElementById('nav-workspace-label').textContent = authenticated ? '进入工作台' : '开始写简历';
      document.getElementById('nav-mobile-label').textContent = authenticated ? '工作台' : '开始';
    } catch (_) { /* The public page and guest entry remain usable offline. */ }
  }
  syncNavigation();
  window.addEventListener('pageshow', event => { if (event.persisted) syncNavigation(); });
})();
