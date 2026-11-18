const {test}=require('node:test');
const assert=require('node:assert/strict');
const {menuTemplate}=require('../menu.cjs');
function items(state){const result={};const visit=entries=>{for(const item of entries){if(item.id)result[item.id]=item;if(Array.isArray(item.submenu))visit(item.submenu);}};visit(menuTemplate({},state));return result;}
test('collection actions require a selected collection and idle engine',()=>{
 assert.equal(items({})['reindex'].enabled,false);
 assert.equal(items({collection:'/notes'})['reindex'].enabled,true);
 assert.equal(items({collection:'/notes',busy:true})['remove'].enabled,false);
 assert.equal(items({collection:'/notes',busy:true})['add-files'].enabled,false);
 assert.equal(items({indexing:true})['index-progress'].enabled,true);
});
test('appearance and shortcut menu state mirrors the application',()=>{
 const menu=items({appearance:'dark',login:true});
 assert.equal(menu['theme-dark'].checked,true);assert.equal(menu['theme-light'].checked,false);
 assert.equal(menu.login.checked,true);
 assert.equal(menu['quick-search'].accelerator,'CommandOrControl+Shift+Space');
 assert.equal(menu['quick-search'].registerAccelerator,false);
 assert.equal(menu.settings.accelerator,'CommandOrControl+,');
});
