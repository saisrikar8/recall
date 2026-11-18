const modes = new Set(['system', 'light', 'dark']);
const system = matchMedia('(prefers-color-scheme: dark)');
let preference = 'system';
try { const saved = localStorage.getItem('recall-appearance'); if (modes.has(saved)) preference = saved; } catch {}
function apply() {
  const theme = preference === 'system' ? (system.matches ? 'dark' : 'light') : preference;
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  document.querySelectorAll('[data-appearance]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.appearance === preference));
  });
  document.querySelectorAll('.appearance-switch').forEach(group=>group.style.setProperty('--selected', [...modes].indexOf(preference)));
}
export function setAppearance(value) {
  if (!modes.has(value)) return;
  preference = value;
  try { localStorage.setItem('recall-appearance', value); } catch {}
  apply();
  window.recall?.setAppearance(value).catch(()=>{});
}
export function connectAppearance(root = document) {
  apply();
  window.recall?.setAppearance(preference).catch(()=>{});
  root.querySelectorAll('.appearance-switch').forEach(group=>{
  if(group.dataset.connected)return;
  group.dataset.connected='true';
  group?.addEventListener('click', event => {
    const button = event.target.closest('[data-appearance]');
    if (button) setAppearance(button.dataset.appearance);
  });
  group?.addEventListener('keydown', event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    const choices = [...modes];
    const current = choices.indexOf(event.target.closest('[data-appearance]')?.dataset.appearance || preference);
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (current + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
    setAppearance(choices[index]);
    group.querySelector(`[data-appearance="${choices[index]}"]`).focus();
  });
  });
}
system.addEventListener('change', apply);
window.addEventListener('storage', event => {
  if (event.key === 'recall-appearance') { preference = modes.has(event.newValue) ? event.newValue : 'system'; apply(); window.recall?.setAppearance(preference).catch(()=>{}); }
});
apply();
