/* Keep the chat flex layout inside iOS browser chrome and the soft keyboard. */
(() => {
  'use strict';
  const root = document.documentElement, viewport = window.visualViewport;
  let scheduled = false;
  function update() {
    scheduled = false;
    // Preserve user pinch zoom rather than resize the page to its magnified crop.
    if (viewport && Math.abs(viewport.scale - 1) > .01) return;
    const height = viewport?.height || window.innerHeight;
    if (height <= 0) return;
    root.style.setProperty('--chat-viewport-height', height + 'px');
    root.style.setProperty('--chat-viewport-top', Math.max(0, viewport?.offsetTop || 0) + 'px');
    root.toggleAttribute('data-chat-short-viewport', height < 500);
    // Do not scroll/focus here: reading position and unfinished input must survive.
  }
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(update);
  }
  viewport?.addEventListener('resize', schedule);
  viewport?.addEventListener('scroll', schedule);
  window.addEventListener('resize', schedule);
  window.addEventListener('pageshow', schedule);
  update();
})();
