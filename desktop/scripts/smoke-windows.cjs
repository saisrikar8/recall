const { _electron: electron, expect } = require('@playwright/test');
const { spawnSync } = require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
(async()=>{
 if(process.platform!=='win32')throw Error('Run the packaged Windows smoke test on Windows.');
 const bundle=path.resolve(process.argv[2] || '../dist/windows/win-unpacked');
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'recall-windows-'));
 let source=path.join(dir,'Test notes');fs.mkdirSync(source);source=fs.realpathSync.native(source);fs.writeFileSync(path.join(source,'remember.md'),'# Memory\nNotes about linear algebra, matrices, and eigenvalues.');
 const runtime=path.join(bundle,'resources/runtime');
 const env={...process.env,PATH:`${process.env.SystemRoot}\\System32;${process.env.SystemRoot}`,RECALL_DB_PATH:path.join(dir,'index.db'),RECALL_DESKTOP_USER_DATA:path.join(dir,'user-data'),RECALL_DISABLE_AUTOSTART:'1',RECALL_PYTHON:'C:\\missing\\python.exe',RECALL_EMBEDDING_SOCKET:path.join(dir,'unused.sock')};
 delete env.Path;delete env.PYTHONPATH;delete env.PYTHONHOME;delete env.HF_HUB_OFFLINE;delete env.TRANSFORMERS_OFFLINE;
 console.log('Checking bundled OCR, PDF rendering and native dependencies…');
 const check=spawnSync(path.join(runtime,'python/python.exe'),['-I','-B','-c',`from PIL import Image,ImageDraw,ImageFont; from src.visual import ocr_image; image=Image.new('RGB',(900,180),'white'); ImageDraw.Draw(image).text((20,40),'Recall remembers your notes',font=ImageFont.load_default(size=38),fill='black'); text=ocr_image(image); assert 'Recall' in text,repr(text); import torch,torchvision,pymupdf,tree_sitter_language_pack; document=pymupdf.open(); page=document.new_page();page.insert_text((50,50),'Recall PDF preview');assert 'Recall' in page.get_text();assert page.get_pixmap().width>0; print('Bundled OCR, PDF rendering and model dependencies passed')`],{env:{...env,RECALL_TESSERACT:path.join(runtime,'ocr/tesseract.exe'),TESSDATA_PREFIX:path.join(runtime,'ocr/tessdata')},encoding:'utf8',timeout:120000,windowsHide:true});
 if(check.status!==0)throw Error(check.stderr || check.stdout || check.error);console.log(check.stdout.trim());
 console.log('Launching the installed application…');
 const desktop=await electron.launch({executablePath:path.join(bundle,'Recall.exe'),args:['--disable-gpu'],cwd:dir,env,timeout:60000});
 desktop.process().stderr.on('data',chunk=>process.stderr.write(chunk));
 try{
  const page=await desktop.firstWindow();const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const modal=page.locator('#recall-onboarding');await expect(modal).toBeVisible({timeout:60000});
  await modal.getByRole('button',{name:'Get started'}).click();
  await desktop.evaluate(({dialog},folder)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[folder]});},source);
  await modal.getByRole('button',{name:'Choose a folder'}).click();
  await modal.getByRole('button',{name:'Continue',exact:false}).click();
  console.log('Starting real indexing and first-time model preparation…');
  await modal.getByRole('button',{name:'Start indexing'}).click();
  // This downloads models on a clean runner and tests their actual CPU inference.
  const ready=modal.getByRole('button',{name:'Try a first search'});
  const deadline=Date.now()+600000;let lastReport=0;
  while(!await ready.isVisible()){
    const error=await modal.locator('.ob-error').textContent();
    if(error?.trim())throw Error('Indexing failed: '+error);
    const title=await modal.locator('.ob-progress-title').textContent();
    const stage=await modal.locator('.ob-stage').textContent();
    if(Date.now()-lastReport>15000){console.log('Index status:',title,stage);lastReport=Date.now();}
    if(title==='Some files need another try.')throw Error('Indexing failed: '+stage);
    if(title==='You’re ready to find it.'){
      console.error('Indexed library:',await page.evaluate(()=>window.recall.library()));
      throw Error('Indexing ended without a searchable file in the selected source: '+source);
    }
    if(Date.now()>deadline)throw Error('Indexing did not finish within ten minutes.');
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  console.log('Indexing finished. Checking search and preview…');
  await modal.getByRole('button',{name:'Try a first search'}).click();
  await expect(page.locator('.file-row')).toHaveCount(1,{timeout:60000});
  await expect(page.locator('.document')).toContainText('linear algebra');
  await page.locator('#search-input').fill('linear algebra');await page.locator('#search-input').press('Enter');
  await expect(page.locator('#result-count')).toContainText('1',{timeout:120000});
  if(errors.length)throw Error(errors.join('\n'));
  console.log('Installed Windows app: onboarding, indexing, preview and semantic search passed');
 }catch(error){
  const page=desktop.windows()[0];if(page){console.error(await page.locator('body').innerText().catch(()=>''));await page.screenshot({path:path.resolve(__dirname,'../../dist/windows/smoke-failure.png')}).catch(()=>{});}
  throw error;
 }finally{await desktop.close();fs.rmSync(dir,{recursive:true,force:true,maxRetries:10,retryDelay:100});}
})().catch(error=>{console.error(error);process.exitCode=1;});
