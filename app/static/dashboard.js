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
  Overview: 'Collection status at a glance · live freshness unverified.',
  Review: 'Inspect coverage gaps and collection findings. No tracking changes are performed.',
  Library: 'Browse movie and TV folders by lifecycle stage.',
  'Audit Preview': 'Scheduler observations, recorded outcomes and separate timer estimates.',
  Activity: 'Inspect recent action log entries for both libraries.',
  History: 'Review recorded audit attempts and their reported outcomes.'
};
function openSection(name) {
  if (name === 'Library') name = lastLibrary;
  if (!Array.from(panels).some(panel => panel.dataset.panel === name)) name = 'Overview';
  const isLibrary = libraryNames.includes(name);
  if (isLibrary) lastLibrary = name;
  const workspace = isLibrary ? 'Library' : name;
  document.body.classList.toggle('viewing-overview', workspace === 'Overview');
  document.body.classList.toggle('viewing-review', workspace === 'Review');
  document.body.classList.toggle('viewing-history', workspace === 'History');
  closeInspector(false);
  document.getElementById('library-layout').classList.toggle('hidden-section', !isLibrary);
  tabs.forEach(tab => {
    const selected = tab.dataset.tab === name;
    tab.classList.toggle('selected', selected);
    tab.setAttribute('aria-pressed', String(selected));
  });
  workspaces.forEach(link => {
    if (link.dataset.workspace === workspace) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  panels.forEach(panel => panel.classList.toggle('hidden-section', panel.dataset.panel !== name));
  document.getElementById('library-toolbar').classList.toggle('hidden-section', !isLibrary);
  document.querySelectorAll('[data-workspace-context]').forEach(element =>
    element.classList.toggle('hidden-section', !element.dataset.workspaceContext.split(' ').includes(workspace)));
  document.getElementById('workspace-title').textContent = workspace === 'Audit Preview' ? 'Scans' : workspace;
  document.getElementById('workspace-description').textContent = descriptions[workspace];
  if (isLibrary) filterLibrary();
}
workspaces.forEach(link => link.addEventListener('click', event => {
  if (link.dataset.workspace === 'Review' || document.body.dataset.initialWorkspace === 'Review') return;
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  openSection(link.dataset.workspace);
  history.replaceState(null, '', link.getAttribute('href'));
}));
tabs.forEach(tab => tab.addEventListener('click', () => openSection(tab.dataset.tab)));
document.querySelectorAll('[data-open-library]').forEach(button =>
  button.addEventListener('click', () => {
    if (document.body.dataset.initialWorkspace === 'Review') {
      location.assign('/#' + encodeURIComponent(button.dataset.openLibrary));
      return;
    }
    openSection(button.dataset.openLibrary);
  }));
let inspectorTrigger = null;
function closeInspector(returnFocus) {
  document.getElementById('title-inspector').classList.add('hidden-section');
  document.getElementById('library-layout').classList.remove('has-selection');
  if (inspectorTrigger) {
    inspectorTrigger.setAttribute('aria-expanded', 'false');
    if (returnFocus && inspectorTrigger.getClientRects().length) inspectorTrigger.focus();
  }
  inspectorTrigger = null;
}
function activeLibrary() {
  return Array.from(panels).find(panel => libraryNames.includes(panel.dataset.panel) && !panel.classList.contains('hidden-section'));
}
function filterLibrary() {
  const section = activeLibrary();
  if (!section) return;
  const query = document.getElementById('library-search').value.trim().toLowerCase();
  const direction = document.getElementById('library-sort').value === 'desc' ? -1 : 1;
  section.querySelectorAll('tbody, .media-poster-list').forEach(container => {
    Array.from(container.querySelectorAll('[data-media-title]')).sort((a, b) =>
      direction * a.dataset.mediaTitle.localeCompare(b.dataset.mediaTitle, undefined, {numeric: true})).forEach(row => {
        row.classList.toggle('library-filtered-out', !row.dataset.mediaTitle.toLowerCase().includes(query));
        container.append(row);
      });
  });
  const stage = section.querySelector('.lifecycle-panel:not(.hidden-section)');
  const rows = stage ? Array.from(stage.querySelectorAll('tbody [data-media-title]')) : [];
  const matched = rows.filter(row => !row.classList.contains('library-filtered-out')).length;
  document.getElementById('library-results').textContent = 'Showing ' + matched + ' of ' + rows.length + ' folders in this stage · ' + section.dataset.panel;
  document.getElementById('library-no-matches').classList.toggle('hidden-section', matched > 0 || !query || rows.length === 0);
}
document.getElementById('library-search').addEventListener('input', () => {closeInspector(false); filterLibrary();});
document.getElementById('library-sort').addEventListener('change', filterLibrary);
document.getElementById('close-inspector').addEventListener('click', () => closeInspector(true));
document.getElementById('title-inspector').addEventListener('keydown', event => {
  if (event.key === 'Escape') {event.preventDefault(); closeInspector(true);}
});
document.querySelectorAll('.inspect-title').forEach(button => button.addEventListener('click', () => {
  closeInspector(false);
  const row = button.closest('[data-media-title]');
  const section = button.closest('[data-panel]');
  const stage = button.closest('[data-stage-panel]').dataset.stagePanel.split(':')[1];
  const source = row.querySelector('.media-detail-source');
  document.getElementById('inspector-title').textContent = row.dataset.mediaTitle;
  document.getElementById('inspector-library').textContent = section.dataset.panel + ' · ' + stage;
  const clock = row.querySelector('span[title]');
  document.getElementById('inspector-since').textContent = clock ? clock.textContent : 'Unknown';
  document.getElementById('inspector-explanation').replaceChildren(...Array.from(source.querySelectorAll('p')).map(p => p.cloneNode(true)));
  document.getElementById('title-inspector').classList.remove('hidden-section');
  document.getElementById('library-layout').classList.add('has-selection');
  button.setAttribute('aria-expanded', 'true');
  inspectorTrigger = button;
  document.getElementById('close-inspector').focus();
}));
document.body.classList.add('dashboard-ready');
let initialWorkspace = document.body.dataset.initialWorkspace || 'Overview';
if (initialWorkspace !== 'Review') {
  try { initialWorkspace = decodeURIComponent(location.hash.slice(1)) || initialWorkspace; } catch (_) {}
}
openSection(initialWorkspace);
document.querySelectorAll('[data-stage-tab]').forEach(tab => tab.addEventListener('click', () => {
  const section = tab.closest('[data-panel]');
  closeInspector(false);
  section.querySelectorAll('[data-stage-tab]').forEach(item => {
    const selected = item === tab;
    item.classList.toggle('selected', selected);
    item.setAttribute('aria-selected', String(selected));
  });
  section.querySelectorAll('[data-stage-panel]').forEach(panel =>
    panel.classList.toggle('hidden-section', panel.dataset.stagePanel !== tab.dataset.stageTab));
  filterLibrary();
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
let runRequestPending = false;
let runStatusPending = false;
const runButtonLabel = button?.textContent;
const runDefaultHint = document.getElementById('run-result')?.textContent;
async function refreshRunButton() {
  if (!button || runButtonLabel === 'Daily schedule only' || runStatusPending || runRequestPending) return;
  runStatusPending = true;
  try {
    const response = await fetch('/api/run-status', {credentials:'same-origin', cache:'no-store',
      signal:AbortSignal.timeout(8000)});
    if (!response.ok) throw Error('Status unavailable');
    const state = await response.json();
    if (state.ok !== true || typeof state.running !== 'boolean' || typeof state.queued !== 'boolean') throw Error('Invalid status');
    if (runRequestPending) return;
    const blocked = state.blocked === true;
    button.disabled = state.running || state.queued || blocked;
    button.textContent = state.running ? 'Scan running…' : blocked ? 'Review required' : state.queued ? 'Scan queued…' : runButtonLabel;
    if (blocked && !state.running) document.getElementById('run-result').textContent =
      'The scheduler is blocked or has an uncertain outcome. Review the retained operation and settings before another scan. The previous attempt is historical.';
    else if (state.running || state.queued) document.getElementById('run-result').textContent =
      state.running ? 'A scan is in progress. Another scan cannot start yet.' : 'A scan is queued.';
    else if (button.dataset.wasBusy === 'true') document.getElementById('run-result').textContent = runDefaultHint;
    button.dataset.wasBusy = String(state.running || state.queued || blocked);
  } catch (error) {
    // Preserve the existing disabled state until a successful observation.
  } finally { runStatusPending = false; }
}
if (button) {
  refreshRunButton();
  setInterval(refreshRunButton, 5000);
}
button?.addEventListener('click', async () => {
  const live=button.dataset.live === 'true';
  const message=live ? ('Run a live scan now? This can move ' + (button.dataset.libraryLimit === '5' ? 'up to five Movies and five TV shows (' + button.dataset.actionLimit + ' total maximum)' : button.dataset.actionLimit === '2' ? 'one Movie and one TV show' : 'one title') + '. Live scans must start at least 60 minutes apart, and another scan cannot run concurrently. Permanent deletion is disabled.') : 'Start an audit using your saved configuration? In Live Mode this may move or delete media.';
  if (button.dataset.preview !== 'true' && !confirm(message)) return;
  runRequestPending = true;
  button.disabled = true;
  const output = document.getElementById('run-result');
  output.textContent = 'Requesting audit…';
  try {
    const response = await fetch('/api/run-now', {method:'POST', credentials:'same-origin',
      ...(live ? {headers:{'Content-Type':'application/json'},body:JSON.stringify({run_live_scan:true})} : {})});
    const data = await response.json();
    output.textContent = data.message || 'Request failed.';
    if (data.next_allowed_at) output.textContent += ' Next eligible: ' + new Date(data.next_allowed_at).toLocaleString();
    if (response.status === 401) output.textContent = 'Please open Settings to sign in, then try again.';
  } catch (error) { output.textContent = 'Unable to request an audit.'; }
  finally { runRequestPending = false; await refreshRunButton(); }
});

// Overview navigation reuses the Library's existing stage and Details controls.
document.querySelectorAll('[data-open-workspace]').forEach(button =>
  button.addEventListener('click', () => openSection(button.dataset.openWorkspace)));
document.querySelectorAll('[data-open-title]').forEach(button => button.addEventListener('click', () => {
  document.getElementById('library-search').value = '';
  openSection(button.dataset.library === 'TV' ? 'TV Shows' : 'Movies');
  const section = activeLibrary();
  const stageButton = Array.from(section.querySelectorAll('[data-stage-tab]')).find(tab =>
    tab.dataset.stageTab === button.dataset.library + ':' + button.dataset.stage);
  stageButton.click();
  const row = Array.from(section.querySelectorAll('[data-media-title]')).find(item =>
    item.dataset.mediaTitle === button.dataset.openTitle && item.getClientRects().length);
  row?.querySelector('.inspect-title').click();
}));

// Paginate only the already-rendered process history; no polling or replay requests.
const historyEntries = Array.from(document.querySelectorAll('[data-history-result]'));
if (historyEntries.length) {
  const resultFilter = document.getElementById('history-filter');
  const previous = document.getElementById('history-previous');
  const next = document.getElementById('history-next');
  let historyPage = 0;
  function renderHistory() {
    const matching = historyEntries.filter(entry => resultFilter.value === 'all' || entry.dataset.historyResult === resultFilter.value);
    const pages = Math.max(1, Math.ceil(matching.length / 5));
    historyPage = Math.max(0, Math.min(historyPage, pages - 1));
    const visible = new Set(matching.slice(historyPage * 5, historyPage * 5 + 5));
    historyEntries.forEach(entry => {entry.hidden = !visible.has(entry);});
    document.getElementById('history-page-status').textContent = matching.length ?
      'Showing ' + (historyPage * 5 + 1) + '–' + Math.min(historyPage * 5 + 5, matching.length) + ' of ' + matching.length + ' attempts' : '0 matching attempts';
    document.getElementById('history-no-results').hidden = matching.length !== 0;
    previous.disabled = historyPage === 0;
    next.disabled = historyPage >= pages - 1;
  }
  resultFilter.addEventListener('change', () => {historyPage = 0; renderHistory();});
  previous.addEventListener('click', () => {historyPage--; renderHistory();});
  next.addEventListener('click', () => {historyPage++; renderHistory();});
  renderHistory();
}
