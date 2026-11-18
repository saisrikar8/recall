const { contextBridge, ipcRenderer } = require('electron');
const call = name => (...args) => ipcRenderer.invoke(`recall:${name}`, ...args);
contextBridge.exposeInMainWorld('recall', {
  finishOnboarding: call('onboarding-complete'),
  preferences: call('preferences'), setLogin: call('set-login'), settings: call('settings'),
  setAppearance: call('appearance'), navigation: call('navigation'),
  onCommand: callback => { ipcRenderer.on('recall:command', (_, value) => callback(value)); },
  onPreferencesChanged: callback => { ipcRenderer.on('recall:preferences-changed', () => callback()); },
  library: call('library'), search: call('search'), job: call('job'), preview: call('preview'),
  removeCollection: call('remove-collection'), libraryChanged: call('library-changed'),
  onLibraryChanged: callback => { ipcRenderer.on('recall:library-changed', () => callback()); },
  index: call('index'), pick: call('pick'), openOriginal: call('open-original'),
  openPreview: call('open-preview'), dashboard: call('dashboard'), hide: call('hide'),
  launcher: call('launcher'), status: call('status'), engineStatus: call('engine-status'),
  onSelection: callback => { ipcRenderer.on('recall:selection', (_, selection) => callback(selection)); },
  onFocus: callback => { ipcRenderer.on('recall:focus', () => callback()); }
});
