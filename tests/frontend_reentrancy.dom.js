// Production controllers, synthetic DOM/data and deliberately pending requests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {fixture, tick} = require('./resume_embedded.dom.js');
const settle = async () => { for (let i = 0; i < 4; i++) await tick(); };
const root = path.resolve(__dirname, '..');
const descendants = node => [node, ...node.children.flatMap(descendants)];
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };
const response = (body = {}, ok = true, status = 200) => ({ok, status, headers: {get: () => ''}, json: async () => structuredClone(body)});
function dom(page, options) {
  const f = fixture(page, options), events = {};
  const proto = Object.getPrototypeOf(f.document.body);
  const matches = (node, selector) => {
    const attribute = selector.match(/\[([^=\]]+)="([^"]*)"\]/);
    if (attribute) {
      const key = attribute[1].replace(/^data-/, '').replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      if ((attribute[1].startsWith('data-') ? node.dataset[key] : node.attributes[attribute[1]]) !== attribute[2]) return false;
    }
    const cls = selector.match(/^\.([\w-]+)/);
    if (cls) return (node.className || '').split(' ').includes(cls[1]);
    const tag = selector.match(/^[a-z]+/i);
    return !tag || node.tagName === tag[0].toUpperCase();
  };
  proto.querySelectorAll = function(selector) { return descendants(this).slice(1).filter(node => selector.split(',').some(part => matches(node, part.trim()))); };
  proto.querySelector = function(selector) { return this.querySelectorAll(selector)[0] || null; };
  proto.prepend = function(...nodes) { for (const node of nodes) node.parentElement = this; this.children.unshift(...nodes); };
  proto.appendChild = function(node) { this.append(node); return node; };
  Object.defineProperty(proto, 'value', {get() { return this._value ?? (this.tagName === 'SELECT' ? this.children[0]?.value || '' : ''); }, set(value) { this._value = value; }});
  proto.reportValidity = () => true;
  proto.getAttribute = function(name) { return this.attributes[name]; };
  proto.click = async function() {
    if (this.disabled) return;
    for (const handler of this.handlers.click || []) await handler({currentTarget: this, target: this, preventDefault() {}});
  };
  f.document.addEventListener = (type, handler) => (events[type] ||= []).push(handler);
  f.key = async key => { for (const handler of events.keydown || []) await handler({key, preventDefault() {}}); await tick(); };
  f.context.setInterval = () => 1; f.context.clearInterval = () => {};
  return f;
}
const buttons = (node, text) => descendants(node).filter(n => n.tagName === 'BUTTON' && n.textContent === text);
async function submit(form) { for (const handler of form.handlers.submit || []) await handler({preventDefault() {}}); await tick(); }
async function panel() {
  const f = dom('index.html'); f.context.location.search = '?session=synthetic-session';
  const calls = [], jobs = [{id:'job1',session_id:'synthetic-session',name:'合成岗位',revision:1}, {id:'job2',session_id:'other',name:'另一个岗位',revision:1}];
  let pending;
  f.context.fetch = async (url, options = {}) => {
    calls.push({url, options});
    if (options.method && options.method !== 'GET') return pending.promise;
    if (url === '/api/account/me') return response({authenticated:true,login_available:true,account:{email:'fixture@example.test'}});
    if (url === '/api/profile') return response({revision:1,facts:[],conflicts:[],jobs});
    if (url.endsWith('/inbox')) return response({items:[{id:'i1',category:'project',subject:'合成项目',field:'description',value:'合成建议',evidence:'合成依据'}],pending_count:1});
    return response({tokens:[],recent_calls:[]});
  };
  f.run('account-profile.js'); await tick(); await f.window.HuhuaAccount.open();
  return {f, calls, content: f.ids.get('profile-content'), hold() { pending = deferred(); return pending; }};
}
async function inline(kind) {
  const {f, calls, content, hold} = await panel();
  const labels = {name:['改名','保存名称'],job:['保存当前岗位版本','保存岗位版本'],fact:['补充一条信息','加入个人档案']};
  const [label, saveLabel] = labels[kind];
  const trigger = buttons(content, label)[0];
  await trigger.click(); await trigger.click(); await trigger.click();
  const forms = content.querySelectorAll('form');
  assert.equal(forms.length, 1, 'three clicks leave one inline form');
  const form = forms[0], input = form.querySelector(kind === 'fact' ? 'textarea' : 'input');
  input.value = '保留的输入'; await trigger.click();
  assert.equal(input.value, '保留的输入');
  assert.equal(f.document.activeElement, form.querySelector('input,textarea,select'), 'reopen focuses existing input');
  if (kind !== 'fact') assert.equal(trigger.getAttribute('aria-expanded'), 'true');
  // A different card has its own form; neither card stacks editors.
  if (kind === 'name') {
    await buttons(content, label)[1].click();
    assert.equal(content.querySelectorAll('form').length, 2);
    await buttons(content, '取消')[1].click(); await buttons(content, label)[0].click();
  }
  const currentForm = content.querySelector('form'), save = buttons(currentForm, saveLabel)[0];
  currentForm.reportValidity = () => false; await submit(currentForm);
  assert.equal(calls.filter(c => c.options.method === 'POST' || c.options.method === 'PATCH').length, 0);
  currentForm.reportValidity = () => true;
  let wait = hold(); await submit(currentForm); await submit(currentForm); await submit(currentForm);
  assert.equal(save.disabled, true);
  assert.equal(calls.filter(c => c.options.method === 'POST' || c.options.method === 'PATCH').length, 1, 'pending save is single flight');
  wait.resolve(response({detail:'合成失败'}, false, 503)); await tick();
  assert.equal(save.disabled, false, 'failed save restores controls and preserves the form');
  assert.equal(content.querySelectorAll('form').length, 1);
  wait = hold(); await submit(currentForm); await submit(currentForm);
  assert.equal(calls.filter(c => c.options.method === 'POST' || c.options.method === 'PATCH').length, 2);
  wait.resolve(response()); await settle();
  assert.equal(content.querySelectorAll('form').length, 0, 'successful save closes editor');
  const reopened = buttons(content, label)[0];
  assert.equal(reopened.disabled, false);
  if (kind !== 'fact') assert.equal(reopened.getAttribute('aria-expanded'), 'false');
  await reopened.click(); await buttons(content, '取消')[0].click();
  assert.equal(content.querySelectorAll('form').length, 0);
  assert.equal(buttons(content, label)[0].disabled, false);
}
async function mcp() {
  const {f, calls, content, hold} = await panel();
  await f.window.HuhuaAccount.open('', 'connect');
  let wait = hold(), form = content.querySelector('form');
  const generating = submit(form); await tick(); await submit(form); await submit(form);
  assert.equal(calls.filter(c => c.url.endsWith('/tokens') && c.options.method === 'POST').length, 1);
  assert.equal(buttons(form, '生成令牌')[0].disabled, true);
  wait.resolve(response({detail:'合成失败'},false,503)); await generating;
  assert.equal(buttons(form, '生成令牌')[0].disabled, false);
  await f.window.HuhuaAccount.open();
  await buttons(content, '信息确认')[0].click();
  wait = hold(); const accept = buttons(content, '确认')[0];
  const accepting = accept.click(); await accept.click(); await accept.click();
  assert.equal(calls.filter(c => c.url.endsWith('/i1/accept')).length, 1);
  assert.equal(accept.disabled, true);
  wait.resolve(response({detail:'合成失败'},false,503)); await accepting; assert.equal(accept.disabled, false);
  await f.key('Escape'); assert.equal(f.ids.get('profile-overlay').hidden, true);
}
async function review() {
  const f = dom('index.html');
  const html = fs.readFileSync(root + '/web/index.html', 'utf8');
  const update = html.slice(html.indexOf('function updateFlowActions()'), html.indexOf('function setSendButtonMode'));
  const start = html.indexOf("document.getElementById('btn-review-current').addEventListener");
  const handler = html.slice(start, html.indexOf("window.addEventListener('focus'", start));
  let reads = 0, sends = 0, wait = deferred(), turn = deferred();
  Object.assign(f.context, {messages:[{}],reviewPending:false,currentController:null,conversationBusy:false,conversationReady:true,SESSION_ID:'a',canvasState:{hasData:true},
    refreshCanvas: () => { reads++; return wait.promise; }, send: () => { sends++; return turn.promise; }});
  vm.runInNewContext(update + handler, f.context);
  vm.runInNewContext('updateFlowActions()', f.context);
  const button = f.ids.get('btn-review-current'), first = button.click();
  button.click(); button.click(); await tick();
  assert.equal(reads, 1); assert.equal(button.disabled, true, 'locked before reading current draft');
  vm.runInNewContext('updateFlowActions()', f.context); assert.equal(button.disabled, true);
  wait.resolve(true); await tick(); assert.equal(sends, 1);
  await button.click(); assert.equal(reads, 1, 'remains locked until model turn settles');
  turn.resolve(true); await first; assert.equal(button.disabled, false);
  wait = deferred(); const next = button.click(); wait.resolve(false); await next;
  assert.equal(sends, 1, 'failed read does not start a check'); assert.equal(button.disabled, false);
  wait = deferred(); const switched = button.click(); f.context.SESSION_ID = 'b'; wait.resolve(true); await switched;
  assert.equal(sends, 1, 'delayed read cannot check a different conversation');
  wait = deferred(); f.context.refreshCanvas = () => { throw new Error('synthetic failure'); };
  await assert.rejects(button.click(), /synthetic failure/); assert.equal(button.disabled, false);
}
async function undo() {
  const f = dom('index.html'); f.run('change-card.js');
  const options = {session: () => 'synthetic-session'}, meta = {diff:[{section:'summary',field:'summary',before:'旧定位',after:'新定位'}]};
  const card = f.window.HuhuaChangeCard.create(meta, options), button = buttons(card,'撤销这次修改')[0];
  let reads = 0, wait = deferred();
  f.context.fetch = async () => { reads++; return wait.promise; };
  const first = button.click(); await button.click(); assert.equal(reads,1); assert.equal(button.disabled,true);
  f.window.HuhuaChangeCard.create(meta, options);
  wait.resolve(response({},false,503)); await first;
  assert.equal(button.disabled,true,'failed old undo cannot reactivate a superseded card');
  await button.click(); assert.equal(reads,1);
  const fresh = f.window.HuhuaChangeCard.create(meta,options), retry = buttons(fresh,'撤销这次修改')[0];
  wait = deferred(); const failing = retry.click(); wait.resolve(response({},false,503)); await failing;
  assert.equal(retry.disabled,false,'current card can retry a failed undo');
}
function editor() {
  const f = dom('resume.html', {embedded:true});
  const menu = f.ids.get('export-menu');
  for (const format of ['pdf','docx']) { const option = f.document.createElement('button'); option.className='export-opt'; option.dataset.format=format; menu.append(option); }
  f.document.querySelectorAll = selector => selector === '.export-opt' ? menu.children : [];
  f.run('resume-editor.js', code => code.replace('  initialise();', `  window.fixture = {state, changed, flushSave, startBlank, seed() {
    state.session = 'session-a'; state.serverRevision = 'r1'; state.canSave = true; editorLoaded = true;
    activateData({basic_info: {name: '合成同学'}, sections: []}, 'personal');
  }};`));
  f.window.fixture.seed(); return f;
}
async function save() {
  const f = editor(), api = f.window.fixture, retry = f.ids.get('btn-retry-save');
  api.changed(); let puts=0, wait=deferred();
  f.context.fetch = async () => { puts++; return wait.promise; };
  const first=retry.click(); retry.click(); retry.click(); await tick();
  assert.equal(puts,1); assert.equal(retry.disabled,true);
  wait.resolve(response({detail:{message:'合成失败'}},false,503)); await first;
  assert.equal(retry.disabled,false);
  wait=deferred(); const second=retry.click(); await retry.click(); assert.equal(puts,2);
  wait.resolve(response({saved:true,revision:'r2'})); await second; assert.equal(retry.disabled,false);
}
async function draft() {
  const f=editor(), api=f.window.fixture, trigger=f.document.createElement('button');
  trigger.addEventListener('click',api.startBlank); api.state.canSave=false;
  let posts=0, wait=deferred();
  f.context.fetch=async () => { posts++; return wait.promise; };
  const first=trigger.click(); await trigger.click(); assert.equal(posts,1); assert.equal(trigger.disabled,true);
  wait.resolve(response({detail:'合成失败'},false,503)); await first; assert.equal(trigger.disabled,false);
  f.context.history={replaceState(){}}; api.state.canSave=true;
  await trigger.click(); assert.equal(trigger.disabled,false); assert.equal(api.state.mode,'personal');
}
async function exporting() {
  const f=editor(), api=f.window.fixture, retry=f.ids.get('btn-retry-export'), options=f.ids.get('export-menu').children;
  api.state.template={id:'synthetic-template'}; api.state.exportFormat='pdf';
  let exports=0, wait=deferred(); f.context.fetch=async () => { exports++; return wait.promise; };
  const first=retry.click(); await tick(); await retry.click();
  assert.equal(exports,1); assert.equal(retry.disabled,true); assert.ok(options.every(option=>option.disabled));
  wait.resolve(response({detail:'合成失败'},false,503)); await first;
  assert.equal(retry.disabled,false); assert.equal(f.ids.get('btn-export').disabled,false); assert.ok(options.every(option=>!option.disabled));
  wait=deferred(); const second=options[0].click(); await tick(); await options[1].click(); assert.equal(exports,2);
  wait.resolve(response({detail:'合成失败'},false,503)); await second; assert.equal(retry.disabled,false);
}
async function escape() {
  const f=editor(), api=f.window.fixture;
  api.changed(); let puts=0, wait=deferred();
  f.context.fetch=async () => { puts++; return wait.promise; };
  await f.key('Escape'); await f.key('Escape'); assert.equal(puts,1); assert.equal(f.posts.length,0);
  wait.resolve(response({detail:{message:'合成失败'}},false,503)); await tick();
  assert.equal(f.posts.length,0,'save failure leaves editor open');
  wait=deferred(); await f.key('Escape'); wait.resolve(response({saved:true,revision:'r2'})); await tick();
  assert.equal(f.posts.filter(row=>row.data.type==='resume-editor-close').length,1);
  f.posts.length=0; f.ids.get('export-menu').hidden=false; await f.key('Escape');
  assert.equal(f.ids.get('export-menu').hidden,true); assert.equal(f.posts.length,0,'first Escape closes menu only');
  const profile=f.document.createElement('div'); profile.id='profile-overlay'; profile.hidden=false;
  await f.key('Escape'); assert.equal(f.posts.length,0,'profile handles its own Escape'); profile.hidden=true;
  f.fire('message',{source:{},data:{type:'resume-preview-escape'}}); await tick(); assert.equal(f.posts.length,0);
  f.fire('message',{source:f.ids.get('preview-frame').contentWindow,data:{type:'resume-preview-escape'}}); await tick();
  assert.equal(f.posts.filter(row=>row.data.type==='resume-editor-close').length,1);
}
async function modal() {
  const f=dom('index.html'); f.run('resume-actions.js'); const actions=f.window.HuhuaResumeActions;
  actions.init({session:()=> 'synthetic-session'}); actions.sync({has_data:true,data:{},revision:'r1'});
  await f.ids.get('btn-edit-resume').click(); await f.ids.get('btn-edit-resume').click(); await f.ids.get('btn-edit-resume').click();
  const overlay=f.ids.get('resume-editor-overlay'); assert.equal(overlay.children.length,1);
  for (const handler of overlay.handlers.keydown) handler({key:'Escape',preventDefault(){}});
  assert.equal(overlay.hidden,true); assert.equal(f.main.inert,undefined);
}
async function previewEscape() {
  const f=dom('resume.html'); f.document.head=f.document.createElement('head');
  f.document.body.getBoundingClientRect=()=>({height:1123});
  f.run('resume-preview.js'); f.posts.length=0; await f.key('Escape');
  assert.equal(f.posts[0].data.type,'resume-preview-escape');
}
const checks = {rename:()=>inline('name'),job:()=>inline('job'),fact:()=>inline('fact'),mcp,review,undo,save,draft,exporting,escape,modal,previewEscape};
checks[process.argv[2]]().then(()=>console.log('frontend reentrancy DOM check passed')).catch(error=>{console.error(error);process.exitCode=1;});
