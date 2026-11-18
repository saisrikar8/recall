// Exercise the built application without the development Python or Homebrew PATH.
const { _electron: electron, expect } = require('@playwright/test');
const { spawnSync } = require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
(async()=>{
 const bundle=path.resolve(process.argv[2] || '../dist/mac/mac-arm64/Recall.app');
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'recall-packaged-'));
 const source=path.join(dir,'Test notes');fs.mkdirSync(source);fs.writeFileSync(path.join(source,'remember.md'),'# Memory\nRecall helps you find notes about linear algebra, matrices and eigenvalues.');
 const env={...process.env,PATH:'/usr/bin:/bin:/usr/sbin:/sbin',RECALL_DB_PATH:path.join(dir,'index.db'),RECALL_DESKTOP_USER_DATA:path.join(dir,'user-data'),RECALL_DISABLE_AUTOSTART:'1',RECALL_PYTHON:'/does/not/exist',RECALL_EMBEDDING_SOCKET:path.join(dir,'unused.sock'),HF_HUB_OFFLINE:'1',TRANSFORMERS_OFFLINE:'1'};
 const runtime=path.join(bundle,'Contents/Resources/runtime');
 const check=spawnSync(path.join(runtime,'python/bin/python3'),['-I','-B','-c',`import os; from PIL import Image,ImageDraw,ImageFont; from src.visual import ocr_image; image=Image.new('RGB',(900,180),'white'); ImageDraw.Draw(image).text((20,40),'Recall remembers your notes',font=ImageFont.load_default(size=38),fill='black'); text=ocr_image(image); assert 'Recall' in text,repr(text); import torch,torchvision,tree_sitter_language_pack; print('Bundled OCR and model dependencies passed')`],{env:{...env,RECALL_TESSERACT:path.join(runtime,'ocr/bin/tesseract'),TESSDATA_PREFIX:path.join(runtime,'ocr/tessdata')},encoding:'utf8',timeout:60000});
 if(check.status!==0)throw Error(check.stderr || check.stdout);console.log(check.stdout.trim());
 const desktop=await electron.launch({executablePath:path.join(bundle,'Contents/MacOS/Recall'),args:[],cwd:dir,env,timeout:30000});
 try{
  const page=await desktop.firstWindow();const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const modal=page.locator('#recall-onboarding');await expect(modal).toBeVisible({timeout:30000});
  await modal.getByRole('button',{name:'Get started'}).click();
  await desktop.evaluate(({dialog},folder)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[folder]});},source);
  await modal.getByRole('button',{name:'Choose a folder'}).click();
  await modal.getByRole('button',{name:'Continue',exact:false}).click();
  await modal.getByRole('button',{name:'Start indexing'}).click();
  await expect(modal.getByRole('button',{name:'Try a first search'})).toBeVisible({timeout:120000});
  await modal.getByRole('button',{name:'Try a first search'}).click();
  await expect(page.locator('.file-row')).toHaveCount(1,{timeout:30000});
  await expect(page.locator('.document')).toContainText('linear algebra');
  await page.locator('#search-input').fill('linear algebra');await page.locator('#search-input').press('Enter');
  await expect(page.locator('#result-count')).toContainText('1',{timeout:60000});
  if(errors.length)throw Error(errors.join('\n'));
  await page.screenshot({path:'/tmp/recall-packaged-mac.png',scale:'css'});
  console.log('Packaged onboarding, indexing, preview and semantic search passed');
 }finally{await desktop.close();fs.rmSync(dir,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
