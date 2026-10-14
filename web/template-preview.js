/* Shared, memory-only render requests and sandboxed preview buffers. */
(() => {
  'use strict';

  function createLoader({fetchHtml, templates, current, canPrefetch}) {
    const cache = new Map(), pending = new Map();
    let revision = null, generation = 0, idle = null, hover = null, walk = 0;
    function cancelIdle() {
      walk++;
      if (idle === null) return;
      if (window.requestIdleCallback) window.cancelIdleCallback(idle);
      else clearTimeout(idle);
      idle = null;
    }
    function abort(template, entry) {
      entry.controller.abort();
      if (pending.get(template) === entry) pending.delete(template);
    }
    function invalidate() {
      generation++;
      cancelIdle(); clearTimeout(hover); hover = null;
      for (const [template, entry] of pending) abort(template, entry);
      cache.clear(); revision = null;
    }
    function get(template, version, foreground = false) {
      if (version !== revision) { invalidate(); revision = version; }
      if (foreground) {
        cancelIdle();
        for (const [id, entry] of pending) if (entry.foreground && id !== template) abort(id, entry);
      }
      if (cache.has(template)) return {promise: Promise.resolve(cache.get(template)), controller: null};
      const existing = pending.get(template);
      if (existing) { existing.foreground ||= foreground; return existing; }
      // Hover may overlap the serial idle walk. Reserve a slot for a click.
      if (pending.size >= 2) {
        if (!foreground) return null;
        const [id, entry] = [...pending].find(([, value]) => !value.foreground);
        abort(id, entry);
      }
      const epoch = generation;
      const entry = {controller: new AbortController(), foreground};
      pending.set(template, entry);
      entry.promise = (async () => {
        try {
          const html = await fetchHtml(template, entry.controller.signal);
          if (epoch === generation && !entry.controller.signal.aborted) cache.set(template, html);
          return html;
        } finally { if (pending.get(template) === entry) pending.delete(template); }
      })();
      return entry;
    }
    function prefetch(template, version) {
      if (!canPrefetch()) return;
      // Speculative errors stay silent and are retried by a later real request.
      return get(template, version)?.promise.catch(() => {});
    }
    function schedule(version) {
      cancelIdle();
      const epoch = generation, runId = walk;
      const remaining = templates().filter(id => id !== current());
      const next = () => {
        if (epoch !== generation || runId !== walk || !canPrefetch() || !remaining.length) return;
        const run = async () => {
          idle = null;
          if (epoch !== generation || runId !== walk || !canPrefetch()) return;
          await prefetch(remaining.shift(), version);
          if (epoch === generation && runId === walk) next();
        };
        idle = window.requestIdleCallback ? window.requestIdleCallback(run, {timeout: 1000}) : setTimeout(run, 200);
      };
      next();
    }
    function bind(button, template, version) {
      const warm = () => {
        clearTimeout(hover);
        hover = setTimeout(() => { hover = null; prefetch(template, version()); }, 80);
      };
      const cancel = () => { clearTimeout(hover); hover = null; };
      button.addEventListener('pointerenter', warm);
      button.addEventListener('focus', warm);
      button.addEventListener('pointerleave', cancel);
      button.addEventListener('blur', cancel);
    }
    return {get, invalidate, schedule, bind};
  }

  function createBuffer(front, back, onSwap) {
    const frontId = front.id, backId = back.id;
    const frames = [front, back];
    let pending = null, sequence = 0, measuring = false;
    function visibility(frame, visible) {
      frame.style.visibility = visible ? 'visible' : 'hidden';
      frame.style.pointerEvents = visible ? 'auto' : 'none';
      frame.setAttribute('aria-hidden', String(!visible));
      frame.setAttribute('tabindex', visible ? '0' : '-1');
      frame.inert = !visible;
      if (visible) frame.removeAttribute('inert');
      else frame.setAttribute('inert', '');
    }
    visibility(front, true); visibility(back, false);
    function cancel() {
      if (!pending) return;
      clearTimeout(pending.timer);
      pending.resolve(false); pending = null;
    }
    function markSwitch() {
      if (!window.performance?.mark) return;
      window.performance.clearMarks('huhua-template-switch-start');
      window.performance.mark('huhua-template-switch-start');
      measuring = true;
    }
    function finishMeasure() {
      if (!measuring) return;
      window.performance.clearMeasures('huhua-template-switch');
      window.performance.measure('huhua-template-switch', 'huhua-template-switch-start');
      window.performance.clearMarks('huhua-template-switch-start');
      measuring = false;
    }
    function cancelSwitch() {
      cancel();
      if (measuring) window.performance.clearMarks('huhua-template-switch-start');
      measuring = false;
    }
    function reset() {
      cancelSwitch();
      for (const frame of frames) frame.srcdoc = '';
    }
    function show(html, isCurrent, commit) {
      cancel();
      const target = frames.find(frame => frame !== front), token = ++sequence;
      return new Promise((resolve, reject) => {
        pending = {target, token, isCurrent, commit, resolve, reject};
        pending.timer = setTimeout(() => {
          if (pending?.token !== token) return;
          pending = null; reject(new Error('预览加载超时，请重试'));
        }, 15000);
        // The parent cannot read an opaque sandbox's document.fonts. This tiny
        // bridge runs only in the preview; rendered/exported HTML is unchanged.
        const bridge = `<script>(() => {
          window.addEventListener('load', () => {
            let timer;
            const fonts = document.fonts ? document.fonts.ready : Promise.resolve();
            Promise.race([fonts, new Promise(resolve => { timer = setTimeout(resolve, 300); })])
              .catch(() => {}).then(() => {
                clearTimeout(timer);
                parent.postMessage({type: 'huhua-preview-loaded', token: ${token},
                  height: Math.ceil(Math.max(1123, document.body.getBoundingClientRect().height))}, '*');
              });
          }, {once: true});
        })();<\/script>`;
        target.srcdoc = /<\/body>/i.test(html) ? html.replace(/<\/body>/i, bridge + '</body>') : html + bridge;
      });
    }
    window.addEventListener('message', event => {
      const job = pending, message = event.data;
      if (!job || event.source !== job.target.contentWindow || message?.type !== 'huhua-preview-loaded' || message.token !== job.token) return;
      if (!Number.isFinite(message.height) || message.height < 1123 || message.height > 100000) return;
      if (!job.isCurrent()) { cancel(); return; }
      clearTimeout(job.timer); pending = null;
      const old = front;
      front = job.target;
      // Keep existing ID-based consumers (including history reset) on the front.
      old.id = backId; front.id = frontId;
      onSwap(front, message.height);
      job.commit?.();
      visibility(old, false); visibility(front, true);
      finishMeasure(); job.resolve(true);
    });
    return {show, cancel, cancelSwitch, reset, markSwitch, frames};
  }
  window.HuhuaTemplatePreview = {createLoader, createBuffer};
})();
