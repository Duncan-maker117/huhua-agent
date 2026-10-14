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
      document.getElementById('nav-account').textContent = authenticated ? '我的档案' : '登录';
      document.getElementById('nav-account-mobile').textContent = authenticated ? '我的档案' : '登录';
      document.getElementById('nav-workspace-label').textContent = authenticated ? '进入工作台' : '开始写简历';
      document.getElementById('nav-mobile-label').textContent = authenticated ? '工作台' : '开始';
    } catch (_) { /* The public page and guest entry remain usable offline. */ }
  }
  syncNavigation();
  window.addEventListener('pageshow', event => { if (event.persisted) syncNavigation(); });
})();
