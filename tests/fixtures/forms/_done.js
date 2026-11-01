// Shared by fixtures: on submit, validate required fields and show a confirmation like a real ATS.
function jrSubmit(ev, msg) {
  if (ev) ev.preventDefault();
  const missing = [...document.querySelectorAll('[required]')].filter(e =>
    (e.type === 'radio' || e.type === 'checkbox') ? !document.querySelector(`[name="${e.name}"]:checked`) :
    (e.type === 'file' ? !e.files.length : !e.value));
  if (missing.length) { document.getElementById('err').textContent = 'Missing: ' + missing.map(m => m.name || m.id).join(', '); return false; }
  window.__submitted = Object.fromEntries([...document.querySelectorAll('input,textarea,select')].filter(e => e.name || e.id)
    .map(e => [e.name || e.id, e.type === 'file' ? (e.files[0] || {}).name : (e.type === 'radio' || e.type === 'checkbox') ? (e.checked ? e.value : undefined) : e.value])
    .filter(([k, v]) => v !== undefined));
  localStorage.setItem('jr_submitted', JSON.stringify(window.__submitted));
  document.body.innerHTML = '<h1>' + msg + '</h1><pre id="payload">' + JSON.stringify(window.__submitted) + '</pre>';
  return false;
}
