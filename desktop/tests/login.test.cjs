const {test} = require('node:test');
const assert = require('node:assert/strict');
const {agentPlist} = require('../login.cjs');
test('login agent launches this checkout silently, with escaped literal arguments',()=>{
 const plist=agentPlist({executable:'/Applications/A & B/Electron', project:'/Work/My <Recall>/desktop', python:'/Work/My Recall/.venv/bin/python', database:'/Work/My Recall/test.db'});
 assert.match(plist,/<string>--background<\/string>/);
 assert.match(plist,/A &amp; B/);
 assert.match(plist,/My &lt;Recall&gt;/);
 assert.match(plist,/<key>RECALL_DB_PATH<\/key>/);
 assert.match(plist,/<key>RunAtLoad<\/key><true\/>/);
 assert.doesNotMatch(plist,/KeepAlive/); // An explicit Quit must stay quit.
});
