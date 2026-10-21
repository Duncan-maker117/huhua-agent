// Production handlers against the repository's synthetic DOM, no server/provider.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {fixture, tick} = require('./resume_embedded.dom.js');
const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const warning = '这份简历属于另一个账号。请退出当前账号，用生成它的邮箱登录后再打开此链接。';
const reply = (body, status = 200) => ({ok: status < 400, status, headers: {get() {}}, json: async () => body});
const text = node => [node.textContent, ...node.children.map(text)].join('|');
const descendants = node => [node, ...node.children.flatMap(descendants)];
const settle = async () => { for (let i = 0; i < 6; i++) await tick(); };
const between = (start, end) => html.slice(html.indexOf(start), html.indexOf(end, html.indexOf(start)));

function chatFixture() {
  const f = fixture('index.html');
  f.context.location = {origin:'https://huhua.test', pathname:'/chat', search:'?session=foreign&from=mcp', hash:'', href:'https://huhua.test/chat?session=foreign&from=mcp'};
  Object.assign(f.context, {API:'/api/chat/stream', SESSION_ID:'foreign', LEGACY_SESSION_ID:null,
    SESSION_KEY:'huhua_session_id', MSG_KEY:'huhua_messages', SAVED_AT_KEY:'huhua_saved_at',
    conversationReady:true, conversationBusy:false, currentController:null, currentTurn:null,
    attachments:[], pendingUploads:0, messages:[], canvasState:{}, canvasReadRequest:0,
    selectedTask:'auto', waitingTimer:null, chatBackups:new Map(), chatRecoveries:new Map(), unsavedChatSessions:new Set(),
    crypto:{randomUUID:()=> 'turn-fixture'}, setInterval:()=>1, clearInterval(){}, cancelAnimationFrame(){},
    autoResize(){}, updateFlowActions(){}, resetSelectedTask(){}, clearAttachments(){}, renderAttachments(){},
    resetCanvasPreview(){}, resetGenerateLink(){}, renderStageRail(){}, refreshCanvas(){}, saveMessages(){},
    maybeShowGenerateLink(){}, setSendButtonMode(){}, renderAssistant(){}, applyMeta(){},
    appendBubble:()=>f.document.createElement('div'), alert:message=>{throw new Error(message);},
    history:{replaceState:(_, __, url)=>{f.replaced = url;}}, sessionStorage:{removeItem(){}},
  });
  f.window.matchMedia = () => ({matches: Boolean(f.mobile)});
  f.ids.get('input').value = '';
  f.ids.get('input').setSelectionRange = (start, end) => { f.selection = [start, end]; };
  vm.runInNewContext(between('const emptyStateEl =', 'function renderAssistant('), f.context);
  vm.runInNewContext(between("inputEl.addEventListener('input'", '// A chip selects'), f.context);
  return f;
}

async function editorCheck() {
  for (const status of [403, 404, 401]) {
    const f = fixture('resume.html'), called = [], logout = [], opened = [];
    f.context.location.search = '?session=foreign&template=t001-jianyue&from=mcp';
    f.context.location.href = 'https://huhua.test/resume' + f.context.location.search;
    f.context.location.reload = () => { f.reloaded = true; };
    f.window.HuhuaAccount = {ready:Promise.resolve({require_account:true}), guest:()=>false,
      claimPending:()=>false, rememberSession(){}, logout:async options=>logout.push(options), open:reason=>opened.push(reason)};
    f.context.fetch = async url => {
      called.push(url);
      if (url === '/api/resume/templates') return reply({templates:[{id:'t001-jianyue',name:'简约'}]});
      if (url.startsWith('/api/resume/current?')) return reply({detail:status===403 ? {code:'conversation_other_account',message:warning} : '不可访问'}, status);
      throw new Error('Unexpected request ' + url);
    };
    f.run('resume-editor.js'); await settle();
    assert.ok(called.includes('/api/resume/current?session_id=foreign&from=mcp'));
    assert.ok(!called.includes('/api/resume/sample'));
    const editor = f.ids.get('form-editor');
    if (status === 403) {
      assert.ok(text(editor).includes(warning));
      assert.ok(f.ids.get('back-to-chat').href.includes('from=mcp'));
      await descendants(editor).find(n => n.tagName==='BUTTON' && n.textContent==='退出登录').click();
      assert.equal(logout[0].returnToCurrent, true);
    } else {
      assert.ok(text(editor).includes('这份简历需要登录对应账号后查看'));
      await descendants(editor).find(n => n.tagName==='BUTTON').click();
      assert.equal(opened.length, 1);
    }
    f.fire('huhua-account-changed', {}); assert.equal(f.reloaded, true);
    assert.equal(f.ids.get('btn-export').disabled, true);
  }
}

