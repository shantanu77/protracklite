(() => {
  const form = document.querySelector('[data-capacity-sync-form]');
  if (!form) return;
  const button = form.querySelector('[data-capacity-sync-button]');
  const message = document.querySelector('[data-capacity-sync-message]');
  const statusUrl = `${form.action.replace(/\/sync$/, '')}/sync-status`;
  let polling = false;
  function show(text, error = false) {
    message.textContent = text;
    message.hidden = !text;
    message.classList.toggle('is-error', error);
  }
  async function poll() {
    if (polling) return;
    polling = true;
    try {
      for (;;) {
        const response = await fetch(statusUrl, { headers: { Accept: 'application/json' }, cache: 'no-store' });
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Unable to check sync status. Reload to see the saved view and current sync status.');
        const data = await response.json();
        if (data.status === 'done') { window.location.reload(); return; }
        if (data.status !== 'running') {
          show(data.error || 'The sync did not finish. The last saved snapshot is unchanged.', true);
          return;
        }
        show('Syncing leave for the organization… The last saved view stays available.');
        await new Promise(resolve => setTimeout(resolve, 3000));
      }
    } catch (error) {
      show(error.message || 'Unable to check the sync. Reload to check progress.', true);
    } finally {
      polling = false;
      button.disabled = false;
      button.textContent = 'Sync with Zoho';
    }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = 'Syncing…';
    show('Starting organization sync…');
    try {
      const response = await fetch(form.action, { method: 'POST', body: new FormData(form), headers: { Accept: 'application/json' } });
      const data = await response.json().catch(() => ({}));
      if (response.status === 409) { await poll(); return; }
      if (!response.ok) throw new Error(data.detail || 'Unable to start sync. The saved snapshot is unchanged.');
      await poll();
    } catch (error) {
      show(error.message || 'Unable to start sync. Reload to check progress.', true);
    } finally {
      button.disabled = false;
      button.textContent = 'Sync with Zoho';
    }
  });
  if (button.disabled) poll();
})();
