(() => {
  const base = document.documentElement.dataset.ingressPath || '';
  let timer = null;
  let saving = false;
  let queued = false;

  function currentConfig() {
    return window.config || null;
  }

  function mark(text, ok = true) {
    const status = document.getElementById('status');
    if (!status) return;
    status.textContent = text;
    status.className = `status ${ok ? 'ok' : 'err'}`;
  }

  async function persist() {
    const payload = currentConfig();
    if (!payload) return;
    if (saving) {
      queued = true;
      return;
    }
    saving = true;
    try {
      const response = await fetch(`${base}/api/ha-export/autosave`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
      document.body.dataset.configSavedAt = String(Date.now());
    } catch (error) {
      mark(`Autosave fehlgeschlagen: ${error.message}`, false);
    } finally {
      saving = false;
      if (queued) {
        queued = false;
        persist();
      }
    }
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(persist, 450);
  }

  document.addEventListener('change', event => {
    if (event.target.matches('.enabled, .category')) schedule();
  }, true);

  document.addEventListener('input', event => {
    if (event.target.matches('.alexaname')) schedule();
  }, true);

  document.addEventListener('click', event => {
    if (event.target.matches('.prepare, #btn-enable-visible, #btn-disable-visible, #btn-disable-technical')) {
      setTimeout(schedule, 0);
    }
  }, true);

  window.addEventListener('pagehide', () => {
    const payload = currentConfig();
    if (!payload || !navigator.sendBeacon) return;
    navigator.sendBeacon(`${base}/api/ha-export/autosave`, new Blob([JSON.stringify(payload)], {type: 'application/json'}));
  });
})();