async function chatCheck() {
  for (const loggedIn of [true, false]) {
    const f = chatFixture(), called = [], logout = [], opened = [];
    f.context.conversationReady = false;
    let authenticated = loggedIn;
    f.window.HuhuaAccount = {ready:Promise.resolve({}), claimPending:()=>false, authenticated:()=>authenticated,
      requiresLogin:()=>!authenticated, guest:()=>!authenticated, rememberedSession:()=>null,
      rememberSession(){}, logout:async options=>logout.push(options), open:reason=>opened.push(reason)};
    f.context.fetch = async (url, options={}) => {
      called.push({url,options});
      if (options.method==='POST') return reply({session_id:'own',messages:[]});
      if (url==='/api/chat/conversations') return reply({conversations:[{session_id:'another',title:'另一对话'}],retention_days:0});
      if (url==='/api/chat/conversations/another') return reply({session_id:'another',messages:[]});
      return reply({detail:{code:'conversation_other_account',message:warning}},403);
    };
    f.run('conversation-history.js'); await settle();
    if (!loggedIn) {
      assert.equal(opened.length,1, 'linked guest opens existing login flow');
      assert.equal(called.length,0, 'linked guest never creates an unrelated conversation');
      assert.equal(f.replaced, undefined);
      authenticated = true; f.fire('huhua-account-changed', {}); await settle();
    }
    assert.ok(called.some(c=>c.url==='/api/chat/conversations/foreign?from=mcp'));
    assert.equal(f.ids.get('conversation-status').textContent, warning);
    await f.ids.get('conversation-bar').children.find(n=>n.textContent==='退出登录').click();
    assert.equal(logout[0].returnToCurrent,true);
    assert.equal(f.replaced,undefined,'failed read preserves the original URL');
    await f.ids.get('btn-new-chat').click(); await settle();
    assert.equal(f.context.SESSION_ID,'own');
    await f.ids.get('conversation-list').children[0].children[0].click(); await settle();
    assert.equal(f.context.SESSION_ID,'another');
    assert.ok(!called.some(c=>c.url.includes('/another?from=')), 'source marker is scoped to the original link');
  }
}

async function logoutCheck() {
  const f = fixture('resume.html'), removed = [], calls = [];
  f.context.location.href = 'https://huhua.test/resume?session=foreign&from=mcp&template=t001-jianyue';
  const original = f.context.location.href;
  f.document.readyState = 'loading';
  f.context.clearInterval = () => {};
  f.context.confirm = () => true;
  f.context.Event = class {constructor(type){this.type=type;}};
  f.window.dispatchEvent = event => f.fire(event.type,event);
  f.window.localStorage = {'huhua_session_id':'foreign',removeItem:key=>removed.push(key)};
  f.window.sessionStorage = {'huhua_editor_draft:foreign':'draft',removeItem:key=>removed.push(key)};
  let failed = true, release;
  f.context.fetch = async (url, options) => {
    calls.push({url,options});
    if (url==='/api/account/me') return reply({authenticated:true,login_available:true});
    if (failed) return reply({detail:'退出失败'},503);
    return new Promise(resolve=>{release=()=>resolve(reply({}));});
  };
  f.run('account-profile.js'); await f.window.HuhuaAccount.ready;
  await assert.rejects(f.window.HuhuaAccount.logout({returnToCurrent:true}), /退出失败/);
  assert.equal(f.context.location.href,original); assert.ok(!removed.includes('huhua_session_id'));
  failed = false;
  const first = f.window.HuhuaAccount.logout({returnToCurrent:true}); await tick();
  assert.equal(await f.window.HuhuaAccount.logout({returnToCurrent:true}),false,'logout is single flight');
  release(); await first;
  assert.ok(removed.includes('huhua_session_id'));
  assert.equal(f.context.location.href,original);
  assert.equal(calls.filter(c=>c.url==='/api/account/logout').length,2);
  const ordinary = f.window.HuhuaAccount.logout(); await tick(); release(); await ordinary;
  assert.equal(f.context.location.href,'/chat','ordinary logout keeps existing destination');
}

({editor:editorCheck,chat:chatCheck,logout:logoutCheck}[process.argv[2]])()
  .then(()=>console.log('batch18a DOM checks passed')).catch(error=>{console.error(error);process.exitCode=1;});
