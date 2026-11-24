// Installed application lookup is independent of Python, embeddings, and the file index.
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { createHash } = require('node:crypto');
const { execFile, spawn } = require('node:child_process');
const { promisify } = require('node:util');
const execute = promisify(execFile);
const normalize = value => value.normalize('NFKD').replace(/\p{M}/gu,'').toLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
const identity = value => createHash('sha256').update(value).digest('hex').slice(0,24);

function editDistance(a,b) {
  const table=Array.from({length:a.length+1},(_,i)=>[i]);
  for(let j=0;j<=b.length;j++)table[0][j]=j;
  for(let i=1;i<=a.length;i++)for(let j=1;j<=b.length;j++){
    table[i][j]=Math.min(table[i-1][j]+1,table[i][j-1]+1,table[i-1][j-1]+(a[i-1]===b[j-1]?0:1));
    if(i>1&&j>1&&a[i-1]===b[j-2]&&a[i-2]===b[j-1])table[i][j]=Math.min(table[i][j],table[i-2][j-2]+1);
  }
  return table[a.length][b.length];
}
function matchScore(name,raw) {
  const q=normalize(raw.trim().replace(/^(?:open|launch|start)\s+/i,'')),value=normalize(name);
  if(!q||q.length>80)return 0;
  if(value===q)return 1000;
  if(value.startsWith(q))return 900-Math.min(value.length-q.length,100);
  const words=name.split(/[^\p{L}\p{N}]+/u).map(normalize).filter(Boolean);
  if(words.some(word=>word.startsWith(q)))return 800;
  if(value.includes(q))return 700;
  if(q.length>=2){
    let position=0,last=-1,gaps=0;
    for(const char of q){const next=value.indexOf(char,position);if(next<0){position=-1;break;}if(last>=0)gaps+=next-last-1;last=next;position=next+1;}
    if(position>=0&&gaps<=Math.max(6,q.length*2))return 500-gaps;
  }
  if(q.length>=4&&[value,...words].some(word=>Math.abs(word.length-q.length)<=1&&editDistance(word,q)<=1))return 400;
  return 0;
}

async function macApplications(roots,explicit=[]) {
  const found=new Map();
  async function add(candidate) {
    try {
      if(!(await fs.stat(path.join(candidate,'Contents/Info.plist'))).isFile())return;
      const real=await fs.realpath(candidate);
      if(!found.has(real))found.set(real,{name:path.basename(candidate,'.app'),target:real,iconPath:real,type:'mac'});
    }catch{}
  }
  async function walk(root,depth=0){
    let entries;try{entries=await fs.readdir(root,{withFileTypes:true});}catch{return;}
    for(const entry of entries){
      if(entry.name.startsWith('.'))continue;
      const candidate=path.join(root,entry.name);
      if(entry.name.endsWith('.app'))await add(candidate); // Never descend into an app's helpers.
      else if(entry.isDirectory()&&depth<2)await walk(candidate,depth+1);
    }
  }
  await Promise.all(roots.map(root=>walk(root)));
  await Promise.all(explicit.map(add));
  return [...found.values()];
}
function parseWindowsApps(output) {
  const data=JSON.parse(output.replace(/^\uFEFF/,'').trim() || '[]');
  const rows=Array.isArray(data)?data:data?[data]:[];
  return rows.filter(row=>typeof row.Name==='string'&&typeof row.AppID==='string'&&row.Name.trim()&&row.AppID.trim()
    &&row.AppID.length<1024&&!/[\x00-\x1f]/.test(row.AppID)&&!/^uninstall\b/i.test(row.Name))
    .map(row=>({name:row.Name.trim(),target:row.AppID,type:'windows'}));
}
async function windowsApplications() {
  const executable=path.win32.join(process.env.SystemRoot || 'C:\\Windows','System32/WindowsPowerShell/v1.0/powershell.exe');
  const script="[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); @(Get-StartApps | Select-Object Name, AppID) | ConvertTo-Json -Compress";
  const {stdout}=await execute(executable,['-NoProfile','-NonInteractive','-Command',script],{windowsHide:true,timeout:15000,maxBuffer:2*1024*1024});
  return parseWindowsApps(stdout);
}
function launchWindows(id) {
  return new Promise((resolve,reject)=>{
    const executable=path.win32.join(process.env.SystemRoot || 'C:\\Windows','explorer.exe');
    const child=spawn(executable,['shell:AppsFolder\\'+id],{detached:true,stdio:'ignore',windowsHide:true});
    child.once('error',reject);child.once('spawn',()=>{child.unref();resolve();});
  });
}
function createApplicationCatalog({platform=process.platform,roots,explicit,getIcon=async()=>null,openPath,
  loadWindows=windowsApplications,openWindows=launchWindows,now=Date.now,ttl=120000}={}) {
  const locations=roots || ['/Applications','/System/Applications',path.join(os.homedir(),'Applications'),'/System/Library/CoreServices/Applications'];
  const direct=explicit || ['/System/Library/CoreServices/Finder.app'];
  let entries=new Map(),expires=0,refreshing=null;
  const icons=new Map();
  async function refresh(){
    if(now()<expires)return;
    if(refreshing)return refreshing;
    refreshing=(async()=>{
      const apps=platform==='darwin'?await macApplications(locations,direct):platform==='win32'?await loadWindows():[];
      const next=new Map();
      for(const app of apps){const id=identity(platform+':'+app.target);next.set(id,{...app,id});}
      entries=next;expires=now()+ttl;icons.clear();
    })();
    try{await refreshing;}finally{refreshing=null;}
  }
  async function search(query,limit=6){
    if(typeof query!=='string'||query.length>200)throw Error('Enter an application name.');
    if(!query.trim())return [];
    await refresh();
    const matches=[...entries.values()].map(app=>({...app,score:matchScore(app.name,query)})).filter(app=>app.score>0)
      .sort((a,b)=>b.score-a.score||a.name.localeCompare(b.name)).slice(0,Math.max(1,Math.min(Number(limit)||6,10)));
    return Promise.all(matches.map(async app=>{
      let icon=null;
      if(app.iconPath){
        if(!icons.has(app.id))icons.set(app.id,Promise.resolve().then(()=>getIcon(app.iconPath)).catch(()=>null));
        icon=await icons.get(app.id);
      }
      return {id:app.id,name:app.name,path:'application:'+app.id,kind:'application',icon:typeof icon==='string'&&icon.startsWith('data:image/png;base64,')?icon:null};
    }));
  }
  async function launch(id){
    if(typeof id!=='string')throw Error('Choose an installed application.');
    await refresh();const app=entries.get(id);
    if(!app)throw Error('Application is no longer available. Search for it again.');
    if(app.type==='windows')await openWindows(app.target);
    else{const error=await openPath(app.target);if(error)throw Error(error);}
  }
  return {search,launch,refresh};
}
module.exports={createApplicationCatalog,matchScore,macApplications,parseWindowsApps};
