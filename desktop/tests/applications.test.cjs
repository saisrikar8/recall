const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const {createApplicationCatalog,matchScore,parseWindowsApps}=require('../applications.cjs');
test('app names prefer exact and prefix matches, with abbreviations and typos',()=>{
 assert.ok(matchScore('Chrome','chrome')>matchScore('Chrome Beta','chrome'));
 assert.ok(matchScore('Google Chrome','chrome')>0);
 assert.ok(matchScore('Visual Studio Code','vscode')>0);
 assert.ok(matchScore('Safari','sfaari')>0);
 assert.ok(matchScore('Calculator','open calculator')>0);
 assert.equal(matchScore('Calculator','linear algebra'),0);
 assert.equal(matchScore('Safari',''),0);
});
test('Mac inventory scans grouped apps but excludes nested helper bundles and deduplicates roots',async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'recall-apps-'));
 try{
  const make=async value=>{const app=path.join(dir,value);await fs.mkdir(path.join(app,'Contents'),{recursive:true});await fs.writeFile(path.join(app,'Contents/Info.plist'),'plist');return app;};
  const safari=await make('Safari.app');await make('Tools/Editor.app');await make('Safari.app/Contents/Helpers/Hidden.app');await make('.private/Hidden.app');
  let time=1,opened=[];
  const catalog=createApplicationCatalog({platform:'darwin',roots:[dir,dir],explicit:[],now:()=>time,ttl:100,openPath:async target=>{opened.push(target);return '';}});
  const rows=await catalog.search('safari');assert.equal(rows.length,1);assert.equal(rows[0].name,'Safari');
  assert.equal((await catalog.search('editor')).length,1);assert.equal((await catalog.search('hidden')).length,0);
  await assert.rejects(catalog.launch(safari),/Choose|available/);assert.equal(opened.length,0);
  await catalog.launch(rows[0].id);assert.deepEqual(opened,[await fs.realpath(safari)]);
  await make('Fresh.app');assert.equal((await catalog.search('fresh')).length,0);time=102;
  assert.equal((await catalog.search('fresh')).length,1);
  await fs.rm(safari,{recursive:true});time=205;await assert.rejects(catalog.launch(rows[0].id),/available/);
 }finally{await fs.rm(dir,{recursive:true,force:true});}
});
test('Windows Start menu catalog supports classic and Store identifiers with allowlisted launching',async()=>{
 const rows=parseWindowsApps(JSON.stringify([{Name:'Calculator',AppID:'Microsoft.WindowsCalculator_abc!App'},{Name:'Visual Studio Code',AppID:'Microsoft.VisualStudioCode'},{Name:'Uninstall Example',AppID:'uninstall'},{Name:'Bad',AppID:'bad\nargument'}]));
 assert.equal(rows.length,2);assert.equal(parseWindowsApps('{"Name":"Paint","AppID":"Paint"}').length,1);
 let loads=0,opened=[];
 const catalog=createApplicationCatalog({platform:'win32',loadWindows:async()=>{loads++;return rows;},openWindows:async id=>{opened.push(id);}});
 const matches=await catalog.search('calculator');assert.equal(matches.length,1);await catalog.search('vscode');assert.equal(loads,1);
 await catalog.launch(matches[0].id);assert.deepEqual(opened,['Microsoft.WindowsCalculator_abc!App']);
 await assert.rejects(catalog.launch('arbitrary.exe'),/available/);
});
test('failed discovery retries and icon failures do not prevent name search',async()=>{
 let calls=0;
 const catalog=createApplicationCatalog({platform:'win32',loadWindows:async()=>{if(++calls===1)throw Error('Unavailable');return [{name:'Editor',target:'Editor',type:'windows',iconPath:'icon'}];},getIcon:async()=>{throw Error('No icon');},openWindows:async()=>{}});
 await assert.rejects(catalog.search('editor'),/Unavailable/);
 const rows=await catalog.search('editor');assert.equal(rows[0].icon,null);assert.equal(rows[0].name,'Editor');
});
