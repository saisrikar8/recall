// Development builds need an explicit LaunchAgent: macOS cannot register an
// unpackaged Electron executable as a reliable, app-specific login item.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const label = 'app.recall.desktop';
const xml = value => String(value).replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&apos;' }[c]));
function agentPlist({ executable, project, python, database }) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${label}</string>
<key>ProgramArguments</key><array><string>${xml(executable)}</string><string>${xml(project)}</string><string>--background</string></array>
<key>WorkingDirectory</key><string>${xml(path.dirname(project))}</string>
<key>EnvironmentVariables</key><dict><key>RECALL_PYTHON</key><string>${xml(python)}</string><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>${database ? `<key>RECALL_DB_PATH</key><string>${xml(database)}</string>` : ''}</dict>
<key>RunAtLoad</key><true/>
<key>ProcessType</key><string>Interactive</string>
</dict></plist>\n`;
}
function setDevelopmentLogin(enabled, options) {
  const file = path.join(os.homedir(), 'Library/LaunchAgents', `${label}.plist`);
  const domain = `gui/${process.getuid()}`;
  if (!enabled) {
    // Removing the file disables next-login startup without terminating the
    // current background instance (bootout would kill it).
    fs.rmSync(file, { force: true });
    return;
  }
  const plist = agentPlist(options);
  const unchanged = fs.existsSync(file) && fs.readFileSync(file, 'utf8') === plist;
  if (!unchanged) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, plist, { mode: 0o600 });
  }
  const status = spawnSync('/bin/launchctl', ['print', `${domain}/${label}`]);
  if (status.status !== 0) {
    const result = spawnSync('/bin/launchctl', ['bootstrap', domain, file], { encoding: 'utf8' });
    if (result.status !== 0) throw new Error(result.stderr || 'Could not enable Recall at login.');
  }
}
module.exports = { agentPlist, setDevelopmentLogin };
