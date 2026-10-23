// Execute the real send/SSE loop with a virtual clock and a pending writer.
const assert = require('node:assert/strict');
const {fixture, tick} = require('./resume_embedded.dom.js');
const f = fixture('index.html');
const proto = Object.getPrototypeOf(f.document.body);
Object.defineProperty(proto, 'parentNode', {get() { return this.parentElement; }});
let now = 0, interval, resolveRead, signal, rendered = '';
const encoder = new TextEncoder();
const chunk = text => ({done: false, value: encoder.encode(text)});
let first = true;
Object.assign(f.context, {
  Date: {now: () => now}, crypto: {randomUUID: () => 'fictional-turn'},
  currentController: null, currentTurn: null, waitingTimer: null,
  conversationBusy: false, conversationReady: true, SESSION_ID: 'fictional-session',
  pendingUploads: 0, attachments: [], messages: [], selectedTask: 'auto',
  inputEl: f.ids.get('input'), messagesEl: f.ids.get('messages'), emptyStateEl: null,
  canvasState: {versionId: 'fictional-v1'}, API: '/api/chat/stream',
  setInterval: callback => { interval = callback; return 1; }, clearInterval: () => { interval = null; },
  setSendButtonMode() {}, updateFlowActions() {}, saveMessages() {}, clearAttachments() {}, autoResize() {},
  resetSelectedTask() {}, applyMeta() {}, maybeShowGenerateLink() {}, refreshCanvas() {}, cancelAnimationFrame() {},
  renderAssistant: (element, text) => { rendered = text; },
  appendBubble: () => { const element = f.document.createElement('div'); f.document.body.append(element); return element; },
  fetch: async (url, options) => {
    signal = options.signal;
    return {ok: true, body: {getReader: () => ({
      read: async () => {
        if (first) { first = false; return chunk('data: {"type":"tool_status","tool":"write_draft","status":"running","message":"正在写第一稿…"}\n\n'); }
        return new Promise(resolve => { resolveRead = resolve; });
      }, cancel: async () => {},
    })}};
  },
});
f.run('index.html', html => html.slice(html.indexOf('async function send('), html.indexOf('const canvasState =')));
(async () => {
  const pending = f.context.send('请用虚构经历写稿');
  await tick();
  for (const seconds of [60, 90, 149, 150, 180]) {
    now = seconds * 1000;
    interval();
    assert.equal(signal.aborted, false);
    assert.match(f.ids.get('request-status').textContent, new RegExp(`仍在处理中… ${seconds} 秒`));
    assert.match(f.ids.get('request-status').textContent, /正在写第一稿/);
    assert.equal(f.context.messages.length, 1, 'pending writer is not reported as a failed reply');
    assert.equal(f.timers.size, 0, 'no elapsed-time abort is scheduled');
  }
  resolveRead(chunk(': heartbeat\n\ndata: {"content":"虚构稿件已完成。"}\n\ndata: [DONE]\n\n'));
  assert.equal(await pending, true);
  assert.equal(rendered, '虚构稿件已完成。');
  assert.equal(f.context.currentController, null);
  assert.equal(interval, null);
  console.log('quality 18e DOM: 150s/180s waiting, heartbeat and final reply passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
