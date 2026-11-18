// Native menu definitions are kept separate from window/process lifecycle.
function menuTemplate(actions, state = {}) {
  const selected = Boolean(state.collection);
  const idle = !state.busy && !state.onboarding;
  return [
    { label: 'Recall', submenu: [
      { label: 'About Recall', role: 'about' },
      { label: 'Settings…', id: 'settings', accelerator: 'CommandOrControl+,', click: actions.settings },
      { label: 'Welcome to Recall…', id: 'onboarding', click: actions.onboarding },
      { label: 'Start at Login', id: 'login', type: 'checkbox', checked: Boolean(state.login), click: item => actions.login(item.checked) },
      { type: 'separator' }, { label: 'Open Library', click: actions.library },
      { type: 'separator' }, { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' },
      { type: 'separator' }, { label: 'Quit Recall', role: 'quit' }
    ] },
    { label: 'File', submenu: [
      { label: 'Add Files…', id: 'add-files', accelerator: 'CommandOrControl+O', enabled: idle, click: () => actions.command('add-files') },
      { label: 'Add Folder…', id: 'add-folder', accelerator: 'CommandOrControl+Shift+O', enabled: idle, click: () => actions.command('add-folder') },
      { type: 'separator' },
      { label: 'Reindex Selected Collection', id: 'reindex', enabled: selected && idle, click: () => actions.command('reindex') },
      { label: 'Remove Selected Collection…', id: 'remove', enabled: selected && idle, click: () => actions.command('remove-collection') },
      { type: 'separator' }, { role: 'close' }
    ] },
    { role: 'editMenu' },
    { label: 'Search', submenu: [
      { label: 'Quick Search', id: 'quick-search', accelerator: 'CommandOrControl+Shift+Space', registerAccelerator: false, click: actions.search },
      { label: 'Search This Collection', id: 'search-collection', enabled: selected && idle, click: () => actions.command('search-collection') }
    ] },
    { label: 'View', submenu: [
      { label: 'Appearance', submenu: ['system','light','dark'].map(value => ({
        label: value[0].toUpperCase() + value.slice(1), id: 'theme-' + value, type: 'radio', checked: (state.appearance || 'system') === value,
        click: () => actions.appearance(value)
      })) },
      { label: 'Show Indexing Progress', id: 'index-progress', enabled: Boolean(state.indexing), click: () => actions.command('index-progress') },
      { type: 'separator' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { type: 'separator' }, { role: 'togglefullscreen' }
    ] },
    { role: 'windowMenu' }
  ];
}
module.exports = { menuTemplate };
