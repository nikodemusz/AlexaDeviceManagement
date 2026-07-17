(() => {
  const base = document.documentElement.dataset.ingressPath || '';
  const button = document.getElementById('btn-save');
  if (!button) return;

  function setStatus(text, ok = true) {
    if (typeof window.setStatus === 'function') {
      window.setStatus(text, ok);
      return;
    }
    const status = document.getElementById('status');
    if (!status) return;
    status.textContent = text;
    status.className = `status ${ok ? 'ok' : 'err'}`;
  }

  function checkMessage(data) {
    return data?.check?.message || data?.message || data?.error || 'HTTP-Fehler';
  }

  async function deployCurrentConfiguration(event) {
    event?.preventDefault();

    const config = window.config;
    if (!config?.entities || !Object.values(config.entities).some(item => item?.enabled)) {
      setStatus('Es ist noch keine Entität für Alexa ausgewählt.', false);
      return;
    }

    if (!confirm('Aktuelle Konfiguration als alexa.yaml ausrollen und Home Assistant vollständig prüfen?')) return;

    const oldText = button.textContent;
    button.disabled = true;
    button.textContent = 'Rolle aus…';
    setStatus('Deployment gestartet. alexa.yaml wird geschrieben und anschließend von Home Assistant geprüft.');

    try {
      const response = await fetch(`${base}/api/ha-export/deploy`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(config),
      });

      const responseText = await response.text();
      let result;
      try {
        result = responseText ? JSON.parse(responseText) : {};
      } catch (_) {
        throw new Error(`Ungültige Serverantwort (HTTP ${response.status}): ${responseText || 'leer'}`);
      }

      if (!response.ok || !result.ok) {
        setStatus(
          `${result.error || `HTTP ${response.status}`}\n${checkMessage(result)}`
          + (result.rolled_back ? '\nRollback wurde durchgeführt.' : ''),
          false,
        );
        return;
      }

      document.body.dataset.configDirty = 'false';
      document.body.dataset.configSavedAt = String(Date.now());
      const autosave = document.getElementById('autosave-state');
      if (autosave) {
        autosave.textContent = 'Autosave: gespeichert';
        autosave.className = 'chip good';
      }

      setStatus(
        `Konfiguration erfolgreich ausgerollt.\nDatei: ${result.path}`
        + `\nBackup: ${result.backup || 'keines'}`
        + `\nEntitäten: ${result.selected ?? result.selected_count ?? 0}`
        + `\nPrüfung: ${checkMessage(result)}`,
      );
      document.getElementById('btn-restart')?.classList.remove('hidden');
      window.dispatchEvent(new CustomEvent('ha-export-status-changed'));
    } catch (error) {
      setStatus(`Deployment fehlgeschlagen: ${error.message}`, false);
    } finally {
      button.disabled = false;
      button.textContent = oldText;
    }
  }

  // The page's original handler sends no request body. Replace it completely so
  // deployment always receives the current editor state and always reports progress.
  button.onclick = deployCurrentConfiguration;
})();