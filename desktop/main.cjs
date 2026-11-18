const { app, BrowserWindow, ipcMain, dialog, globalShortcut, Menu, Tray, nativeImage, session } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const { menuTemplate } = require('./menu.cjs');
const { engineLaunch } = require('./runtime.cjs');
const { setDevelopmentLogin } = require('./login.cjs');
const readline = require('node:readline');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '..');
const page = path.join(__dirname, 'renderer/index.html');
app.setName('Recall');
if (process.env.RECALL_DESKTOP_USER_DATA) {
  fs.mkdirSync(process.env.RECALL_DESKTOP_USER_DATA, { recursive: true });
  app.setPath('userData', process.env.RECALL_DESKTOP_USER_DATA);
}
let dashboard, launcher, settingsWindow, tray, worker, quitting = false, sequence = 0;
const pending = new Map();
const knownWindows = new Set();
let startupError = '';
let loginEnabled = false;
let appearance = 'system';
let navigation = { collection: null, busy: false, indexing: false };
let loginError = '';
function syncDock() {
  if (process.platform !== 'darwin') return;
  if (BrowserWindow.getAllWindows().some(win => win.isVisible() && win !== launcher)) {
    if (!app.dock.isVisible()) app.dock.show();
  } else if (app.dock.isVisible()) app.dock.hide();
}
function configureLogin(enabled) {
  if (process.env.RECALL_DISABLE_AUTOSTART === '1') { loginEnabled = enabled; return; }
  if (process.platform === 'darwin' && !app.isPackaged) {
    setDevelopmentLogin(enabled, { executable: process.execPath, project: __dirname, database: process.env.RECALL_DB_PATH,
      python: process.env.RECALL_PYTHON || path.join(root, '.venv/bin/python') });
  } else if (process.platform === 'darwin' || process.platform === 'win32') {
    app.setLoginItemSettings({ openAtLogin: enabled, args: app.isPackaged ? ['--background'] : [__dirname, '--background'] });
  }
  loginEnabled = enabled;
  fs.mkdirSync(app.getPath('userData'), { recursive: true });
  fs.writeFileSync(path.join(app.getPath('userData'), 'preferences.json'), JSON.stringify({ ...readPreferences(), openAtLogin: enabled }));
}

function readPreferences() {
  try { return JSON.parse(fs.readFileSync(path.join(app.getPath('userData'), 'preferences.json'), 'utf8')); }
  catch { return {}; }
}
function showSettings() {
  if (!settingsWindow || settingsWindow.isDestroyed()) settingsWindow = makeWindow('settings');
  else { settingsWindow.show(); settingsWindow.focus(); }
}
function sendCommand(action, payload) {
  showDashboard();
  const send = () => dashboard.webContents.send('recall:command', { action, ...payload });
  if (dashboard.webContents.isLoadingMainFrame()) dashboard.webContents.once('did-finish-load', send);
  else send();
}
function updateMenus() {
  if (!app.isReady()) return;
  const changeLogin = enabled => {
    try { configureLogin(enabled); loginError = ''; }
    catch (error) { loginError = error.message; dialog.showErrorBox('Could not change startup setting', error.message); }
    updateMenus();
    for (const win of BrowserWindow.getAllWindows()) win.webContents.send('recall:preferences-changed');
  };
  Menu.setApplicationMenu(Menu.buildFromTemplate(menuTemplate({
    settings: showSettings, library: showDashboard, search: toggleLauncher,
    command: action => sendCommand(action, { collection: navigation.collection }),
    onboarding: () => sendCommand('onboarding'),
    appearance: value => { for (const win of BrowserWindow.getAllWindows()) win.webContents.send('recall:command', { action: 'appearance', value }); }, login: changeLogin
  }, { ...navigation, login: loginEnabled, appearance })));
  if (tray) tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Search Recall', click: toggleLauncher }, { label: 'Open Library', click: showDashboard },
    { label: 'Settings…', click: showSettings }, { type: 'separator' },
    { label: 'Start at Login', type: 'checkbox', checked: loginEnabled, click: item => changeLogin(item.checked) },
    { type: 'separator' }, { label: 'Quit Recall', click: () => app.quit() }
  ]));
}

