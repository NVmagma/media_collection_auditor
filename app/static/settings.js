"use strict";
const tabs = document.querySelectorAll('[data-tab]');
const panels = document.querySelectorAll('[data-panel]');
function showTab(name) {
  tabs.forEach(tab => { const active = tab.dataset.tab === name; tab.classList.toggle('selected', active); tab.setAttribute('aria-pressed', String(active)); });
  panels.forEach(panel => panel.classList.toggle('hidden-section', panel.dataset.panel !== name));
}
tabs.forEach(tab => tab.addEventListener('click', () => showTab(tab.dataset.tab)));
document.querySelectorAll('[data-test-service]').forEach(button => {
  button.addEventListener('click', async () => {
    const service = button.dataset.testService;
    const result = document.querySelector('[data-test-result="' + service + '"]');
    button.disabled = true;
    result.textContent = 'Testing…';
    result.className = 'test-result';
    try {
      const response = await fetch('/api/test-connection/' + service, {
        method: 'POST',
        headers: {'Accept': 'application/json'},
        credentials: 'same-origin'
      });
      const data = await response.json();
      result.textContent = data.message || 'Unable to complete test.';
      result.classList.add(data.ok ? 'test-success' : 'test-failure');
    } catch (error) {
      result.textContent = 'Request failed. Please try again.';
      result.classList.add('test-failure');
    } finally {
      button.disabled = false;
    }
  });
});

// Draft indicators remain local; no values are copied to status text or storage.
const editor = document.getElementById('settings-form');
const draftStatus = document.getElementById('settings-draft-status');
if (editor && draftStatus) {
  const fields = Array.from(editor.querySelectorAll('[id^="field-"]'));
  const initial = new Map(fields.map(field => [field, field.value]));
  function updateDraft() {
    const paused = editor.querySelector('fieldset').disabled;
    let changed = 0;
    fields.forEach(field => {
      const dirty = field.value !== initial.get(field);
      field.closest('.setting-row').classList.toggle('draft-changed', dirty);
      if (dirty) changed++;
    });
    draftStatus.textContent = paused ? 'Editing paused until previous settings are restored.' : changed ?
      changed + (changed === 1 ? ' unsaved field edit' : ' unsaved field edits') + (editor.dataset.preview === 'true' ? ' · choose Apply Requested Settings to submit' : ' · not saved yet') : 'No unsaved field edits';
  }
  fields.forEach(field => {
    field.addEventListener('input', updateDraft);
    field.addEventListener('change', updateDraft);
  });
  updateDraft();
}

// A visible, unchecked acknowledgement is required for every apply with deletion on.
const deletionSwitch = document.getElementById('field-ALLOW_PERMANENT_DELETE');
const deletionWarning = document.getElementById('removal-deletion-warning');
const deletionAck = document.getElementById('acknowledge-removal-deletion');
if (deletionSwitch && deletionWarning && deletionAck) {
  function updateDeletionWarning() {
    const on = deletionSwitch.value === 'true';
    deletionWarning.hidden = !on;
    deletionAck.required = on;
    if (!on) deletionAck.checked = false;
  }
  deletionSwitch.addEventListener('change', () => { deletionAck.checked = false; updateDeletionWarning(); });
  editor.addEventListener('submit', event => {
    if (deletionSwitch.value === 'true' && !deletionAck.checked) {
      event.preventDefault(); showTab('Safety'); deletionAck.focus();
    }
  });
  editor.addEventListener('invalid', event => {
    if (event.target === deletionAck) { showTab('Safety'); deletionAck.focus(); }
  }, true);
  updateDeletionWarning();
}

const orphanSwitch = document.getElementById('field-ORPHAN_CLEANUP_ENABLED');
const orphanWarning = document.getElementById('orphan-quarantine-warning');
const orphanAck = document.getElementById('acknowledge-orphan-quarantine');
if (editor && orphanSwitch && orphanWarning && orphanAck) {
  function updateOrphanWarning() {
    const on = orphanSwitch.value === 'true';
    orphanWarning.hidden = !on; orphanAck.required = on;
    if (!on) orphanAck.checked = false;
  }
  orphanSwitch.addEventListener('change', () => { orphanAck.checked = false; updateOrphanWarning(); });
  editor.addEventListener('submit', event => {
    if (orphanSwitch.value === 'true' && !orphanAck.checked) {
      event.preventDefault(); showTab('Safety'); orphanAck.focus();
    }
  });
  editor.addEventListener('invalid', event => {
    if (event.target === orphanAck) { showTab('Safety'); orphanAck.focus(); }
  }, true);
  updateOrphanWarning();
}
