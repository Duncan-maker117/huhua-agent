// Real app/OTP/profile/editor/export integration; ONLY SMTP is an in-memory test transport.
async (page) => {
  const base='http://127.0.0.1:8894', checks=[], errors=[]; let stage='start';
  const check=(id,passed,detail='')=>{checks.push({id,passed:Boolean(passed),detail});if(!passed)throw new Error(id+': '+detail);};
  page.removeAllListeners('pageerror');page.removeAllListeners('dialog');
  page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.accept());
  const request=async(path,method='GET',data)=>{const result=await page.request.fetch(base+path,{method,...(data===undefined?{}:{data}),headers:{Origin:base}});let body;try{body=await result.json();}catch{body={};}return{status:result.status(),body};};
  const login=async(email)=>{
    await page.locator('#btn-account-profile').click();
    await page.getByLabel('登录邮箱',{exact:true}).fill(email);await page.getByRole('button',{name:'发送验证码',exact:true}).click();
    await page.getByLabel('邮箱验证码',{exact:true}).waitFor();
    const otp=await request('/__test__/otp?email='+encodeURIComponent(email));check('mailbox-'+email,otp.status===200);
    await page.getByLabel('邮箱验证码',{exact:true}).fill(otp.body.code);await page.getByRole('button',{name:'登录',exact:true}).click();
    await page.waitForFunction(()=>document.getElementById('btn-account-profile')?.textContent==='我的档案'&&!document.getElementById('btn-send').disabled);
  };
  const addFact=async(category,subject,field,value)=>{
    await page.getByRole('button',{name:'补充一条信息',exact:true}).click();await page.getByLabel('资料类别',{exact:true}).selectOption(category);
    await page.getByLabel('属于哪段经历或信息',{exact:true}).fill(subject);await page.getByLabel('信息类型',{exact:true}).selectOption(field);await page.getByLabel('本人提供的内容',{exact:true}).fill(value);
    await page.getByRole('button',{name:'加入个人档案',exact:true}).click();await page.waitForFunction(text=>document.querySelector('.profile-status').textContent.includes('已加入')&&[...document.querySelectorAll('.profile-value')].some(n=>n.textContent===text),value);
  };
  let sessionA,sessionB, factId, revision, beforeDelete, audit;
  try{
    await page.setViewportSize({width:1440,height:960});await page.goto(base+'/');
    check('anonymous-private-blocked',(await request('/api/profile')).status===401);
    stage='login-a';await login('nora@huhua-fixture.invalid');sessionA=await page.evaluate(()=>new URLSearchParams(location.search).get('session'));
    check('account-cookie-http-only',(await page.context().cookies()).some(c=>c.name==='huhua_account'&&c.httpOnly&&c.sameSite==='Lax'));
    stage='add-real-profile';await page.locator('#btn-account-profile').click();await page.getByRole('button',{name:'补充一条信息',exact:true}).waitFor();
    await addFact('basic','基本信息','name','HUHUA_LIVE_NORA');
    let card=page.locator('.profile-card').filter({has:page.locator('.profile-value', {hasText:'HUHUA_LIVE_NORA'})});
    await card.getByRole('button',{name:'用于当前简历',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.profile-status').textContent.includes('已用于'));
    await addFact('project','虚构文档项目','description','本地合并虚构验收');
    card=page.locator('.profile-card').filter({has:page.locator('.profile-value', {hasText:'本地合并虚构验收'})});factId=await card.getAttribute('data-fact-id');
    await card.getByRole('button',{name:'用于当前简历',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.profile-status').textContent.includes('已用于'));
    const initial=await request('/api/resume/current?session_id='+encodeURIComponent(sessionA));check('real-fact-import',initial.status===200&&JSON.stringify(initial.body.data).includes('本地合并虚构验收'),JSON.stringify(initial.body));
    await page.screenshot({path:'evaluation/product-profile-live-2026-10-04/desktop-profile.png'});
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:'evaluation/product-profile-live-2026-10-04/mobile-profile.png'});
    check('real-mobile-bounds',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth&&document.getElementById('profile-drawer').getBoundingClientRect().width<=innerWidth));
    await page.keyboard.press('Escape');await page.setViewportSize({width:1440,height:960});
    stage='editor-save';await page.goto(base+'/resume?session='+encodeURIComponent(sessionA));
    await page.locator('[data-input-path="/basic_info/name"]').waitFor();await page.locator('[data-input-path="/basic_info/name"]').fill('HUHUA_LIVE_EDIT');
    await page.waitForFunction(()=>document.getElementById('save-status').textContent.startsWith('已保存到当前会话'));
    await page.reload();await page.locator('[data-input-path="/basic_info/name"]').waitFor();check('real-editor-refresh',await page.locator('[data-input-path="/basic_info/name"]').inputValue()==='HUHUA_LIVE_EDIT');
    beforeDelete=(await request('/api/resume/current?session_id='+encodeURIComponent(sessionA))).body.data;
    stage='word-export';const download=page.waitForEvent('download');await page.locator('#btn-export-docx').click();const exported=await download;await exported.saveAs('evaluation/product-profile-live-2026-10-04/nora-before-delete.docx');check('word-downloaded',exported.suggestedFilename().endsWith('.docx'));
    stage='delete-fact';await page.locator('#btn-account-profile').click();card=page.locator('[data-fact-id="'+factId+'"]');await card.getByRole('button',{name:'删除',exact:true}).click();await page.getByRole('button',{name:'确认删除这条事实',exact:true}).click();await page.waitForFunction(id=>!document.querySelector('[data-fact-id="'+id+'"]'),factId);
    check('real-fact-deleted',!(await request('/api/profile')).body.facts.some(f=>f.id===factId));
    const cleared=await request('/api/resume/current?session_id='+encodeURIComponent(sessionA));check('real-delete-current-sanitized',cleared.status===200&&!JSON.stringify(cleared.body.data).includes('本地合并虚构验收'));
    const denied=await page.request.post(base+'/api/resume/export/docx/t001-jianyue',{headers:{Origin:base},data:beforeDelete});check('stale-export-rejected',denied.status()===409);
    await page.keyboard.press('Escape');await page.reload();await page.waitForFunction(()=>document.getElementById('workspace-status').textContent.includes('简历'));
    const after=page.waitForEvent('download');await page.locator('#btn-export-docx').click();await (await after).saveAs('evaluation/product-profile-live-2026-10-04/nora-after-delete.docx');
    stage='second-account';await page.locator('#btn-account-profile').click();await page.getByRole('button',{name:'退出登录',exact:true}).click();await page.waitForFunction(()=>document.getElementById('btn-account-profile')?.textContent==='登录账号');
    await login('milo@huhua-fixture.invalid');sessionB=await page.evaluate(()=>new URLSearchParams(location.search).get('session'));
    check('accounts-get-distinct-session',sessionA!==sessionB);
    check('second-account-empty-profile',(await request('/api/profile')).body.facts.length===0);
    check('cross-account-current-blocked',(await request('/api/resume/current?session_id='+encodeURIComponent(sessionA))).status===404);
    check('cross-account-conversation-blocked',(await request('/api/chat/conversations/'+encodeURIComponent(sessionA))).status===404);
    check('cross-account-delete-blocked',(await request('/api/chat/session/'+encodeURIComponent(sessionA),'DELETE')).status===404);
    audit=(await request('/__test__/storage-audit')).body;check('disk-encrypted-markers',audit.plaintext_marker_found===false,JSON.stringify(audit.files));
    check('no-private-browser-cache',await page.evaluate(()=>![localStorage,sessionStorage].some(s=>Object.keys(s).some(k=>/^huhua_(messages|chat_backup:|chat_recovery:|editor_draft:)/.test(k)))));
    check('no-browser-errors',errors.length===0,JSON.stringify(errors));
    return{passed:true,scope:'Real encrypted main.app routes and lifecycle; mailbox transport only replaced; no model call or real user data.',checks,errors,sessionA,sessionB,audit};
  }catch(error){return{passed:false,stage,checks,errors,error:String(error),sessionA,sessionB};}
}
