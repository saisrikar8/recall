import { connectAppearance } from './theme.js';

/** First-run setup shares the actual library, native pickers, jobs and preferences. */
export function createOnboarding({ api, icon, esc, appearanceControl, getState, startIndex, onClose, onOpen }) {
  const dialog=document.createElement('dialog');
  dialog.id='recall-onboarding';dialog.className='onboarding';
  dialog.setAttribute('aria-labelledby','onboarding-title');
  document.body.append(dialog);
  let step=1,paths=[],ownIndex=false,lastJob=null,error='',shortcut=null,login=false,closing=false,token=0;
  const normalize=path=>path.replaceAll('\\','/').replace(/\/$/,'');
  const name=path=>normalize(path).split('/').pop();
  const files=()=>getState().files.filter(file=>!file.error && (!paths.length || paths.some(path=>normalize(file.path)===normalize(path) || normalize(file.path).startsWith(normalize(path)+'/'))));
  const working=()=>ownIndex || getState().indexing;
  const status=()=>lastJob?.progress || getState().latestIndexProgress;

  async function finish(outcome='complete',query=null){
    if(closing)return;closing=true;
    try{
      await api.finishOnboarding(outcome);
      dialog.close();token++;onClose(query);
    }catch(reason){error=reason.message || String(reason);render();}
    finally{closing=false;}
  }
  function update(){
    if(!dialog.open || step!==4)return;
    const progress=status(),busy=working(),available=files();
    const ring=dialog.querySelector('.ob-progress-ring');
    if(!ring)return;
    const total=progress?.total || 0,completed=progress?.completed || 0;
    ring.style.setProperty('--progress',busy ? (total ? completed/total : 0) : 1);
    ring.classList.toggle('pending',busy && !total);
    ring.setAttribute('aria-valuetext',busy ? total ? `${completed} of ${total} files processed` : 'Preparing your library' : 'Indexing finished');
    dialog.querySelector('.ob-progress-title').textContent=busy?'Getting your library ready.':error?'Some files need another try.':'You’re ready to find it.';
    dialog.querySelector('.ob-progress-description').textContent=busy
      ? 'You can explore the library while Recall works. Files appear as they become searchable.'
      : available.length ? 'Start with a file you know. Next time, try describing what you remember.' : 'Add files whenever you’re ready. Recall will be here.';
    dialog.querySelector('.ob-stage').textContent=busy ? progress?.stage || 'Preparing search…' : error || `${available.length} file${available.length===1?'':'s'} in reach`;
    dialog.querySelector('.ob-progress-count').textContent=busy && total ? `${completed} / ${total} files processed` : '';
    const list=dialog.querySelector('.ob-ready-files');
    list.replaceChildren();
    for(const file of available.slice(0,3)){
      const row=document.createElement('div');row.className='ob-ready-file';
      row.innerHTML=icon('file')+'<span></span>'+icon('check');row.querySelector('span').textContent=file.name;list.append(row);
    }
    const tryButton=dialog.querySelector('[data-ob="try"]');
    tryButton.hidden=busy || available.length===0;
    dialog.querySelector('[data-ob="finish"]').textContent=busy?'Continue to library':available.length?'Open library':'Start exploring';
    dialog.querySelector('.ob-note').textContent=busy?'Indexing continues if you leave setup.':'Use ⌘ Shift Space whenever you need something.';
  }
  function render(){
    const count=paths.length;
    let body,footer;
    if(step===1){
      body=`<div class="ob-welcome"><div class="ob-copy"><span class="eyebrow">Welcome to Recall</span><h1 id="onboarding-title">Your files.<br>A thought away.</h1><p>Find your notes, code, and documents by what you remember about them.</p><div class="ob-value">${icon('search')} Describe it. Find it. Pick up where you left off.</div></div><div class="ob-illustration" aria-hidden="true"><div class="ob-orbit"></div><div class="ob-demo-search">${icon('search')} that idea from my notes…</div><div class="ob-demo-file">${icon('book')}<div><strong>A thought, rediscovered.</strong><span>Notes · Code · PDFs · Images</span></div>${icon('arrow')}</div><span class="ob-example">A glimpse of Recall</span></div></div>`;
      footer=`<span class="muted">A quick setup. Then it’s yours.</span><button class="btn primary" data-ob="next" autofocus>Get started ${icon('arrow')}</button>`;
    }else if(step===2){
      const existing=getState().files.length;
      body=`<div class="ob-centered"><span class="eyebrow">Your library</span><h1 id="onboarding-title">Choose a place to start.</h1><p>Add a small folder or a few files. You can add more later.</p><div class="ob-source-picker">${icon('folder')}<strong>Notes, code, PDFs, and images.</strong><div class="ob-picker-actions"><button class="btn primary" data-ob="folder" ${working()?'disabled':''}>Choose a folder</button><button class="btn" data-ob="files" ${working()?'disabled':''}>Choose files</button></div></div><div class="ob-source-list">${paths.map((path,i)=>`<div class="ob-source">${icon('folder')}<div><strong>${esc(name(path))}</strong><span title="${esc(path)}">${esc(path)}</span></div><button class="icon-btn" data-ob-remove="${i}" aria-label="Remove ${esc(name(path))}">${icon('close')}</button></div>`).join('')}</div><p class="ob-caption">${count ? 'Only these locations will be added. Your originals stay where they are.' : existing ? `Your current library already has ${existing} files. You can use those instead.` : 'Nothing is added until you start indexing.'}</p></div>`;
      footer=`<button class="btn ghost" data-ob="back">${icon('left')} Back</button><button class="btn ${count?'primary':''}" data-ob="next">${count?'Continue':existing?'Use my current library':'Add files later'} ${icon('arrow')}</button>`;
    }else if(step===3){
      body=`<div class="ob-centered"><span class="eyebrow">Make it yours</span><h1 id="onboarding-title">A shortcut to remembering.</h1><p>Recall stays in the menu bar when you close its windows.</p><div class="ob-shortcut"><span class="kbd">⌘</span><span class="kbd">⇧</span><span class="kbd">Space</span></div><p class="ob-caption">${shortcut ? 'Press these keys to open quick search from anywhere.' : 'The shortcut is in use. You can still open Quick Search from the Search menu.'}</p><div class="ob-preferences"><div class="ob-preference"><div><strong>Start at login</strong><span>Keep quick search ready when you need it.</span></div><input type="checkbox" role="switch" id="onboarding-login" aria-label="Start at login" ${login?'checked':''}></div><div class="ob-preference"><div><strong>Appearance</strong><span>Follow your system, or choose a theme.</span></div>${appearanceControl('onboarding-appearance-label')}</div></div></div>`;
      footer=`<button class="btn ghost" data-ob="back">${icon('left')} Back</button><button class="btn primary" data-ob="start">${paths.length?'Start indexing':'Open my library'} ${icon('arrow')}</button>`;
    }else{
      body=`<div class="ob-centered ob-ready"><div class="ob-progress-ring" role="status"><span>${icon('check')}</span></div><h1 id="onboarding-title" class="ob-progress-title">Getting your library ready.</h1><p class="ob-progress-description"></p><div class="ob-stage"></div><div class="ob-progress-count"></div><div class="ob-ready-files"></div><p class="ob-note ob-caption"></p></div>`;
      footer=`<button class="btn ghost" data-ob="finish">Continue to library</button><button class="btn primary" data-ob="try" hidden>Try a first search ${icon('arrow')}</button>`;
    }
    dialog.innerHTML=`<header class="ob-header"><div class="brand"><span class="brand-symbol" aria-hidden="true"></span><span class="brand-word">recall</span></div><button class="btn ghost ob-skip" data-ob="skip">Skip setup ${icon('close')}</button></header><section class="ob-body">${body}</section><div class="ob-error" role="status">${esc(error)}</div><footer class="ob-footer">${footer}</footer><div class="ob-steps" aria-label="${step<=3?'Step '+step+' of 3':'Your library'}">${[1,2,3].map(value=>`<span class="${value===step?'current':value<step?'complete':''}"></span>`).join('')}</div>`;
    connectAppearance(dialog);
    if(step===4)update();
    dialog.querySelector('.ob-footer .primary, .ob-footer button:last-child')?.focus();
  }
  async function open(){
    if(dialog.open){dialog.querySelector('.ob-footer button:last-child')?.focus();return;}
    step=1;paths=[];lastJob=null;error='';closing=false;token++;
    render();dialog.showModal();onOpen();
    try{const [preferences,available]=await Promise.all([api.preferences(),api.status()]);login=preferences.openAtLogin;shortcut=available.shortcut;if(step===3)render();}
    catch(reason){error=reason.message || String(reason);}
  }
  dialog.addEventListener('cancel',event=>{event.preventDefault();finish('skipped');});
  dialog.addEventListener('click',async event=>{
    const remove=event.target.closest('[data-ob-remove]');
    if(remove){paths.splice(Number(remove.dataset.obRemove),1);render();return;}
    const action=event.target.closest('[data-ob]')?.dataset.ob;if(!action)return;
    if(action==='skip')return finish('skipped');
    if(action==='finish')return finish();
    if(action==='try')return finish('complete',files()[0]?.name || null);
    if(action==='back'){step--;error='';render();return;}
    if(action==='next'){step++;error='';render();return;}
    if(action==='folder' || action==='files'){
      try{const chosen=await api.pick(action);paths=[...new Set([...paths,...chosen])];if(chosen.length)render();}
      catch(reason){error=reason.message || String(reason);render();}
      return;
    }
    if(action==='start'){
      step=4;error='';ownIndex=paths.length>0;render();
      if(!paths.length)return;
      const generation=token;
      try{
        const result=await startIndex(paths,{onProgress:job=>{lastJob=job;update();}});
        if(generation!==token)return;
        error=result?.error || (result?.results?.some(entry=>entry.result.failed) ? 'Some files could not be indexed. Check the library and try them again.' : '');
      }catch(reason){if(generation===token)error=reason.message || String(reason);}
      finally{ownIndex=false;if(generation===token)update();}
    }
  });
  dialog.addEventListener('change',async event=>{
    if(event.target.id!=='onboarding-login')return;
    const toggle=event.target;toggle.disabled=true;
    try{const result=await api.setLogin(toggle.checked);login=result.openAtLogin;}
    catch(reason){error=reason.message || String(reason);toggle.checked=login;dialog.querySelector('.ob-error').textContent=error;}
    finally{toggle.disabled=false;}
  });
  return {open,update,get isOpen(){return dialog.open;}};
}
