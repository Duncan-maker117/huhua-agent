const assert = require('node:assert/strict');
const {fixture, tick} = require('./resume_embedded.dom.js');
const all = el => [el, ...el.children.flatMap(all)];
const text = el => [el.textContent, ...el.children.map(text)].join('|');
(async () => {
  const f = fixture('resume.html', {embedded:true});
  f.run('resume-editor.js', code => code.replace('  initialise();', `
    window.fixture = {state, flushSave, seed() {
      state.session='session-a'; state.serverRevision='r1'; state.canSave=true; editorLoaded=true;
      activateData({projects:[{name:'项目',tech_stack:['MCP']}],work_experience:[{company:'公司'}]}, 'personal');
    }};`));
  f.window.fixture.seed();
  f.window.fixture.state.ready = true;
  for (const [section, value] of [['projects','MCP，longchain、Tool Calling'],['work_experience','Python, FastAPI']]) {
    const input = all(f.ids.get('form-editor')).find(el => el.dataset.inputPath === `/${section}/0/tech_stack`);
    assert.ok(input);
    if (section === 'projects') assert.equal(input.value, 'MCP');
    input.value=value;
    for (const fn of input.handlers.input) await fn({target:input});
    assert.ok(Array.isArray(f.window.fixture.state.data[section][0].tech_stack));
  }
  assert.ok(f.posts.some(p => p.data.type === 'resume-field-value' && p.data.path === '/projects/0/tech_stack'
    && p.data.value === '技术栈：MCP、longchain、Tool Calling'));
  let saved;
  f.context.fetch = async (_, options) => {
    saved=JSON.parse(options.body).resume_data;
    return {ok:true,json:async()=>({saved:true,revision:'r2',data:saved})};
  };
  await f.window.fixture.flushSave(); await tick();
  assert.deepEqual(saved.projects[0].tech_stack, ['MCP','longchain','Tool Calling']);
  assert.deepEqual(saved.work_experience[0].tech_stack, ['Python','FastAPI']);
  const input = all(f.ids.get('form-editor')).find(el => el.dataset.inputPath === '/projects/0/tech_stack');
  input.value=''; for (const fn of input.handlers.input) await fn({target:input});
  await f.window.fixture.flushSave();
  assert.deepEqual(saved.projects[0].tech_stack, []);
  input.value='mcp,MCP,toolcalling,Tool Calling,longchain,LangChain,Python,Rust,Go';
  for (const fn of input.handlers.input) await fn({target:input});
  await f.window.fixture.flushSave();
  assert.equal(saved.projects[0].tech_stack.at(-1), 'Go', 'aliases must normalize before applying the server limit');
  f.run('change-card.js');
  const api = f.window.HuhuaChangeCard;
  const card = api.create({diff:[{section:'projects',item_id:'p',before:{name:'项目',tech_stack:['MCP']},after:{name:'项目',tech_stack:['MCP','LangChain']}}]});
  assert.ok(text(card).includes('技术栈：MCP → MCP、LangChain'));
})().catch(error => { console.error(error); process.exit(1); });
