const {test}=require('node:test');
const assert=require('node:assert/strict');
const {_electron:electron,expect}=require('@playwright/test');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const root=path.resolve(__dirname,'../..');
test('first launch, real indexing, first search, persistence and replay',{timeout:120000},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'recall-onboarding-'));
 const source=path.join(dir,'notes');fs.mkdirSync(source);fs.writeFileSync(path.join(source,'remember.md'),'# Remember\nA note about finding memories on your laptop.');
 const options={args:[path.join(root,'desktop')],cwd:root,env:{...process.env,RECALL_DB_PATH:path.join(dir,'index.db'),RECALL_PYTHON:path.join(root,'.venv/bin/python'),RECALL_EMBEDDING_SOCKET:path.join(dir,'unused.sock'),RECALL_DESKTOP_USER_DATA:path.join(dir,'user-data'),RECALL_DISABLE_AUTOSTART:'1',HF_HUB_OFFLINE:'1',TRANSFORMERS_OFFLINE:'1'},timeout:30000};
 let desktop=await electron.launch(options);
 try{
  let page=await desktop.firstWindow();const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const modal=page.locator('#recall-onboarding');await expect(modal).toBeVisible({timeout:30000});
  await page.screenshot({path:'/tmp/recall-onboarding-welcome.png',scale:'css'});
  await modal.getByRole('button',{name:'Get started'}).click();
  await desktop.evaluate(({dialog})=>{dialog.showOpenDialog=async()=>({canceled:true,filePaths:[]});});
  await modal.getByRole('button',{name:'Choose a folder'}).click();await expect(modal.locator('.ob-source')).toHaveCount(0);
  await desktop.evaluate(({dialog},folder)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[folder]});},source);
  await modal.getByRole('button',{name:'Choose a folder'}).click();await expect(modal.locator('.ob-source')).toHaveCount(1);
  assert.equal(await page.evaluate(async()=> (await window.recall.library()).files.length),0);
  await modal.getByRole('button',{name:'Continue',exact:false}).click();
  await modal.locator('#onboarding-login').uncheck();await modal.locator('[data-appearance="dark"]').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  await page.screenshot({path:'/tmp/recall-onboarding-preferences.png',scale:'css'});
  await modal.getByRole('button',{name:'Start indexing'}).click();
  await expect(modal.getByRole('button',{name:'Try a first search'})).toBeVisible({timeout:60000});
  await expect(modal.locator('.ob-ready-file')).toHaveCount(1);
  await page.screenshot({path:'/tmp/recall-onboarding-ready.png',scale:'css'});
  await modal.getByRole('button',{name:'Try a first search'}).click();await expect(modal).not.toBeVisible();
  await expect(page.locator('#search-input')).toHaveValue('remember.md');await expect(page.locator('.file-row')).toHaveCount(1);
  assert.equal(await page.evaluate(async()=> (await window.recall.preferences()).onboardingCompleted),true);
  assert.deepEqual(errors,[]);
  await desktop.close();desktop=await electron.launch(options);page=await desktop.firstWindow();await page.locator('.file-row').first().waitFor();
  await expect(page.locator('#recall-onboarding')).not.toBeVisible();
  await desktop.evaluate(({Menu})=>Menu.getApplicationMenu().getMenuItemById('onboarding').click());await expect(page.locator('#recall-onboarding')).toBeVisible();
  await page.keyboard.press('Escape');await expect(page.locator('#recall-onboarding')).not.toBeVisible();
  assert.equal(fs.existsSync(path.join(source,'remember.md')),true);
 }finally{await desktop.close();fs.rmSync(dir,{recursive:true,force:true});}
});
