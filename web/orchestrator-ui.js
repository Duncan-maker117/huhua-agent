/* 编排模式的入口与进度；继续使用现有发送、工作区和问题卡。 */
(() => {
  'use strict';
  const entries = [
    ['我有 JD', '我有目标岗位的 JD，先帮我看看岗位要求。'],
    ['我有旧简历', '我有一份旧简历，想基于真实经历整理成新稿。'],
    ['先聊聊我的经历', '我想先聊聊自己的经历，看看哪些能写进简历。'],
    ['看看你能做什么', '请介绍你能怎样帮我做简历，并给一个具体的价值示例。'],
  ];
  function init({container, legacy, send, busy, fetcher = fetch}) {
    if (!container) return;
    fetcher('/api/chat/agent-mode').then(response => response.ok ? response.json() : {}).then(data => {
      if (data.agent_mode !== 'loop') return;
      if (legacy) legacy.style.display = 'none';
      container.hidden = false;
      for (const [label, text] of entries) {
        const button = document.createElement('button');
        button.type = 'button'; button.textContent = label;
        button.className = 'guidance-option';
        button.addEventListener('click', async () => {
          if (button.disabled || busy()) return;
          button.disabled = true;
          try { await send(text, {quickReply: true, keepDraft: true}); }
          finally { button.disabled = false; }
        });
        container.append(button);
      }
    }).catch(() => {});
  }
  function progress(parent) {
    const rows = new Map();
    return event => {
      if (!event || typeof event.tool !== 'string' || !['running', 'completed'].includes(event.status)) return;
      let row = rows.get(event.tool);
      if (!row) {
        row = document.createElement('p'); row.className = 'tool-progress text-xs text-on-surface-variant';
        row.setAttribute('role', 'status'); row.setAttribute('aria-live', 'polite');
        parent.append(row); rows.set(event.tool, row);
      }
      row.dataset.status = event.status;
      row.textContent = typeof event.message === 'string' ? event.message : '正在处理…';
    };
  }
  window.HuhuaOrchestrator = {init, progress};
})();
