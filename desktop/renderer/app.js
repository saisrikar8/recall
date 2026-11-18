import { createOnboarding } from './onboarding.js';
import { connectAppearance, setAppearance } from './theme.js';
/* Shared desktop surfaces: library, quick search, and full-window preview. */
const api = window.recall;
const mode = new URLSearchParams(location.search).get('mode') || 'dashboard';
const app = document.querySelector('#app');
const icons = {
  trash: '<path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>',
  monitor: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M12 17v4m-4 0h8"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  moon: '<path d="M20.5 13A8.5 8.5 0 0 1 11 3.5 8.5 8.5 0 1 0 20.5 13Z"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3Z"/>',
  file: '<path d="M6 3h8l4 4v14H6Z"/><path d="M14 3v5h4M9 12h6M9 16h6"/>',
  code: '<path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-12-2 18"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  left: '<path d="m14 5-7 7 7 7"/>',
  up: '<path d="m6 14 6-6 6 6"/>',
  expand: '<path d="M14 3h7v7m0-7-8 8M10 21H3v-7m0 7 8-8"/>',
  external: '<path d="M14 3h7v7m0-7L10 14M10 3H3v18h18v-7"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  spark: '<path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4Z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  layers: '<path d="m12 3 10 5-10 5L2 8Zm-10 9 10 5 10-5M2 17l10 5 10-5"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  settings: '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="currentColor"/><circle cx="15" cy="17" r="3" fill="currentColor"/>',
  book: '<path d="M12 5C9 3 5 3 2 4v15c4-1 7-1 10 1 3-2 6-2 10-1V4c-4-1-7-1-10 1v15"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">${icons[name] || icons.file}</svg>`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = { files: [], collections: [], results: null, selected: null, query: '', filter: 'all', view: 'home', collection: null, busy: false, indexing: false, revealIndexProgress: false, previewVersion: 0, searchVersion: 0, completedQuery: '', shortcut: null };
const imageTypes = new Set(['.png','.jpg','.jpeg','.webp','.tif','.tiff','.bmp','.gif']);
const codeTypes = new Set(['.py','.js','.jsx','.mjs','.cjs','.ts','.tsx','.mts','.cts','.java','.go','.rs','.c','.h','.cpp','.cc','.cxx','.hpp','.cs','.rb','.php','.kt','.kts','.swift','.sh','.bash','.lua']);
function kind(file) { const ext = file.extension || (file.path?.match(/\.[^./]+$/)?.[0] || '').toLowerCase(); return ext === '.pdf' ? 'pdf' : imageTypes.has(ext) ? 'image' : codeTypes.has(ext) ? 'code' : ['.md','.markdown'].includes(ext) ? 'markdown' : 'text'; }
const fileIcon = file => `<span class="file-icon ${kind(file)}">${icon(kind(file) === 'code' ? 'code' : kind(file) === 'image' ? 'image' : 'file')}</span>`;
const basename = path => path.split(/[\\/]/).pop();
function toast(message) { const node = document.querySelector('#toast'); node.textContent = message; node.classList.add('visible'); clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.remove('visible'), 5000); }
function errorMessage(error) { return String(error?.message || error).replace(/^Error invoking remote method '[^']+': Error: /, ''); }
const empty = (title, message, glyph='search') => `<div class="empty"><div class="empty-icon">${icon(glyph)}</div><h3>${esc(title)}</h3><p>${esc(message)}</p></div>`;
function niceDate(value) { if (!value) return 'Not indexed'; const date = new Date(value), age = Date.now() - date; if (age < 60000) return 'Just indexed'; if (age < 3600000) return `${Math.floor(age/60000)}m ago`; if (age < 86400000) return `${Math.floor(age/3600000)}h ago`; return date.toLocaleDateString(undefined,{month:'short',day:'numeric'}); }
function highlight(value, terms = []) {
  if (!terms.length) return esc(value);
  const pattern = terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  if (!pattern) return esc(value);
  return String(value).split(new RegExp(`(${pattern})`, 'gi')).map((part, i) => i % 2 ? `<mark>${esc(part)}</mark>` : esc(part)).join('');
}
function termsFor(query) { return query.match(/[\w-]{3,}/g)?.filter(w => !['the','what','where','which','show','find','with','that','this','does','how','and','for','from'].includes(w.toLowerCase())).slice(0,24) || []; }
let onboarding, firstRunChecked=false;
function appearanceControl(labelId="appearance-label") {
  return `<div class="appearance-control"><span id="${labelId}">Appearance</span><div class="appearance-switch" role="group" aria-labelledby="${labelId}"><span class="appearance-thumb" aria-hidden="true"></span>${[['system','monitor','System'],['light','sun','Light'],['dark','moon','Dark']].map(([value,glyph,label])=>`<button type="button" data-appearance="${value}" aria-label="${label} appearance" aria-pressed="false" title="${label}">${icon(glyph)}</button>`).join('')}</div></div>`;
}
function notifyNavigation() {
  if(mode==='dashboard')api.navigation({collection:state.collection,busy:state.busy || state.indexing,indexing:state.indexing,onboarding:Boolean(onboarding?.isOpen)}).catch(()=>{});
}
function shell() {
  if(mode==='settings'){
    app.innerHTML=`<main class="settings-window"><header class="titlebar">Recall / Settings</header><section class="settings-content"><h1>Settings</h1><div class="settings-row"><div><h2>Appearance</h2><p>Follow your system, or choose a theme.</p></div>${appearanceControl()}</div><div class="settings-row"><label for="startup-toggle"><h2>Start at login</h2><p>Keep quick search ready in the menu bar.</p></label><input type="checkbox" role="switch" id="startup-toggle"></div><div class="settings-row"><div><h2>Quick search</h2><p>Open Recall from anywhere.</p></div><span class="kbd">⌘ ⇧ Space</span></div><p class="settings-error" id="settings-error" role="status"></p></section></main>`;
    const refresh=async()=>{try{const prefs=await api.preferences();document.querySelector('#startup-toggle').checked=prefs.openAtLogin;document.querySelector('#settings-error').textContent=prefs.loginError || '';}catch(error){document.querySelector('#settings-error').textContent=errorMessage(error);}};
    document.querySelector('#startup-toggle').addEventListener('change',async event=>{
      const toggle=event.target;toggle.disabled=true;
      try{await api.setLogin(toggle.checked);}catch(error){document.querySelector('#settings-error').textContent=errorMessage(error);}
      finally{await refresh();toggle.disabled=false;}
    });
    api.onPreferencesChanged(refresh);refresh();return;
  }

  if (mode === 'preview') {
    app.innerHTML = `<main class="preview-window"><header class="titlebar">Recall <span>/</span> File preview <div class="right"><button class="btn ghost" data-action="dashboard">${icon('grid')} Open library</button></div></header><section id="preview" class="preview">${empty('Opening your file…','Getting the original ready.','file')}</section></main>`;
    api.onSelection(selection => { state.query = selection.query || ''; state.selected = selection; showPreview(selection); });
    return;
  }
  if (mode === 'launcher') {
    document.body.classList.add('launcher-mode');
    app.innerHTML = `<main class="launcher"><form class="launcher-top" id="search-form"><span class="brand-symbol" aria-hidden="true"></span><label class="sr-only" for="search-input">Search your files</label><input id="search-input" placeholder="What are you looking for?" autocomplete="off" autofocus><button type="button" class="icon-btn" data-action="hide" aria-label="Close quick search"><span class="kbd">esc</span></button></form><section class="launcher-content"><div class="launcher-results"><div class="list-header" id="list-heading">YOUR LIBRARY, A THOUGHT AWAY</div><div id="rows"></div></div><section id="preview" class="preview"></section></section><footer class="launcher-foot"><span><span class="kbd">↑</span> <span class="kbd">↓</span> to navigate</span><span><span class="kbd">↵</span> open preview</span><button data-action="dashboard">Open library ${icon('arrow')}</button></footer></main>`;
    api.onFocus(() => document.querySelector('#search-input').focus());
    document.querySelector('#search-input').addEventListener('input', event => { state.query = event.target.value; clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 350); });
  } else {
    app.innerHTML = `<div class="shell"><aside class="sidebar"><div class="brand"><span class="brand-symbol" aria-hidden="true"></span><span class="brand-word">recall</span></div><nav class="nav" aria-label="Main navigation"><button class="nav-item active" data-view="home">${icon('grid')}<span>Overview</span></button><button class="nav-item" data-view="all">${icon('folder')}<span>All files</span><span class="count" id="file-count">0</span></button><button class="nav-item" data-action="focus-search">${icon('search')}<span>Search</span></button></nav><div class="side-label eyebrow">Collections</div><div id="collections" class="side-collections"></div><button class="nav-item" data-action="add-folder">${icon('plus')}<span>Add a folder</span></button><div class="sidebar-bottom">${appearanceControl()}</div></aside><main class="main"><header class="titlebar">Workspace ${icon('chevron')} <span id="breadcrumb">Overview</span><div class="right"><button class="icon-btn" data-action="launcher" aria-label="Open quick search">${icon('search')}</button></div></header><div class="content"><div class="page-head"><div><h1 id="page-title">Your things, found.</h1><p id="page-description">Notes, documents, and code.</p></div><div class="head-actions"><button class="btn" data-action="add-folder">${icon('folder')} Add folder</button><button class="btn primary" data-action="add-files">${icon('plus')} Add files</button></div></div><div id="regular-content"><form class="hero-search" id="search-form">${icon('search')}<label class="sr-only" for="search-input">Search your library</label><input id="search-input" placeholder="A thought, a phrase, that thing you remember…" autocomplete="off"><span class="kbd">↵</span></form><div class="search-note"><span style="margin-left:auto" id="shortcut-hint"></span></div><div id="error"></div><div id="indexing"></div><div id="stats" class="stats"></div><div class="section-head"><h2 id="section-title">Recently added</h2><span class="badge" id="result-count">0 files</span><button class="btn ghost right" data-view="all">View all files ${icon('arrow')}</button></div><div class="filter-bar" id="filters"><button class="filter active" data-filter="all">Everything</button><button class="filter" data-filter="pdf">PDFs</button><button class="filter" data-filter="code">Code</button><button class="filter" data-filter="markdown">Notes</button><button class="filter" data-filter="image">Images</button></div><section class="workspace"><div class="file-list"><div class="list-header" id="list-heading">FILE <span style="margin-left:auto">ADDED TO RECALL</span></div><div class="rows" id="rows"></div></div><section class="preview" id="preview"></section></section></div></div></main></div>`;
  }
  document.querySelector('#search-form').addEventListener('submit', event => { event.preventDefault(); clearTimeout(searchTimer); state.query = document.querySelector('#search-input').value; runSearch(); });
  refreshLibrary();
}
let searchTimer;
async function refreshLibrary() {
  try {
    if (!api) throw new Error('Open this interface through the Recall Electron app to connect your library.');
    const library = await api.library(); Object.assign(state, library);
    if (state.collection && !state.collections.some(item=>item.path===state.collection)) { state.collection=null; state.view='home'; state.results=null; state.selected=null; if(mode==='dashboard')setView('home'); }
    if (mode !== 'launcher') {
      document.querySelector('#file-count').textContent = state.files.length;
      document.querySelector('#collections').innerHTML = state.collections.map((c,i) => `<div class="collection-item"><button class="nav-item" data-collection="${i}">${icon('folder')}<span class="collection-name">${esc(c.name)}</span><span class="count">${c.count}</span></button><button class="icon-btn collection-remove" data-remove-collection="${i}" aria-label="Remove collection ${esc(c.name)}" title="Remove from Recall">${icon('trash')}</button></div>`).join('') || '<p class="muted" style="font-size:11px;padding:0 12px 10px">A place for everything.</p>';
      syncNavigation();
      renderStats();
      const status = await api.status(); state.shortcut = status.shortcut;
      document.querySelector('#shortcut-hint').textContent = status.shortcut ? `${status.shortcut} from anywhere` : 'Shortcut unavailable · use the menu to search';
    }
    renderRows();
    onboarding?.update();
    if(mode==='dashboard' && !firstRunChecked){
      firstRunChecked=true;
      const preferences=await api.preferences();
      if(!preferences.onboardingCompleted){
        if(state.collections.length)await api.finishOnboarding('existing-library');
        else await onboarding.open();
      }
    }
  } catch (error) {
    if (mode === 'launcher') document.querySelector('#rows').innerHTML = empty('Let’s reconnect.',errorMessage(error));
    else document.querySelector('#error').innerHTML = `<div class="error-box" role="alert">${esc(errorMessage(error))}</div>`;
    renderPreviewEmpty();
  }
}
function renderStats() {
  const docs = state.files.filter(file => ['pdf','text','markdown'].includes(kind(file))).length;
  document.querySelector('#stats').innerHTML = [
    [icon('file'),'In your library',state.files.length,'files in one place'],
    [icon('folder'),'Connected collections',state.collections.length,'folders in one place'],
    [icon('book'),'Documents & notes',docs,'ideas worth keeping']
  ].map(([glyph,label,value,note]) => `<div class="stat"><div class="stat-top">${glyph}${label}</div><div class="stat-bottom"><span class="stat-number">${value.toLocaleString()}</span><small>${note}</small></div></div>`).join('');
}
function currentRows() {
  return (state.results ?? state.files).filter(file => (state.filter === 'all' || kind(file) === state.filter) && (!state.collection || (file.collection === state.collection)));
}
function renderRows() {
  let rows = currentRows();
  if (mode === 'launcher') rows = rows.slice(0, 12);
  else if (state.view === 'home' && !state.results) rows = rows.slice(0, 12);
  state.visibleRows = rows;
  if (mode !== 'launcher') {
    document.querySelector('#section-title').textContent = state.results ? 'Found in your library' : state.view === 'home' ? 'Recently added' : 'Your library';
    document.querySelector('#result-count').textContent = `${rows.length} ${state.results ? 'results' : 'files'}`;
  }
  document.querySelector('#list-heading').innerHTML = state.results ? `SEARCH RESULTS <span style="margin-left:auto">${rows.length} matches</span>` : mode === 'launcher' ? 'PICK UP WHERE YOU LEFT OFF' : 'FILE <span style="margin-left:auto">ADDED TO RECALL</span>';
  if (!rows.length) {
    document.querySelector('#rows').innerHTML = empty(state.results ? 'Nothing quite yet.' : 'Make room for remembering.', state.results ? 'Try a different description, or check that the file has been added to your library.' : 'Add a few files or a folder. Your notes, code, and documents will be right here.', state.results ? 'search' : 'folder') + (!state.results ? '<div style="text-align:center;margin-bottom:28px"><button class="btn primary" data-action="add-files">Add your first files</button></div>' : '');
    state.selected = null; renderPreviewEmpty(); return;
  }
  const selectedIndex = rows.findIndex(row => row.path === state.selected?.path && row.page === state.selected?.page);
  state.selectedIndex = selectedIndex < 0 ? 0 : selectedIndex;
  state.selected = rows[state.selectedIndex];
  const terms = termsFor(state.query);
  document.querySelector('#rows').innerHTML = rows.map((file,i) => `<button class="file-row ${i === state.selectedIndex ? 'selected' : ''}" data-row="${i}" aria-pressed="${i === state.selectedIndex}" title="${esc(file.path)}">${fileIcon(file)}<div class="row-copy"><div class="row-title">${highlight(file.name && !state.results ? file.name : basename(file.path),terms)}</div>${file.relative_path && file.relative_path !== basename(file.path) ? `<div class="row-path">${esc(file.relative_path.slice(0, -basename(file.path).length).replace(/\/$/, ''))}</div>` : ''}${file.source ? `<div class="row-excerpt">${highlight(file.source.slice(0,260),terms)}</div>` : ''}<div class="row-tags"><span>${file.page ? `Page ${file.page}` : file['start-line'] ? `Line ${file.match_line || file['start-line']}` : niceDate(file.indexed_at)}</span>${file.error ? '<span class="badge">Needs reindexing</span>' : ''}</div></div>${icon('chevron')}</button>`).join('');
  if(state.previewData?.path!==state.selected.path || state.previewQuery!==state.query || state.previewIndexedAt!==state.selected.indexed_at)showPreview(state.selected);
}
function renderPreviewEmpty() {
  const node = document.querySelector('#preview');
  if (node) node.innerHTML = empty('A closer look.','Choose a file to see a preview, right where you are.','file');
}
function previewRequest(file, page) { return {path:file.path, query:state.query, page:page || file.page || 1, line:file.match_line || file['start-line'] || file.line}; }
async function showPreview(file, page) {
  const version = ++state.previewVersion;
  const node = document.querySelector('#preview');
  node.setAttribute('aria-busy','true');
  node.innerHTML = `<header class="preview-header">${icon('file')}<strong>${esc(basename(file.path))}</strong><span class="right"><button class="icon-btn" data-action="open-preview" aria-label="Open preview in a new window" title="Open in a new window">${icon('expand')}</button></span></header><div class="preview-body">${empty('A closer look…','Loading the original file.','file')}</div>`;
  try {
    const data = await api.preview(previewRequest(file,page));
    if (version !== state.previewVersion) return;
    state.previewData = data;
    state.previewQuery=state.query;state.previewIndexedAt=file.indexed_at;
    const semantic = ['semantic','visual','hybrid'].includes(file.match_type);
    let body;
    if (data.kind === 'pdf') {
      body = `<div class="page-controls"><button class="icon-btn" data-page="${data.page-1}" ${data.page === 1 ? 'disabled' : ''} aria-label="Previous page">${icon('left')}</button><span>Page ${data.page} of ${data.pages}</span><button class="icon-btn" data-page="${data.page+1}" ${data.page === data.pages ? 'disabled' : ''} aria-label="Next page">${icon('chevron')}</button></div><div class="pdf-page"><img src="${data.image}" alt="Page ${data.page} of ${esc(data.name)}">${data.highlights.map(rect => `<span class="pdf-highlight" style="left:${rect.x*100}%;top:${rect.y*100}%;width:${rect.width*100}%;height:${rect.height*100}%"></span>`).join('')}</div>`;
    } else if (data.kind === 'image') {
      body = `<img class="image-preview" src="${data.image}" alt="${esc(data.name)}">`;
    } else if (data.kind === 'markdown') {
      body = `<article class="document">${markdown(data.text,data.terms)}</article>`;
    } else {
      body = `<div class="code-view">${data.text.split('\n').map((line,i) => {const n = data.first_line+i; return `<div class="code-line ${n === data.match_line ? 'matched' : ''}" ${n === data.match_line ? 'id="match-line"' : ''}><span class="line-number">${n}</span><code>${syntax(line,data.terms)}</code></div>`;}).join('')}</div>`;
    }
    node.innerHTML = `<header class="preview-header">${icon(data.kind === 'code' ? 'code' : 'file')}<strong>${esc(data.name)}</strong><div class="right">${mode !== 'preview' ? `<button class="icon-btn" data-action="open-preview" title="Open in a new window" aria-label="Open preview in a new window">${icon('expand')}</button>` : ''}<button class="icon-btn" data-action="open-original" title="Open original file" aria-label="Open original file">${icon('external')}</button></div></header><div class="preview-body">${body}</div>${semantic || data.truncated ? `<footer class="preview-footer"><span>${data.truncated ? 'Showing an excerpt around this match' : file.match_type === 'visual' ? 'Visual match' : 'Related passage'}</span></footer>` : ''}`;
    node.setAttribute('aria-busy','false');
    if (data.match_line) node.querySelector('#match-line')?.scrollIntoView({block:'center'});
  } catch(error) { if(version === state.previewVersion) { node.innerHTML = empty('Preview unavailable.',errorMessage(error),'file'); node.setAttribute('aria-busy','false'); } }
}
function syntax(line, terms) {
  const regex = /(#[^\n]*|\/\/[^\n]*|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\b(?:def|class|return|import|from|const|let|function|async|await|if|else|for|while|try|except|export|interface|public|private|var|new|true|false|None|null)\b)/g;
  return line.split(regex).map((part,i) => { if (!(i%2)) return highlight(part,terms); const type = /^(#|\/\/)/.test(part) ? 'comment' : /^["']/.test(part) ? 'string' : 'keyword'; return `<span class="syntax-${type}">${highlight(part,terms)}</span>`; }).join('');
}
function markdown(text, terms) {
  let inCode = false, list = false;
  const output=[];
  const inline = value => highlight(value,terms).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  for (const line of text.split('\n')) {
    if (/^```/.test(line)) { if(list) {output.push('</ul>');list=false;} output.push(inCode ? '</code></pre>' : '<pre><code>'); inCode=!inCode; continue; }
    if(inCode) {output.push(highlight(line,terms)+'\n');continue;}
    const item = line.match(/^\s*[-*] (.*)/);
    if(item) {if(!list){output.push('<ul>');list=true;} output.push(`<li>${inline(item[1])}</li>`);continue;}
    if(list){output.push('</ul>');list=false;}
    const heading=line.match(/^(#{1,3}) (.*)/);
    if(heading) output.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`);
    else if(/^> /.test(line)) output.push(`<blockquote>${inline(line.slice(2))}</blockquote>`);
    else if(/^---+$/.test(line)) output.push('<hr>');
    else if(line.trim()) output.push(`<p>${inline(line)}</p>`);
  }
  if(list)output.push('</ul>');if(inCode)output.push('</code></pre>');
  return output.join('');
}
async function pollJob(id, onProgress) {
  while(true) {
    const job = await api.job(id);
    if(onProgress)onProgress(job);
    if(job.status === 'complete')return job.result;
    if(job.status === 'failed')throw new Error(job.error || 'The operation failed.');
    await new Promise(resolve => setTimeout(resolve,400));
  }
}
let searchAgain = false;
async function runSearch() {
  const query = document.querySelector('#search-input').value.trim(); state.query = query;
  if (state.busy) {searchAgain=true;return;}
  if(state.indexing) {toast('Indexing is in progress. Search will be ready when it finishes.');return;}
  if(!query){state.completedQuery='';state.results=null;renderRows();return;}
  state.busy=true;notifyNavigation();
  const version=++state.searchVersion;
  document.querySelector('#list-heading').textContent = 'SEARCHING YOUR LIBRARY…';
  try {
    const {id} = await api.search({query,limit:30,threshold:.3,collection:state.collection});
    const result = await pollJob(id);
    if(version === state.searchVersion && query === document.querySelector('#search-input').value.trim()) {state.completedQuery=query;state.results=result;renderRows();}
  }catch(error){toast(errorMessage(error));document.querySelector('#list-heading').textContent='SEARCH COULD NOT FINISH';}
  finally {state.busy=false;notifyNavigation();if(searchAgain){searchAgain=false;runSearch();}}
}
export function renderIndexProgress(job, current, total, path) {
  if(mode === 'launcher')return;
  const last = job.messages.at(-1) || 'Preparing your files…';
  const matches = [...job.messages].reverse().map(line => line.match(/\[(\d+)\/(\d+)\]/)).find(Boolean);
  const count = matches ? `${matches[1]} / ${matches[2]} checked` : 'Working locally';
  // File-check counts precede OCR and embedding: never label them overall percent.
  const panel = document.querySelector('#indexing');
  // Keep the animated element mounted: replacing it on every poll restarts it.
  if (!panel.querySelector('.index-card')) {
    panel.innerHTML = `<section class="index-card" role="status" aria-live="polite"><div class="index-head">${icon('layers')}<strong class="index-name"></strong><span class="index-count"></span></div><div class="progress-track"><div class="progress-fill indeterminate"></div></div><div class="index-message"></div><details class="folder-progress"><summary>Folder progress</summary><div class="folder-progress-rows"></div></details></section>`;
  }
  panel.querySelector('.index-name').textContent = `Indexing ${basename(path)}`;
  panel.querySelector('.index-count').textContent = `${current} of ${total} sources · ${count}`;
  const textStage = last.match(/^Text embeddings (.+): \d+ passages$/);
  let message = last.replace(/^\[\d+\/\d+\] /, '');
  if (textStage) message = `Preparing search for ${basename(textStage[1])}`;
  else if (/^Embedding scene batch/.test(last)) message = 'Processing images';
  else if (/^Embedding PDF page batch/.test(last)) message = 'Processing PDF pages';
  else if (/^OCR/.test(last)) message = 'Reading text from documents';
  const progress=job.progress;
  if(progress){
    panel.querySelector('.index-count').textContent=`${progress.completed} / ${progress.total} files complete`;
    panel.querySelector('.index-message').textContent=`${progress.stage}${progress.file ? ' · '+basename(progress.file) : ''}`;
    const fill=panel.querySelector('.progress-fill');
    fill.classList.remove('indeterminate');
    fill.style.width=`${progress.total ? progress.completed/progress.total*100 : 100}%`;
    const container=panel.querySelector('.folder-progress-rows');
    const rows=progress.folders.filter(row=>row.path!=='.');
    const previous=new Map([...container.children].map(node=>[node.dataset.folder,node]));
    const wanted=new Set(rows.map(row=>row.path));
    for(const [folder,node] of previous)if(!wanted.has(folder))node.remove();
    for(const row of rows){
      let node=previous.get(row.path);
      if(!node){node=document.createElement('div');node.className='folder-progress-row';node.dataset.folder=row.path;node.innerHTML='<span></span><progress></progress><small></small>';container.append(node);}
      node.querySelector('span').textContent=row.path;
      node.querySelector('progress').max=row.total || 1;node.querySelector('progress').value=row.completed;
      node.querySelector('small').textContent=`${row.completed}/${row.total}${row.failed ? ' · '+row.failed+' failed' : ''}`;
    }
    panel.querySelector('.folder-progress').hidden=rows.length===0;
  }else panel.querySelector('.index-message').textContent = message;
  if(state.revealIndexProgress){
    state.revealIndexProgress=false;panel.scrollIntoView({block:'center',behavior:'smooth'});
    const folders=panel.querySelector('details');if(folders)folders.open=true;
  }

}
async function addSources(type) {
  if(state.indexing || state.busy){toast('Let the current operation finish first.');return;}
  try{const paths=await api.pick(type);if(paths.length)await indexSources(paths);}
  catch(error){toast(errorMessage(error));}
}
async function indexSources(paths, options={}) {
  const outcome={results:[],error:null};
  if(state.indexing || state.busy){return {error:'Let the current operation finish first.',results:[]};}
  try {
    if(mode==='dashboard')setView('home');
    else{state.results=null;state.collection=null;state.query='';document.querySelector('#search-input').value='';renderRows();}
    state.indexing=true;notifyNavigation();
    for(let i=0;i<paths.length;i++){
      const {id}=await api.index({path:paths[i]});
      let lastRevision=-1,lastRefresh=0,refreshing=false;
      const result=await pollJob(id, job=>{
        state.latestIndexProgress=job.progress;
        renderIndexProgress(job,i+1,paths.length,paths[i]);
        options.onProgress?.(job);onboarding?.update();
        const revision=job.progress?.revision ?? -1;
        if(revision>lastRevision && Date.now()-lastRefresh>700 && !refreshing){
          lastRevision=revision;lastRefresh=Date.now();refreshing=true;
          refreshLibrary().then(()=>api.libraryChanged()).finally(()=>{refreshing=false;});
        }
      });
      outcome.results.push({path:paths[i],result});
      toast(`${basename(paths[i])}: ${result.new || 0} added, ${result.changed || 0} updated${result.failed ? `, ${result.failed} failed` : ''}.`);
    }
  }catch(error){outcome.error=errorMessage(error);toast(outcome.error);}
  finally {state.indexing=false;notifyNavigation();const panel=document.querySelector('#indexing');if(panel)panel.innerHTML='';await refreshLibrary();onboarding?.update();}
  return outcome;
}
function syncNavigation() {
  notifyNavigation();
  document.querySelectorAll('[data-view], [data-collection]').forEach(node => {
    const active = node.hasAttribute('data-collection')
      ? state.collections[Number(node.dataset.collection)]?.path === state.collection
      : !state.collection && node.dataset.view === state.view;
    node.classList.toggle('active', active);
    if (active) node.setAttribute('aria-current', 'page');
    else node.removeAttribute('aria-current');
  });
}
function setView(view, collection=null) {
  if(mode !== 'dashboard')return;
  state.view=view;state.collection=collection;state.filter='all';state.results=null;state.query='';document.querySelector('#search-input').value='';
  syncNavigation();
  document.querySelectorAll('[data-filter]').forEach(node=>node.classList.toggle('active',node.dataset.filter==='all'));
  document.querySelector('#page-title').textContent=collection?basename(collection):view==='home'?'Your things, found.':'Everything, in reach.';
  document.querySelector('#page-description').textContent=collection?'':'Notes, documents, and code.';
  document.querySelector('#page-description').hidden = Boolean(collection);
  document.querySelector('#breadcrumb').textContent=collection?basename(collection):view==='home'?'Overview':'All files';
  document.querySelector('#stats').hidden=view!=='home';
  renderRows();
}
async function removeCollection(collection,button) {
  if(state.indexing || state.busy){toast('Let the current operation finish first.');return;}
  if(!collection)return;
  if(button)button.disabled=true;
  state.busy=true;notifyNavigation();
  try{
    const job=await api.removeCollection(collection.path);if(job.canceled)return;
    await pollJob(job.id);state.results=null;state.selected=null;state.previewVersion++;
    await refreshLibrary();await api.libraryChanged();toast(`Removed ${collection.name} from Recall. Your files are unchanged.`);
  }catch(error){toast(errorMessage(error));}
  finally{state.busy=false;notifyNavigation();if(button)button.disabled=false;}
}
api?.onCommand(async command=>{
  if(command.action==='appearance'){setAppearance(command.value);return;}
  if(mode!=='dashboard')return;
  try{
    if(command.action==='onboarding')return await onboarding.open();
    if(command.action==='add-files')return await addSources('files');
    if(command.action==='add-folder')return await addSources('folder');
    if(command.action==='index-progress'){
      const panel=document.querySelector('#indexing');
      if(!panel.querySelector('.index-card')){
        if(state.indexing)state.revealIndexProgress=true;else toast('No indexing is running.');
        return;
      }
      panel.scrollIntoView({block:'center',behavior:'smooth'});const folders=panel.querySelector('details');if(folders)folders.open=true;return;
    }
    const collection=state.collections.find(item=>item.path===command.collection);
    if(!collection){toast('Select a collection first.');return;}
    if(command.action==='search-collection'){setView('all',collection.path);document.querySelector('#search-input').focus();}
    if(command.action==='reindex')await indexSources([collection.path]);
    if(command.action==='remove-collection')await removeCollection(collection);
  }catch(error){toast(errorMessage(error));}
});
app.addEventListener('click',async event=>{
  const remove = event.target.closest('[data-remove-collection]');
  if(remove){
    await removeCollection(state.collections[Number(remove.dataset.removeCollection)],remove);
    return;
  }
  const row=event.target.closest('[data-row]');
  if(row){state.selectedIndex=Number(row.dataset.row);state.selected=state.visibleRows[state.selectedIndex];document.querySelectorAll('[data-row]').forEach(node=>{const selected=node===row;node.classList.toggle('selected',selected);node.setAttribute('aria-pressed',selected);});showPreview(state.selected);return;}
  const collection=event.target.closest('[data-collection]');if(collection){setView('all',state.collections[Number(collection.dataset.collection)].path);return;}
  const view=event.target.closest('[data-view]');if(view){setView(view.dataset.view);return;}
  const filter=event.target.closest('[data-filter]');if(filter){state.filter=filter.dataset.filter;document.querySelectorAll('[data-filter]').forEach(node=>node.classList.toggle('active',node===filter));renderRows();return;}
  const page=event.target.closest('[data-page]');if(page && !page.disabled){showPreview(state.selected,Number(page.dataset.page));return;}
  const action=event.target.closest('[data-action]')?.dataset.action;if(!action)return;
  try{
    if(action==='add-files')await addSources('files');
    else if(action==='add-folder')await addSources('folder');
    else if(action==='focus-search')document.querySelector('#search-input').focus();
    else if(action==='launcher')await api.launcher();
    else if(action==='hide')await api.hide();
    else if(action==='dashboard')await api.dashboard();
    else if(action==='open-preview' && state.selected)await api.openPreview(previewRequest(state.selected,state.previewData?.page));
    else if(action==='open-original' && state.selected)await api.openOriginal({path:state.selected.path});
  }catch(error){toast(errorMessage(error));}
});
app.addEventListener('dblclick',event=>{if(event.target.closest('[data-row]') && state.selected)api.openPreview(previewRequest(state.selected)).catch(error=>toast(errorMessage(error)));});
document.addEventListener('keydown',event=>{
  if(onboarding?.isOpen)return;
  if(event.key==='Escape'){
    if(mode==='launcher')api.hide();
    else if(state.results){state.results=null;state.query='';const input=document.querySelector('#search-input');if(input)input.value='';renderRows();}
  }
  if(mode==='launcher' && ['ArrowDown','ArrowUp'].includes(event.key) && state.visibleRows?.length){event.preventDefault();state.selectedIndex=Math.max(0,Math.min(state.visibleRows.length-1,state.selectedIndex+(event.key==='ArrowDown'?1:-1)));document.querySelector(`[data-row="${state.selectedIndex}"]`)?.click();document.querySelector(`[data-row="${state.selectedIndex}"]`)?.scrollIntoView({block:'nearest'});}
  if(mode==='launcher' && event.key==='Enter' && state.selected && !state.busy && document.querySelector('#search-input').value.trim() === state.completedQuery){event.preventDefault();api.openPreview(previewRequest(state.selected)).catch(error=>toast(errorMessage(error)));}
});
shell();
if(mode==='dashboard')onboarding=createOnboarding({api,icon,esc,appearanceControl,getState:()=>state,startIndex:indexSources,
  onOpen:notifyNavigation,onClose:query=>{notifyNavigation();if(query){setView('home');state.query=query;document.querySelector('#search-input').value=query;runSearch();}else document.querySelector('#search-input').focus();}});
api?.onLibraryChanged(()=>{
  if(mode==='settings')return;
  if(mode==='preview'){
    if(state.selected)api.library().then(library=>{
      const entry=library.files.find(file=>file.path===state.selected.path);
      if(!entry || (state.previewIndexedAt && entry.indexed_at!==state.previewIndexedAt))showPreview(state.selected);
      if(entry)state.previewIndexedAt=entry.indexed_at;
    }).catch(error=>toast(errorMessage(error)));
    return;
  }
  state.results=null;state.previewVersion++;
  refreshLibrary();
});
connectAppearance();
