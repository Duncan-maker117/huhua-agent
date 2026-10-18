/* 编排模式的入口与进度；继续使用现有发送、工作区和问题卡。 */
(() => {
  'use strict';
  const entries = [
    ['我有 JD', '贴招聘原文或链接，先拆岗位要什么', '我有目标岗位的 JD，先帮我看看岗位要求。'],
    ['我有旧简历', '贴进来或拖入文件，按事实重新整理', '我有一份旧简历，想基于真实经历整理成新稿。'],
    ['先聊聊我的经历', '想到哪说到哪，我来追问关键细节', '我想先聊聊自己的经历，看看哪些能写进简历。'],
    ['看看你能做什么', '看一个改写前后的具体例子', '请介绍你能怎样帮我做简历，并给一个具体的价值示例。'],
  ];
  function init({container, legacy, send, busy, fetcher = fetch}) {
    if (!container) return;
    fetcher('/api/chat/agent-mode').then(response => response.ok ? response.json() : {}).then(data => {
      if (data.agent_mode !== 'loop') return;
      if (legacy) legacy.style.display = 'none';
      // 编排模式先请用户随口介绍自己，不再以任务按钮为主入口。
      const title = document.getElementById('quick-card-title'), desc = document.getElementById('quick-card-desc');
      if (title) title.textContent = '先随便介绍下自己';
      if (desc) desc.textContent = '在读什么、做过什么、想投什么，想到哪说到哪，直接在下面输入框里说。也可以从这里挑一个开始。';
      container.hidden = false;
      container.classList.add('orchestrator-entries');
      for (const [label, hint, text] of entries) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'orchestrator-entry';
        const name = document.createElement('span'); name.className = 'orchestrator-entry-label'; name.textContent = label;
        const sub = document.createElement('span'); sub.className = 'orchestrator-entry-hint'; sub.textContent = hint;
        button.append(name, sub);
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
        row = document.createElement('p'); row.className = 'tool-progress';
        row.setAttribute('role', 'status'); row.setAttribute('aria-live', 'polite');
        parent.append(row); rows.set(event.tool, row);
      }
      row.dataset.status = event.status;
      row.textContent = typeof event.message === 'string' ? event.message : '正在处理…';
    };
  }
  window.HuhuaOrchestrator = {init, progress};
})();
