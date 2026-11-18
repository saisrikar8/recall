const path = require('node:path');

function engineLaunch({ packaged, platform = process.platform, root, resources, userData, env = process.env }) {
  const paths = platform === 'win32' ? path.win32 : path.posix;
  const runtime = paths.join(resources, 'runtime');
  const command = packaged
    ? paths.join(runtime, platform === 'win32' ? 'python/python.exe' : 'python/bin/python3')
    : env.RECALL_PYTHON || paths.join(root, '.venv', platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const childEnv = { ...env, PYTHONUNBUFFERED: '1',
    RECALL_EMBEDDING_SOCKET: env.RECALL_EMBEDDING_SOCKET || paths.join(userData, 'desktop-local-models.sock') };
  if (packaged) {
    childEnv.RECALL_TESSERACT = paths.join(runtime, platform === 'win32' ? 'ocr/tesseract.exe' : 'ocr/bin/tesseract');
    childEnv.TESSDATA_PREFIX = paths.join(runtime, 'ocr/tessdata');
    if (platform === 'win32') {
      // Torch and OCR require the bundled Microsoft runtime DLLs on clean PCs.
      childEnv.PATH = [paths.join(runtime, 'python'), paths.join(runtime, 'ocr'), childEnv.PATH || childEnv.Path || ''].join(';');
      delete childEnv.Path;
    }
  }
  return { command, args: [...(packaged ? ['-I', '-B'] : []), '-u', '-m', 'src.desktop_bridge'],
    options: { cwd: packaged ? userData : root, env: childEnv, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] } };
}
module.exports = { engineLaunch };
