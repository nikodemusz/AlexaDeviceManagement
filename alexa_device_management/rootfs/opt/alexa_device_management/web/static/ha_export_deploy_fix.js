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

  function cleanupMessage(cleanup) {
    if (!cleanup) return '';
    const removed = cleanup.deleted_removed?.length || 0;
    const duplicates = cleanup.deleted_duplicates?.length || 0;
    const failed = cleanup.failed?.length || 0;
    const missing = cleanup.not_found?.length || 0;
    const warnings = cleanup.warnings?.filter(Boolean) || [];
    return `\nAlexa entfernt: ${removed}`
      + `\nNicht erreichbare Duplikate entfernt: ${duplicates}`
      + (missing ? `\nIn Alexa nicht gefunden: ${missing}` : '')
      + (failed ? `\nAlexa-Löschfehler: ${failed}` : '')
      + (warnings.length ? `\nHinweise: ${warnings.join(' | ')}` : '');
  }

  async function deployCurrentConfiguration(event) {
    event?.preventDefault();

    const config = window.config;
    if (!config?.entities) {
      setStatus('Die aktuelle Konfiguration konnte nicht gelesen werden.', false);
      return;
    }

    const selected = Object.values(config.entities).filter(item => item?.enabled).length;
    const question = selected
      ? 'Aktuelle Konfiguration als alexa.yaml ausrollen, Alexa-Abwahlen synchronisieren und Home Assistant vollständig prüfen?'
      : 'Alle Home-Assistant-Geräte für Alexa deaktivieren und vorhandene Zuordnungen aus Alexa entfernen?';
    if (!confirm(question)) return;

    const oldText = button.textContent;
    button.disabled = true;
    button.textContent = 'Rolle aus…';
    setStatus('Deployment gestartet. alexa.yaml wird geschrieben, Alexa wird bereinigt und Home Assistant anschließend geprüft.');

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
        + cleanupMessage(result.alexa_cleanup)
        + `\nPrüfung: ${checkMessage(result)}`,
        !(result.alexa_cleanup?.failed?.length),
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

  button.onclick = deployCurrentConfiguration;
})();