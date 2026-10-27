'use strict';
// Copy only public connection coordinates; no credentials are rendered or stored.
const base = document.getElementById('integration-base');
if (base) base.value = window.location.origin;
document.querySelectorAll('[data-copy]').forEach(button => {
  button.addEventListener('click', async () => {
    const field = document.getElementById(button.dataset.copy);
    const result = document.getElementById('integration-copy-status');
    if (!field || !result) return;
    try {
      await navigator.clipboard.writeText(field.value);
      result.textContent = 'Copied.';
    } catch (_) {
      field.focus(); field.select();
      result.textContent = 'Select and copy the highlighted address or path.';
    }
  });
});
