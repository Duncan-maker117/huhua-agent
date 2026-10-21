/* Main workspace only. No editor selection handlers or export/template changes. */
(() => {
  'use strict';
  const selector = '[data-field-path]';
  const fields = [...document.querySelectorAll(selector)].filter(el =>
    /^\/(projects|work_experience|campus|open_source|awards)\/\d+\/(polished_bullets\/\d+|bullets\/\d+|tech_stack)$/.test(el.dataset.fieldPath));
  const byPath = new Map(fields.map(el => [el.dataset.fieldPath, el]));
  const send = message => window.parent.postMessage(message, '*');
  let enabled = false, revealed = null;
  const style = document.createElement('style');
  style.textContent = `
    [data-evidence-state] { cursor: pointer; }
    [data-evidence-state]:hover, [data-evidence-state]:focus-visible,
    [data-evidence-revealed] {
      outline: 1px dashed #8b5cf6; outline-offset: 2px;
      background-color: rgba(139, 92, 246, .09); border-radius: 2px;
      -webkit-box-decoration-break: clone; box-decoration-break: clone;
    }
    [data-evidence-state="pending"] {
      text-decoration: underline wavy #d97706;
      text-underline-offset: 3px; text-decoration-thickness: 1px;
    }
    @media print {
      [data-evidence-state], [data-evidence-state]:hover,
      [data-evidence-state]:focus-visible, [data-evidence-revealed], mark[data-located] {
        outline: none !important; background: transparent !important;
        box-shadow: none !important; text-decoration: none !important; cursor: auto;
      }
    }
  `;
  document.head.appendChild(style);
  function describe() { send({type: 'huhua-evidence-ready', paths: [...byPath.keys()]}); }
  function rect(el) {
    const {left, right, top, bottom} = el.getBoundingClientRect(); return {left, right, top, bottom};
  }
  function clearReveal() { revealed?.removeAttribute('data-evidence-revealed'); revealed = null; }
  function select(target) {
    const el = target instanceof Element ? target.closest(selector) : null;
    if (el && byPath.get(el.dataset.fieldPath) === el && el.hasAttribute('data-evidence-state')) {
      send({type: 'huhua-evidence-select', path: el.dataset.fieldPath, rect: rect(el)}); return true;
    }
    return false;
  }
  document.addEventListener('click', event => {
    if (!enabled) return;
    if (select(event.target)) event.preventDefault();
    else send({type: 'huhua-evidence-dismiss'});
  });
  document.addEventListener('keydown', event => {
    if (!enabled) return;
    if (event.key === 'Escape') send({type: 'huhua-evidence-dismiss'});
    if (['Enter', ' '].includes(event.key) && select(event.target)) event.preventDefault();
  });
  window.addEventListener('scroll', () => send({type: 'huhua-evidence-dismiss'}), true);
  window.addEventListener('message', event => {
    if (event.source !== window.parent) return;
    const message = event.data;
    if (message?.type === 'huhua-evidence-describe') { describe(); return; }
    if (message?.type === 'huhua-evidence-state') {
      enabled = message.enabled === true;
      clearReveal();
      for (const el of fields) {
        el.removeAttribute('data-evidence-state'); el.removeAttribute('tabindex');
        el.removeAttribute('role'); el.removeAttribute('aria-haspopup');
      }
      if (enabled) for (const row of Array.isArray(message.rows) ? message.rows : []) {
        const el = byPath.get(row.path);
        if (!el || !['supported', 'pending', 'manual'].includes(row.state)) continue;
        el.setAttribute('data-evidence-state', row.state); el.tabIndex = 0;
        el.setAttribute('role', 'button'); el.setAttribute('aria-haspopup', 'dialog');
      }
    } else if (enabled && message?.type === 'huhua-evidence-reveal') {
      const el = byPath.get(message.path);
      if (!el) return;
      clearReveal(); revealed = el; el.setAttribute('data-evidence-revealed', '');
      el.scrollIntoView({block: 'nearest', inline: 'nearest'});
      el.focus({preventScroll: true});
      send({type: 'huhua-evidence-revealed', path: message.path, rect: rect(el)});
    }
  });
  describe();
})();
