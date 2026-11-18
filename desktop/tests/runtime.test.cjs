const { test } = require('node:test');
const assert = require('node:assert/strict');
const { engineLaunch } = require('../runtime.cjs');
test('Windows package uses bundled Python and OCR independently of checkout and user Python',()=>{
 const launch=engineLaunch({packaged:true,platform:'win32',root:'C:\\checkout',resources:'C:\\Program Files\\Recall\\resources',userData:'C:\\Users\\Test\\Recall',env:{RECALL_PYTHON:'missing.exe',Path:'C:\\Windows\\System32'}});
 assert.equal(launch.command,'C:\\Program Files\\Recall\\resources\\runtime\\python\\python.exe');
 assert.equal(launch.options.env.RECALL_TESSERACT,'C:\\Program Files\\Recall\\resources\\runtime\\ocr\\tesseract.exe');
 assert.equal(launch.options.cwd,'C:\\Users\\Test\\Recall');assert.equal(launch.options.windowsHide,true);
 assert.deepEqual(launch.args.slice(0,2),['-I','-B']);assert.match(launch.options.env.PATH,/C:\\Windows\\System32$/);
});
test('Mac package retains its standalone Python and OCR layout',()=>{
 const launch=engineLaunch({packaged:true,platform:'darwin',root:'/checkout',resources:'/Applications/Recall.app/Contents/Resources',userData:'/tmp/user',env:{}});
 assert.equal(launch.command,'/Applications/Recall.app/Contents/Resources/runtime/python/bin/python3');
 assert.equal(launch.options.env.RECALL_TESSERACT,'/Applications/Recall.app/Contents/Resources/runtime/ocr/bin/tesseract');
});
test('development continues using the configured Python',()=>{
 const launch=engineLaunch({packaged:false,platform:'win32',root:'C:\\checkout',resources:'C:\\electron',userData:'C:\\user',env:{RECALL_PYTHON:'C:\\dev\\python.exe'}});
 assert.equal(launch.command,'C:\\dev\\python.exe');assert.equal(launch.options.cwd,'C:\\checkout');assert.equal(launch.args.includes('-I'),false);
});