function backend(method, data = {}) {
  return new Promise((resolve, reject) => {
    if (!worker || worker.exitCode !== null || startupError) return reject(new Error(startupError || 'Recall engine is unavailable. Restart the app.'));
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('The engine took too long to respond.')); }, 120000);
    pending.set(id, { resolve, reject, timer });
    worker.stdin.write(JSON.stringify({ id, method, data }) + '\n', error => {
      if (error) { clearTimeout(timer); pending.delete(id); reject(error); }
    });
  });
}
function startEngine() {
  const launch = engineLaunch({ packaged: app.isPackaged, root, resources: process.resourcesPath, userData: app.getPath('userData') });
  worker = spawn(launch.command, launch.args, launch.options);
  const fail = message => {
    startupError = message;
    for (const { reject, timer } of pending.values()) { clearTimeout(timer); reject(new Error(message)); }
    pending.clear();
  };
  worker.on('error', error => fail(`Could not start Recall: ${error.message}. ${app.isPackaged ? 'Reinstall Recall or report this error.' : 'Set RECALL_PYTHON to your Recall Python environment.'}`));
  worker.on('exit', code => { if (!quitting) fail(`Recall engine stopped (${code}). Restart the app.`); });
  worker.stderr.on('data', chunk => process.stderr.write(chunk));
  readline.createInterface({ input: worker.stdout }).on('line', line => {
    let reply; try { reply = JSON.parse(line); } catch { return; }
    const request = pending.get(reply.id); if (!request) return;
    clearTimeout(request.timer); pending.delete(reply.id);
    reply.error ? request.reject(new Error(reply.error)) : request.resolve(reply.result);
  });
}
function makeWindow(mode, payload) {
  const compact = mode === 'launcher';
  const settings = mode === 'settings';
  const win = new BrowserWindow({ width: compact ? 820 : settings ? 600 : 1380, height: compact ? 590 : settings ? 490 : 900,
    minWidth: compact ? 680 : settings ? 520 : 900, minHeight: compact ? 450 : settings ? 430 : 640,
    title: settings ? 'Recall Settings' : 'Recall', icon: path.join(__dirname, 'icon.png'), show: false, backgroundColor: '#f7f7f2',
    ...(compact ? {} : { titleBarStyle: 'hiddenInset' }), roundedCorners: true,
    ...(compact ? { frame: false, alwaysOnTop: true, resizable: false } : {}),
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true }
  });
  if (compact && process.platform === 'darwin') win.setWindowButtonVisibility(false);
  win.on('show', syncDock);
  win.on('hide', syncDock);
  win.on('closed', () => setImmediate(syncDock));
  const contentsId = win.webContents.id;
  knownWindows.add(contentsId);
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', event => event.preventDefault());
  win.on('closed', () => knownWindows.delete(contentsId));
  win.loadFile(page, { query: { mode } });
  win.once('ready-to-show', () => { if (payload) win.webContents.send('recall:selection', payload); win.show(); });
  return win;
}
function showDashboard() {
  if (!dashboard || dashboard.isDestroyed()) {
    dashboard = makeWindow('dashboard');
    dashboard.on('close', event => { if (!quitting) { event.preventDefault(); dashboard.hide(); } });
  } else { dashboard.show(); dashboard.focus(); }
  return dashboard;
}
function toggleLauncher() {
  if (!launcher || launcher.isDestroyed()) {
    launcher = makeWindow('launcher');
    launcher.on('blur', () => launcher.hide());
  } else if (launcher.isVisible()) launcher.hide();
  else { launcher.center(); launcher.show(); launcher.focus(); launcher.webContents.send('recall:focus'); }
}
function validateSender(event) {
  if (!knownWindows.has(event.sender.id) || !event.senderFrame || !event.senderFrame.url.startsWith(pathToFileURL(page).href)) throw new Error('Untrusted window.');
}
function handle(name, fn) { ipcMain.handle(`recall:${name}`, (event, ...args) => { validateSender(event); return fn(event, ...args); }); }
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', (_event, args) => { if (!args.includes('--background')) showDashboard(); });
  app.whenReady().then(() => {
    session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    startEngine();
    if (process.platform === 'darwin') {
      // Dock artwork needs a transparent safe area to match neighboring app icons.
      const artwork = nativeImage.createFromPath(path.join(__dirname, 'icon.png'))
        .resize({ width: 416, height: 416, quality: 'best' }).toBitmap();
      const canvas = Buffer.alloc(512 * 512 * 4);
      for (let row = 0; row < 416; row++) {
        artwork.copy(canvas, ((row + 48) * 512 + 48) * 4, row * 416 * 4, (row + 1) * 416 * 4);
      }
      app.dock.setIcon(nativeImage.createFromBitmap(canvas, { width: 512, height: 512 }));
    }

    app.setAboutPanelOptions({ applicationName: 'Recall', applicationVersion: require('./package.json').version,
      iconPath: path.join(__dirname, 'icon.png'), copyright: 'Local search for your files.' });
    handle('preferences', () => ({ appearance, openAtLogin: loginEnabled, loginError, shortcut: '⌘ Shift Space', onboardingCompleted: Boolean(readPreferences().onboardingCompleted) }));
    handle('set-login', (_, enabled) => {
      if (typeof enabled !== 'boolean') throw new Error('Invalid startup preference.');
      try { configureLogin(enabled); loginError = ''; }
      catch (error) { loginError = error.message; throw error; }
      updateMenus();
      for (const win of BrowserWindow.getAllWindows()) win.webContents.send('recall:preferences-changed');
      return { openAtLogin: loginEnabled };
    });
    handle('onboarding-complete', (_, outcome) => {
      if (!['complete','skipped','existing-library'].includes(outcome)) throw new Error('Invalid setup outcome.');
      fs.mkdirSync(app.getPath('userData'), { recursive: true });
      fs.writeFileSync(path.join(app.getPath('userData'), 'preferences.json'), JSON.stringify({
        ...readPreferences(), onboardingCompleted: true, onboardingVersion: 1, onboardingOutcome: outcome
      }));
    });
    handle('settings', showSettings);
    handle('appearance', (_, value) => {
      if (!['system','light','dark'].includes(value)) throw new Error('Invalid appearance.');
      if (appearance !== value) { appearance = value; updateMenus(); }
    });
    handle('navigation', (event, value) => {
      if (!event.sender.getURL().includes('mode=dashboard')) return;
      navigation = { collection: typeof value?.collection === 'string' ? value.collection : null,
        busy: Boolean(value?.busy), indexing: Boolean(value?.indexing), onboarding: Boolean(value?.onboarding) }; updateMenus();
    });
    handle('engine-status', () => backend('engine-status'));
    handle('library', () => backend('library'));
    handle('search', (_, data) => backend('search', data));
    handle('job', (_, id) => backend('job', { id }));
    handle('preview', (_, data) => backend('preview', data));
    handle('remove-collection', async (event, root) => {
      if (typeof root !== 'string' || !root.trim()) throw new Error('Select a collection.');
      const confirmation = await dialog.showMessageBox(BrowserWindow.fromWebContents(event.sender), {
        type: 'question', title: 'Remove collection', message: `Remove “${path.basename(root)}” from Recall?`,
        detail: `Its search index will be removed. Your original files stay on disk.\n\n${root}`,
        buttons: ['Cancel', 'Remove from Recall'], defaultId: 0, cancelId: 0, noLink: true
      });
      if (confirmation.response !== 1) return { canceled: true };
      return backend('remove-collection', { collection: root });
    });
    handle('library-changed', event => {
      for (const win of BrowserWindow.getAllWindows()) {
        if (win.webContents.id !== event.sender.id) win.webContents.send('recall:library-changed');
      }
    });
    handle('index', (_, data) => backend('index', data));
    handle('open-original', (_, data) => backend('open', data));
    handle('pick', async (event, kind) => {
      const result = await dialog.showOpenDialog(BrowserWindow.fromWebContents(event.sender), { title: kind === 'folder' ? 'Add a folder to Recall' : 'Add files to Recall', properties: kind === 'folder' ? ['openDirectory'] : ['openFile', 'multiSelections'] });
      return result.canceled ? [] : result.filePaths.map(file => fs.realpathSync(file));
    });
    handle('open-preview', async (_, data) => { await backend('validate', { path: data.path }); makeWindow('preview', data); if (launcher) launcher.hide(); });
    handle('dashboard', () => { showDashboard(); });
    handle('hide', event => BrowserWindow.fromWebContents(event.sender).hide());
    handle('launcher', toggleLauncher);
    handle('status', () => ({ shortcut: globalShortcut.isRegistered('CommandOrControl+Shift+Space') ? '⌘ ⇧ Space' : null }));
    globalShortcut.register('CommandOrControl+Shift+Space', toggleLauncher);
    const trayAsset = nativeImage.createFromPath(path.join(__dirname, 'tray.png'));
    // Menu bar images use logical points; retain the original at Retina scale.
    const icon = trayAsset.resize({ width: 24, height: 24, quality: 'best' });
    icon.addRepresentation({ scaleFactor: 2, buffer: trayAsset.resize({ width: 48, height: 48, quality: 'best' }).toPNG() });
    icon.setTemplateImage(true);
    tray = new Tray(icon); tray.setToolTip('Recall');
    try {
      const preferences = path.join(app.getPath('userData'), 'preferences.json');
      const enabled = fs.existsSync(preferences) ? JSON.parse(fs.readFileSync(preferences, 'utf8')).openAtLogin !== false : true;
      configureLogin(enabled);
    } catch (error) { console.error('Recall login setup:', error.message); }
    updateMenus();
    const background = process.argv.includes('--background') ||
      (app.isPackaged && process.platform === 'darwin' && app.getLoginItemSettings().wasOpenedAtLogin);
    if (background) syncDock(); else showDashboard();
  });
  app.on('activate', showDashboard);
  app.on('window-all-closed', () => {});
  app.on('before-quit', () => { quitting = true; globalShortcut.unregisterAll(); if (worker) worker.kill(); });
}
