'use strict';
const el = id => document.getElementById(id);
const csrf = el('main-content').dataset.importCsrf;
let reviewFingerprint = null, recoveryFingerprint = null, busy = false;
function invalidate() {
  reviewFingerprint = null;
  el('import-apply').disabled = true;
  el('import-summary').hidden = true;
}
for (const id of ['import-library','import-folder','import-match','import-profile','import-search']) {
  el(id).addEventListener('input', invalidate);
}
el('import-library').addEventListener('change', () => {
  el('import-folder').value = '';
  el('import-folders').replaceChildren();
  el('import-profile').replaceChildren(new Option('Choose a profile',''));
  el('import-match').replaceChildren(new Option('Choose a match',''));
});
async function request(path, data) {
  const response = await fetch(path, {credentials:'same-origin', cache:'no-store',
    ...(data ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf,...data})} : {})});
  const result = await response.json();
  if (!response.ok || result.ok !== true) throw Error(result.message || 'Request unavailable.');
  return result;
}
async function action(fn) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('#main-content button, #main-content input, #main-content select').forEach(control => control.disabled = true);
  el('import-status').textContent = 'Working…';
  try { await fn(); }
  catch (error) { el('import-status').textContent = error.message || 'Request unavailable. No automatic retry.'; }
  finally {
    busy = false;
    document.querySelectorAll('#main-content button, #main-content input, #main-content select').forEach(control => control.disabled = false);
    el('import-apply').disabled = !reviewFingerprint;
    el('import-recovery-apply').disabled = !recoveryFingerprint;
  }
}
el('import-load').addEventListener('click', () => action(async () => {
  invalidate();
  const result = await request('/api/arr-import/options?library=' + encodeURIComponent(el('import-library').value));
  el('import-folders').replaceChildren(...result.folders.map(name => new Option(
    name + (result.folder_stages?.[name] ? ' · ' + result.folder_stages[name] : ''),name)));
  el('import-profile').replaceChildren(new Option('Choose a profile',''),
    ...result.quality_profiles.map(profile => new Option(profile.name,String(profile.id))));
  el('import-folder-hint').textContent = result.folders_truncated ?
    'Showing the first 1,000 folders. You can enter any exact configured library folder name.' : 'Choose or enter an exact library folder name. Its current stage will be preserved.';
  el('import-status').textContent = 'Folders and profiles loaded. Select a provider match before reviewing.';
}));
el('import-find').addEventListener('click', () => action(async () => {
  invalidate();
  const result = await request('/api/arr-import/lookup?library=' + encodeURIComponent(el('import-library').value) + '&term=' + encodeURIComponent(el('import-search').value));
  const provider = el('import-library').value === 'TV' ? 'TVDB' : 'TMDB';
  el('import-match').replaceChildren(new Option('Choose a match',''), ...result.matches.map(match =>
    new Option(match.title + (match.year ? ' (' + match.year + ')' : '') + ' · ' + provider + ' ' + match.provider_id,String(match.provider_id))));
  el('import-status').textContent = result.truncated ? 'Showing the first 20 matches. Refine your search if needed.' : 'Choose the correct provider match.';
}));
el('import-review').addEventListener('click', () => action(async () => {
  invalidate();
  const result = await request('/api/arr-import/review', {library:el('import-library').value,
    folder:el('import-folder').value,provider_id:Number(el('import-match').value),quality_profile_id:Number(el('import-profile').value)});
  reviewFingerprint = result.review_fingerprint;
  el('import-description').textContent = result.title + ' (' + result.year + ') · ' + (result.service === 'sonarr' ? 'Sonarr' : 'Radarr') + ' · ' + result.media_files + ' existing media files';
  el('import-path').textContent = 'Current stage: ' + result.stage + ' · Existing path: ' + result.path;
  el('import-quality').textContent = 'Quality profile: ' + result.quality_profile;
  el('import-summary').hidden = false;
  el('import-status').textContent = 'Review ready for 10 minutes. No import has been performed.';
}));
el('import-apply').addEventListener('click', () => action(async () => {
  const fingerprint = reviewFingerprint;
  invalidate();
  await request('/api/arr-import/apply', {review_fingerprint:fingerprint});
  el('import-status').textContent = 'Arr registration verified. Arr may still be scanning existing files. Monitoring is off, no download search was requested, and lifecycle clocks were preserved.';
}));
el('import-recovery-review').addEventListener('click', () => action(async () => {
  recoveryFingerprint = null;
  const result = await request('/api/arr-import/recovery-review', {});
  recoveryFingerprint = result.review_fingerprint;
  el('import-status').textContent = 'The pending import matches fresh Arr reads. You can acknowledge it; no creation request was sent.';
}));
el('import-recovery-apply').addEventListener('click', () => action(async () => {
  const fingerprint = recoveryFingerprint; recoveryFingerprint = null;
  await request('/api/arr-import/recovery-apply', {review_fingerprint:fingerprint});
  el('import-status').textContent = 'Pending import acknowledged. No creation request was repeated.';
}));
