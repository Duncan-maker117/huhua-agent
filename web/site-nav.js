(() => {
  'use strict';
  // Center nav = reading progress: a short line slides under the section in view.
  const nav = document.getElementById('site-nav');
  if (!nav) return;
  const header = document.querySelector('.site-header');
  const links = [...nav.querySelectorAll('a[href^="#"]:not(.mobile-account)')]
    .map(link => ({link, section: document.getElementById(link.getAttribute('href').slice(1))}))
    .filter(item => item.section);
  const indicator = document.createElement('span');
  indicator.className = 'nav-indicator no-motion';
  indicator.setAttribute('aria-hidden', 'true');
  nav.append(indicator);
  let active = null, frame = 0;

  function current() {
    const top = (header ? header.getBoundingClientRect().bottom : 0);
    const line = top + window.innerHeight * .3;
    const visible = links.filter(item => item.section.getClientRects().length);
    if (!visible.length) return null;
    const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
    if (atBottom) return visible[visible.length - 1];
    let found = null;
    for (const item of visible) if (item.section.getBoundingClientRect().top <= line) found = item;
    return found;
  }
  function place() {
    frame = 0;
    const next = current();
    if (next !== active) {
      active?.link.classList.remove('is-active');
      active?.link.removeAttribute('aria-current');
      next?.link.classList.add('is-active');
      next?.link.setAttribute('aria-current', 'location');
      active = next;
    }
    if (!active || !active.link.offsetWidth) { indicator.classList.remove('is-visible'); return; }
    const x = active.link.offsetLeft + active.link.offsetWidth / 2 - indicator.offsetWidth / 2;
    indicator.style.setProperty('--indicator-x', x + 'px');
    indicator.classList.add('is-visible');
  }
  const schedule = () => { if (!frame) frame = requestAnimationFrame(place); };
  window.addEventListener('scroll', schedule, {passive: true});
  window.addEventListener('resize', schedule);
  if (document.fonts?.ready) document.fonts.ready.then(schedule);
  place();
  // First placement without sliding in from the left edge.
  requestAnimationFrame(() => requestAnimationFrame(() => indicator.classList.remove('no-motion')));

  // Pages without their own script (comparison report) opt in to the menu and account labels.
  if (nav.dataset.sharedMenu !== undefined) {
    const toggle = document.getElementById('menu-toggle');
    const setMenu = open => {
      nav.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? '关闭导航菜单' : '打开导航菜单');
    };
    toggle?.addEventListener('click', () => setMenu(toggle.getAttribute('aria-expanded') !== 'true'));
    nav.addEventListener('click', event => { if (event.target.closest('a')) setMenu(false); });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && toggle?.getAttribute('aria-expanded') === 'true') { setMenu(false); toggle.focus(); }
    });
    window.HuhuaHomeAuth?.onChange(account => {
      const authenticated = account && account.authenticated === true;
      const text = (id, value) => { const node = document.getElementById(id); if (node) node.textContent = value; };
      text('nav-account', authenticated ? '我的档案' : '登录');
      text('nav-account-mobile', authenticated ? '我的档案' : '登录');
      text('nav-workspace-label', authenticated ? '进入工作台' : '开始写简历');
      text('nav-mobile-label', authenticated ? '工作台' : '开始');
    });
  }
})();
