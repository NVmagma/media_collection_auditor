"use strict";
const mediaViewButtons = document.querySelectorAll('[data-view]');
function setMediaView(view) {
  const selectedView = view === 'posters' ? 'posters' : 'table';
  document.querySelectorAll('.lifecycle-panel .table-wrap').forEach(table =>
    table.classList.toggle('hidden-section', selectedView !== 'table'));
  document.querySelectorAll('.media-poster-list').forEach(list =>
    list.classList.toggle('hidden-section', selectedView !== 'posters'));
  mediaViewButtons.forEach(button => {
    const selected = button.dataset.view === selectedView;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  try { localStorage.setItem('auditor-media-view', selectedView); } catch (_) {}
}
mediaViewButtons.forEach(button => button.addEventListener('click', () => setMediaView(button.dataset.view)));
try { setMediaView(localStorage.getItem('auditor-media-view') || 'table'); }
catch (_) { setMediaView('table'); }
const tabs = document.querySelectorAll('[data-tab]');
const panels = document.querySelectorAll('[data-panel]');
const workspaces = document.querySelectorAll('[data-workspace]');
const libraryNames = ['Movies', 'TV Shows'];
let lastLibrary = 'Movies';
const descriptions = {
  Overview: 'Review library coverage, tracking gaps and scheduler observations.',
  Library: 'Browse movie and TV folders by lifecycle stage.',
  'Audit Preview': 'Review saved-date estimates before a future audit.',
  Activity: 'Inspect recent action log entries for both libraries.',
  History: 'Review recorded audit attempts and their reported outcomes.'
};
function openSection(name) {
  if (name === 'Library') name = lastLibrary;
  if (!Array.from(panels).some(panel => panel.dataset.panel === name)) name = 'Overview';
  const isLibrary = libraryNames.includes(name);
  if (isLibrary) lastLibrary = name;
  const workspace = isLibrary ? 'Library' : name;
  tabs.forEach(tab => {
    const selected = tab.dataset.tab === name;
    tab.classList.toggle('selected', selected);
    tab.setAttribute('aria-pressed', String(selected));
  });
  workspaces.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.workspace === workspace)));
  panels.forEach(panel => panel.classList.toggle('hidden-section', panel.dataset.panel !== name));
  document.getElementById('library-toolbar').classList.toggle('hidden-section', !isLibrary);
  document.querySelectorAll('[data-workspace-context]').forEach(element =>
    element.classList.toggle('hidden-section', !element.dataset.workspaceContext.split(' ').includes(workspace)));
  document.getElementById('workspace-title').textContent = workspace === 'Audit Preview' ? 'Scans' : workspace;
  document.getElementById('workspace-description').textContent = descriptions[workspace];
}
workspaces.forEach(button => button.addEventListener('click', () => openSection(button.dataset.workspace)));
tabs.forEach(tab => tab.addEventListener('click', () => openSection(tab.dataset.tab)));
document.querySelectorAll('[data-open-library]').forEach(button =>
  button.addEventListener('click', () => openSection(button.dataset.openLibrary)));
openSection('Overview');
document.querySelectorAll('[data-stage-tab]').forEach(tab => tab.addEventListener('click', () => {
  const section = tab.closest('[data-panel]');
  section.querySelectorAll('[data-stage-tab]').forEach(item => {
    const selected = item === tab;
    item.classList.toggle('selected', selected);
    item.setAttribute('aria-selected', String(selected));
  });
  section.querySelectorAll('[data-stage-panel]').forEach(panel =>
    panel.classList.toggle('hidden-section', panel.dataset.stagePanel !== tab.dataset.stageTab));
}));
document.querySelectorAll('.rescue-choice').forEach(choice => choice.addEventListener('change', async () => {
  const destination = choice.value;
  if (!destination) return;
  const title = choice.dataset.title;
  const library = choice.dataset.library;
  if (!confirm('Rescue ' + title + ' (' + library + ') to ' + destination + '? Live mode moves media.')) { choice.value = ''; return; }
  choice.disabled = true;
  try {
    const response = await fetch('/api/rescue', {method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({title, library, destination})});
    const data = await response.json();
    alert(data.message || 'Request failed.');
    if (data.ok) location.reload();
  } catch (error) { alert('Unable to request rescue.'); }
  finally { choice.disabled = false; choice.value = ''; }
}));
const button = document.getElementById('run-now');
button?.addEventListener('click', async () => {
  if (button.dataset.preview !== 'true' && !confirm('Start an audit using your saved configuration? In Live Mode this may move or delete media.')) return;
  button.disabled = true;
  const output = document.getElementById('run-result');
  output.textContent = 'Requesting audit…';
  try {
    const response = await fetch('/api/run-now', {method:'POST', credentials:'same-origin'});
    const data = await response.json();
    output.textContent = data.message || 'Request failed.';
    if (response.status === 401) output.textContent = 'Please open Settings to sign in, then try again.';
  } catch (error) { output.textContent = 'Unable to request an audit.'; }
  finally { button.disabled = false; }
});
