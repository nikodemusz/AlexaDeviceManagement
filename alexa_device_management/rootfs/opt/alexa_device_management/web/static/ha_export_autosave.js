(() => {
  const base = document.documentElement.dataset.ingressPath || '';
  let timer = null;
  let saving = false;
  let queued = false;

  function currentConfig() {
    return window.config || null;
  }

  function statusChip(text, state = '') {
    const chip = document.getElementById('autosave-state');
    if (!chip) return;
    chip.textContent = text;
    chip.className = `chip ${state}`.trim();
  }

  function mark(text, ok = true) {
    const status = document.getElementById('status');
    if (!status) return;
    status.textContent = text;
    status.className = `status ${ok ? 'ok' : 'err'}`;
  }

  async function persist() {
    const config = currentConfig();
    if (!config) return;
    if (saving) {
      queued = true;
      return;
    }

    saving = true;
    statusChip('Autosave: speichert…', 'warn');
    try {
      // Create the JSON snapshot only after the user stopped editing. This keeps
      // serialization of large configurations away from the input event itself.
      const payload = JSON.stringify(config);
      const response = await fetch(`${base}/api/ha-export/autosave`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: payload,
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
      document.body.dataset.configSavedAt = String(Date.now());
      document.body.dataset.configDirty = 'false';
      statusChip('Autosave: gespeichert', 'good');
    } catch (error) {
      statusChip('Autosave: Fehler', 'warn');
      mark(`Autosave fehlgeschlagen: ${error.message}`, false);
    } finally {
      saving = false;
      if (queued) {
        queued = false;
        schedule();
      }
    }
  }

  function schedule() {
    clearTimeout(timer);
    statusChip('Autosave: ausstehend', 'warn');
    timer = setTimeout(persist, 1000);
  }

  document.addEventListener('change', event => {
    if (event.target.matches('.enabled, .category, .group-sync-control')) schedule();
  }, true);

  document.addEventListener('input', event => {
    if (event.target.matches('.alexaname, .description, .alexagroup')) schedule();
  }, true);

  document.addEventListener('click', event => {
    if (event.target.matches('.prepare, #btn-enable-visible, #btn-disable-visible, #btn-disable-technical, #btn-copy-ha-areas')) {
      setTimeout(schedule, 0);
    }
  }, true);

  window.addEventListener('pagehide', () => {
    const payload = currentConfig();
    if (!payload || !navigator.sendBeacon || document.body.dataset.configDirty === 'false') return;
    navigator.sendBeacon(`${base}/api/ha-export/autosave`, new Blob([JSON.stringify(payload)], {type: 'application/json'}));
  });
})();
