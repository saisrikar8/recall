// Capture the real desktop UI using the explicitly synthetic test library.
const { _electron: electron, expect } = require('@playwright/test');
const { spawnSync } = require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const root=path.resolve(__dirname,'../..');
(async()=>{
 const dir=fs.mkdtempSync(path.join(process.platform==='darwin'?'/private/tmp':os.tmpdir(),'recall-demo-'));
 const python=process.env.RECALL_PYTHON || path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
 const fixture=spawnSync(python,[path.join(root,'desktop/tests/fixture.py'),dir],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONPATH:root}});
 if(fixture.status!==0)throw Error(fixture.stderr || fixture.stdout);
 const desktop=await electron.launch({args:[path.join(root,'desktop')],cwd:root,env:{...process.env,RECALL_DB_PATH:path.join(dir,'index.db'),RECALL_DESKTOP_USER_DATA:path.join(dir,'electron-data'),RECALL_PYTHON:python,RECALL_DISABLE_AUTOSTART:'1',RECALL_EMBEDDING_SOCKET:path.join(dir,'unused.sock'),HF_HUB_OFFLINE:'1',TRANSFORMERS_OFFLINE:'1'},timeout:30000});
 const out=path.join(root,'docs/screenshots');fs.mkdirSync(out,{recursive:true});
 const capture=(page,name)=>page.screenshot({path:path.join(out,name+'.png'),scale:'css',animations:'disabled',caret:'hide'});
 try{
  const page=await desktop.firstWindow();
  await page.locator('.file-row').first().waitFor();
  await page.locator('[data-appearance="light"]').click();
  await page.locator('.file-row').filter({hasText:'A note on remembering.md'}).click();
  await expect(page.locator('.document h1')).toHaveText('A note on remembering');
  await capture(page,'library');
  await page.locator('#search-input').fill('retrieval.py');
  await page.locator('#search-form').evaluate(form=>form.requestSubmit());
  await page.locator('#list-heading').filter({hasText:'SEARCH RESULTS'}).waitFor({timeout:60000});
  await page.locator('.code-view').waitFor();
  await expect(page.locator('#preview')).toHaveAttribute('aria-busy','false');
  await page.locator('.main').evaluate(node=>{node.scrollTop=0;});
  await capture(page,'search');
  await page.locator('[data-appearance="dark"]').click();
  const launcherPromise=desktop.waitForEvent('window');await page.evaluate(()=>window.recall.launcher());const launcher=await launcherPromise;
  await launcher.locator('.file-row').first().waitFor();
  await launcher.locator('.file-row').filter({hasText:'Field notes.pdf'}).click();
  await launcher.locator('.pdf-page img').waitFor();
  await expect(launcher.locator('#preview')).toHaveAttribute('aria-busy','false');
  await launcher.locator('.pdf-page img').evaluate(image=>image.decode());
  await capture(launcher,'quick-search');
  await launcher.evaluate(()=>window.recall.hide());
  await page.locator('[data-appearance="light"]').click();
  await desktop.evaluate(({Menu})=>Menu.getApplicationMenu().getMenuItemById('onboarding').click());
  await page.locator('#recall-onboarding').waitFor();
  await capture(page,'onboarding');
  console.log('Saved four desktop screenshots to docs/screenshots');
 }finally{await desktop.close();fs.rmSync(dir,{recursive:true,force:true,maxRetries:10,retryDelay:100});}
})().catch(error=>{console.error(error);process.exitCode=1;});
