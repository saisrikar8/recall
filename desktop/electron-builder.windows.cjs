const { build } = require('./package.json');
module.exports = {
  ...build,
  directories: { output: '../dist/windows' },
  extraResources: [{ from: '../build/windows/runtime', to: 'runtime' }],
  artifactName: 'Recall-Setup-${version}-${arch}.${ext}',
  win: { target: [{ target: 'nsis', arch: ['x64'] }], icon: 'icon.png', signAndEditExecutable: false },
  nsis: { oneClick: false, perMachine: false, allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true, createStartMenuShortcut: true, runAfterFinish: false }
};
