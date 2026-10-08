// Disposable :8893 static-server fixture. All APIs and candidate data are mocked.
async (page) => {
  await page.unroute('**/api/**'); page.removeAllListeners('pageerror'); page.removeAllListeners('dialog');
  const checks=[], errors=[], requests=[]; const check=(id,value)=>{checks.push({id,passed:Boolean(value)});if(!value)throw new Error(id);};
  page.on('pageerror',error=>errors.push(error.message)); page.on('dialog',dialog=>dialog.accept());
  const clone=value=>JSON.parse(JSON.stringify(value));
  const fixture='provenance-fixture';
  const sessions={[fixture]:{revision:'revision-1',data:{basic_info:{name:'虚构来源验收'},education:[{item_id:'edu-1',school:'虚构学校',degree:'本科'}],work_experience:[{item_id:'work-1',company:'虚构公司',title:'实习',bullets:['完成虚构测试']}],projects:[{item_id:'project-1',name:'虚构项目一',description:'完成本地功能'},{item_id:'project-2',name:'虚构项目二',description:'完成合成样例'},{item_id:'project-3',name:'虚构项目三',description:'整理测试结果'}],skills:[]}}};
  const sample={basic_info:{name:'原始样例人'},projects:[{name:'样例项目',description:'原始样例内容'}],education:[],work_experience:[],skills:[]};
  let requireAccount=true, failSave=false, holdNext=false, held=null, heldReady=null, created=0, saved=0, assignNewId=false;
  const workspace=session=>({jd:{},experiences:{items:[]},review:{items:[]},resume:{has_data:!!session.data,version:session.revision},suggestions:[]});
  const queryValue=(url,key)=>{const query=url.split('?')[1]||'';const pair=query.split('&').find(part=>part.split('=')[0]===key);return pair?decodeURIComponent(pair.split('=').slice(1).join('=')):null;};
  const completeSave=async(route,body)=>{
    const data=clone(body.resume_data);
    if(assignNewId){const item=data.projects?.find(item=>!item.item_id);if(item)item.item_id='server-assigned-project';assignNewId=false;}
    const revision='saved-'+(++saved);sessions[body.session_id]={data,revision};
    await route.fulfill({json:{saved:true,revision,data}});
  };
  await page.route('**/api/**',async route=>{
    const url=route.request().url(),path='/'+url.split('/').slice(3).join('/').split('?')[0],method=route.request().method();
    const body=['POST','PUT','PATCH'].includes(method)?route.request().postDataJSON():null;
    requests.push({url,path,method,body});
    if(path==='/api/account/me')return route.fulfill({json:{authenticated:requireAccount,account:requireAccount?{id:'fixture',email:'fixture@example.com'}:null,require_account:requireAccount,login_available:true}});
    if(path==='/api/resume/templates')return route.fulfill({json:{templates:[{id:'fixture',name:'测试模板'},{id:'second',name:'第二模板'}]}});
    if(path==='/api/resume/sample')return route.fulfill({json:sample});
    if(path==='/api/resume/current'){
      if(method==='PUT'){
        if(failSave)return route.fulfill({status:503,json:{detail:{message:'模拟保存失败'}}});
        if(holdNext){holdNext=false;held={route,body};heldReady?.();return;}
        return completeSave(route,body);
      }
      const id=queryValue(url,'session_id'),session=sessions[id]||{data:null,revision:'empty-revision'};
      return route.fulfill({json:{has_data:!!session.data,data:session.data,revision:session.revision,can_save:true,stage:'EVALUATING',workspace:workspace(session)}});
    }
    if(path.startsWith('/api/resume/render/'))return route.fulfill({contentType:'text/html',body:'<!doctype html><html><body><p>'+body.basic_info.name+'</p><script>parent.postMessage({type:"resume-preview-ready",height:1123},"*");</script></body></html>'});
    if(path.startsWith('/api/resume/export/docx/'))return route.fulfill({contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers:{'Content-Disposition':"attachment; filename*=UTF-8''fixture.docx"},body:'PK\x03\x04synthetic-docx-fixture'});
    if(path.startsWith('/api/resume/export/pdf/'))return route.fulfill({contentType:'application/pdf',headers:{'Content-Disposition':"attachment; filename*=UTF-8''fixture.pdf"},body:'%PDF-1.4\n% synthetic fixture\n%%EOF'});
    if(path==='/api/chat/conversations'&&method==='POST'){created++;const id='created-draft-'+created;sessions[id]={data:null,revision:'empty-revision'};return route.fulfill({json:{session_id:id,title:'新对话'}});}
    if(path==='/api/chat/conversations')return route.fulfill({json:{conversations:[{session_id:fixture,title:'来源验收',updated_at:'2026-10-05'}]}});
    if(path==='/api/chat/conversations/'+fixture)return route.fulfill({json:{session_id:fixture,messages:[],stage:'EVALUATING',workspace:workspace(sessions[fixture])}});
    return route.fulfill({status:404,json:{detail:'模拟范围外'}});
  });
  const field=path=>page.locator('[data-input-path="'+path+'"]');
  const removeItem=path=>page.locator('.item-editor').filter({has:field(path)}).getByRole('button',{name:'删除',exact:true}).click();
  const flush=()=>page.evaluate(()=>window.HuhuaEditor.prepareProfileChange());
  const puts=()=>requests.filter(request=>request.path==='/api/resume/current'&&request.method==='PUT');
  const renders=()=>requests.filter(request=>request.path.startsWith('/api/resume/render/'));
  await page.setViewportSize({width:1440,height:960});
  await page.goto('http://127.0.0.1:8893/resume?session='+fixture);
  await field('/projects/0/name').waitFor();
  await page.waitForFunction(()=>document.getElementById('render-status').textContent==='已实时更新');
  check('personal-preview-has-session',queryValue(renders().at(-1).url,'session_id')===fixture);
  check('preview-does-not-save',puts().length===0);
  await field('/projects/0/name').fill('改名后的同一项目'); await flush();
  check('rename-preserves-stable-item-id',puts().at(-1).body.resume_data.projects[0].item_id==='project-1'&&puts().at(-1).body.resume_data.projects[0].name==='改名后的同一项目');
  check('rename-is-not-deletion',puts().at(-1).body.removed_item_ids.length===0);
  failSave=true;
  await removeItem('/education/0/school'); await removeItem('/work_experience/0/company');
  await page.waitForFunction(()=>document.getElementById('render-status').textContent==='已实时更新');
  check('unsaved-deletions-in-preview-query',renders().at(-1).url.includes('removed_item_ids=edu-1')&&renders().at(-1).url.includes('removed_item_ids=work-1'));
  check('failed-save-keeps-deletions',await flush()===false&&puts().at(-1).body.removed_item_ids.includes('edu-1')&&puts().at(-1).body.removed_item_ids.includes('work-1'));
  failSave=false; await page.getByRole('button',{name:'重试保存',exact:true}).click();
  await page.waitForFunction(()=>document.getElementById('save-status').textContent.startsWith('已保存'));
  check('retry-resends-deleted-ids',puts().at(-1).body.removed_item_ids.length===2);
  await field('/basic_info/name').fill('删除后继续编辑'); await flush();
  check('acknowledged-deletion-not-repeated',puts().at(-1).body.removed_item_ids.length===0);
  holdNext=true;const firstHeld=new Promise(resolve=>{heldReady=resolve;});
  await removeItem('/projects/0/name'); await firstHeld;
  check('first-delete-snapshot-bound',held.body.removed_item_ids.length===1&&held.body.removed_item_ids[0]==='project-1');
  await removeItem('/projects/0/name'); await field('/projects/0/name').fill('保存期间继续输入');
  await completeSave(held.route,held.body); held=null; await flush();
  check('inflight-save-does-not-drop-new-deletion',puts().at(-1).body.removed_item_ids.length===1&&puts().at(-1).body.removed_item_ids[0]==='project-2');
  check('save-response-does-not-overwrite-live-input',await field('/projects/0/name').inputValue()==='保存期间继续输入'&&sessions[fixture].data.projects[0].item_id==='project-3');
  await page.getByRole('button',{name:'＋ 添加项目',exact:true}).click(); await field('/projects/1/name').fill('等待服务端ID');
  holdNext=true;assignNewId=true;const metadataHeld=new Promise(resolve=>{heldReady=resolve;});
  await metadataHeld;
  await field('/projects/1/name').fill('返回期间继续改名');
  await completeSave(held.route,held.body);held=null;await flush();
  check('server-id-merged-without-overwriting-input',puts().at(-1).body.resume_data.projects[1].item_id==='server-assigned-project'&&await field('/projects/1/name').inputValue()==='返回期间继续改名');
  await page.setViewportSize({width:390,height:844});await page.locator('#btn-mobile-edit').click();
  check('mobile-edit-remains-usable',await field('/basic_info/name').isVisible()&&await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'/private/tmp/huhua-provenance-mobile.png'});
  await page.locator('#btn-mobile-preview').click();
  await page.locator('#btn-export').click();const personalDownload=page.waitForEvent('download');await page.getByRole('button',{name:'通用 Word',exact:true}).click();await personalDownload;
  const personalExport=requests.filter(request=>request.path.startsWith('/api/resume/export/docx/')).at(-1);
  check('personal-export-has-session',queryValue(personalExport.url,'session_id')===fixture);
  check('export-after-save-has-no-pending-delete-query',!personalExport.url.includes('removed_item_ids'));
  await page.locator('#btn-export').click();const personalPdfReady=page.waitForEvent('download');await page.getByRole('button',{name:'导出 PDF',exact:true}).click();const personalPdf=await personalPdfReady;
  const personalPdfExport=requests.filter(request=>request.path.startsWith('/api/resume/export/pdf/')).at(-1);
  check('personal-pdf-download-completes',await personalPdf.failure()===null&&personalPdf.suggestedFilename().endsWith('.pdf'));
  check('personal-pdf-export-has-session',queryValue(personalPdfExport.url,'session_id')===fixture);
  check('personal-pdf-uses-saved-source-and-no-pending-deletions',JSON.stringify(personalPdfExport.body)===JSON.stringify(sessions[fixture].data)&&!personalPdfExport.url.includes('removed_item_ids'));
  await page.setViewportSize({width:1440,height:960});
  await page.evaluate(()=>localStorage.removeItem('huhua_session_id'));
  await page.goto('http://127.0.0.1:8893/resume');
  await field('/basic_info/name').waitFor();await page.waitForFunction(()=>document.getElementById('render-status').textContent==='已实时更新');
  check('account-sample-readonly',await field('/basic_info/name').isDisabled()&&await page.locator('#btn-upload-photo').isDisabled());
  check('sample-disclosure-and-new-draft-entry',(await page.locator('#sample-notice').textContent()).includes('只读模板样例')&&await page.getByRole('button',{name:'新建我的空白草稿',exact:true}).isEnabled());
  check('sample-preview-uses-exact-source',JSON.stringify(renders().at(-1).body)===JSON.stringify(sample)&&queryValue(renders().at(-1).url,'session_id')===null);
  const saveCount=puts().length;await page.locator('.tpl-item').nth(1).click();await page.waitForFunction(()=>document.getElementById('render-status').textContent==='已实时更新');
  check('sample-template-switch-never-saves',puts().length===saveCount);
  await page.locator('#btn-export').click();const sampleDownload=page.waitForEvent('download');await page.getByRole('button',{name:'通用 Word',exact:true}).click();await sampleDownload;
  const sampleExport=requests.filter(request=>request.path.startsWith('/api/resume/export/docx/')).at(-1);
  check('sample-export-exact-and-sessionless',JSON.stringify(sampleExport.body)===JSON.stringify(sample)&&queryValue(sampleExport.url,'session_id')===null);
  await page.locator('#btn-export').click();const samplePdfReady=page.waitForEvent('download');await page.getByRole('button',{name:'导出 PDF',exact:true}).click();await samplePdfReady;
  const samplePdfExport=requests.filter(request=>request.path.startsWith('/api/resume/export/pdf/')).at(-1);
  check('sample-pdf-export-exact-and-sessionless',JSON.stringify(samplePdfExport.body)===JSON.stringify(sample)&&queryValue(samplePdfExport.url,'session_id')===null);
  await page.getByRole('button',{name:'新建我的空白草稿',exact:true}).click();await page.waitForFunction(()=>document.getElementById('data-source').textContent==='当前会话');await flush();
  check('explicit-sample-to-personal-creates-once',created===1&&puts().at(-1).body.session_id==='created-draft-1'&&!puts().at(-1).body.resume_data.basic_info.name);
  check('new-personal-fields-enabled',await field('/basic_info/name').isEnabled());
  await page.evaluate(()=>localStorage.removeItem('huhua_session_id'));requireAccount=false;
  await page.goto('http://127.0.0.1:8893/resume');await field('/basic_info/name').waitFor();
  check('legacy-sample-remains-editable',await field('/basic_info/name').isEnabled());await field('/basic_info/name').fill('兼容模式样例修改');
  await page.waitForFunction(()=>document.getElementById('render-status').textContent==='已实时更新');check('legacy-sample-preview-keeps-edits',renders().at(-1).body.basic_info.name==='兼容模式样例修改');
  requireAccount=true;await page.goto('http://127.0.0.1:8893/?session='+fixture);
  await page.waitForFunction(()=>!document.getElementById('btn-export-docx').disabled);
  check('chat-preview-has-session',queryValue(renders().at(-1).url,'session_id')===fixture);
  const chatDownload=page.waitForEvent('download');await page.locator('#btn-export-docx').click();await chatDownload;
  check('chat-word-export-has-session',queryValue(requests.filter(request=>request.path.startsWith('/api/resume/export/docx/')).at(-1).url,'session_id')===fixture);
  check('no-browser-errors '+JSON.stringify(errors),errors.length===0);
  return {scope:'All APIs mocked; synthetic facts and item IDs; no real model, email or database.',checks,errors};
}
