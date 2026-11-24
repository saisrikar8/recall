const {test}=require('node:test');
const assert=require('node:assert/strict');
const {_electron:electron,expect}=require('@playwright/test');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const root=path.resolve(__dirname,'../..');
test('quick search finds and launches apps while file search is blocked',{timeout:60000,skip:process.platform!=='darwin'},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'recall-app-launcher-'));
 const desktop=await electron.launch({args:[path.join(root,'desktop')],cwd:root,env:{...process.env,RECALL_DB_PATH:path.join(dir,'index.db'),RECALL_DESKTOP_USER_DATA:path.join(dir,'user-data'),RECALL_DISABLE_AUTOSTART:'1',RECALL_PYTHON:path.join(root,'.venv/bin/python'),RECALL_EMBEDDING_SOCKET:path.join(dir,'unused.sock'),HF_HUB_OFFLINE:'1',TRANSFORMERS_OFFLINE:'1'},timeout:30000});
 try{
  const page=await desktop.firstWindow();await page.locator('#recall-onboarding').waitFor();await page.locator('[data-ob="skip"]').click();
  await desktop.evaluate(({ipcMain,shell})=>{
    globalThis.recallOpenedApps=[];globalThis.recallFileSearchStarted=false;
    shell.openPath=async target=>{globalThis.recallOpenedApps.push(target);return globalThis.recallOpenedApps.length===1?'Test launch failure':'';};
    ipcMain.removeHandler('recall:search');ipcMain.handle('recall:search',()=>{globalThis.recallFileSearchStarted=true;return new Promise(()=>{});});
  });
  const nextWindow=desktop.waitForEvent('window');await page.evaluate(()=>window.recall.launcher());const launcher=await nextWindow;
  await launcher.locator('#search-input').fill('calculator');
  await expect(launcher.locator('.file-row').filter({hasText:'Calculator'})).toHaveCount(1,{timeout:10000});
  await expect(launcher.locator('.application-preview')).toContainText('Calculator');
  await expect.poll(()=>desktop.evaluate(()=>globalThis.recallFileSearchStarted)).toBe(true);
  await assert.rejects(launcher.evaluate(()=>window.recall.launchApp('/System/Applications/Calculator.app')),/available/);
  await launcher.locator('#search-input').press('Enter');
  await expect(launcher.locator('#toast')).toContainText('Test launch failure');
  await expect(launcher.locator('.application-preview')).toBeVisible();
  await launcher.screenshot({path:'/tmp/recall-app-search.png',scale:'css'});
  await launcher.locator('#search-input').press('Enter');
  await expect.poll(()=>desktop.evaluate(()=>globalThis.recallOpenedApps.length)).toBe(2);
  await expect.poll(()=>desktop.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(win=>win.webContents.getURL().includes('mode=launcher')).isVisible())).toBe(false);
  const targets=await desktop.evaluate(()=>globalThis.recallOpenedApps);assert.ok(targets.every(value=>value.endsWith('/Calculator.app')));
 }finally{await desktop.close();fs.rmSync(dir,{recursive:true,force:true});}
});
