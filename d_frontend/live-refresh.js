(() => {
  const controls = document.querySelector('#live-refresh-controls');
  const button = document.querySelector('#live-refresh');
  const message = document.querySelector('#live-refresh-status');
  if (!controls || !button || !message) return;

  async function status() {
    const response = await fetch('/live/status', { cache: 'no-store' });
    if (!response.ok) throw new Error('Cannot reach the live service.');
    return response.json();
  }

  status().then(state => { controls.hidden = state.state === 'disabled'; }).catch(() => {});
  button.addEventListener('click', async () => {
    button.disabled = true;
    button.textContent = 'Refreshing…';
    message.textContent = 'Fetching weather and fire detections, then updating predictions…';
    try {
      const before = await status();
      const response = await fetch('/live/refresh', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
      });
      const result = await response.json();
      if (!response.ok && response.status !== 409) throw new Error(result.error || 'Refresh request failed.');
      if (response.status === 409) message.textContent = result.error;
      const deadline = Date.now() + 10 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        const state = await status();
        if (state.state === 'error' && state.failed_at !== before.failed_at) {
          throw new Error(state.error || 'Refresh failed; the last successful snapshot is retained.');
        }
        if (state.state === 'ready' && state.completed_at !== before.completed_at) {
          window.dispatchEvent(new Event('refresh-dashboard'));
          message.textContent = 'Live data updated. Automatic updates still start at each hour.';
          return;
        }
      }
      message.textContent = 'Refresh is taking longer than expected. The dashboard will continue checking for updates.';
    } catch (error) {
      message.textContent = error.message;
    } finally {
      button.disabled = false;
      button.textContent = 'Refresh live data';
    }
  });
})();
