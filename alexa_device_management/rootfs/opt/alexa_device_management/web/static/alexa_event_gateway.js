(() => {
  const base = document.documentElement.dataset.ingressPath || '';

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    })[char]);
  }

  function settings() {
    const config = window.config || (window.config = {locale: 'de-DE', entities: {}});
    return config.event_gateway || (config.event_gateway = {
      enabled: false,
      endpoint: 'https://api.eu.amazonalexa.com/v3/events',
      client_id_secret: 'alexa_skill_client_id',
      client_secret_secret: 'alexa_skill_client_secret',
      fallback_web_cleanup: true,
    });
  }

  function changed() {
    document.body.dataset.configDirty = 'true';
    window.dispatchEvent(new CustomEvent('ha-export-config-changed'));
    window.dispatchEvent(new CustomEvent('ha-export-status-changed'));
  }

  function ensureUi() {
    const header = document.querySelector('body > header');
    if (header && !document.getElementById('btn-event-gateway')) {
      const button = document.createElement('button');
      button.id = 'btn-event-gateway';
      button.className = 'secondary';
      button.textContent = 'Event Gateway';
      button.addEventListener('click', openDialog);
      const discovery = document.getElementById('btn-alexa-discovery');
      header.insertBefore(button, discovery || document.getElementById('btn-restart') || null);
    }

    if (document.getElementById('event-gateway-dialog')) return;
    const dialog = document.createElement('dialog');
    dialog.id = 'event-gateway-dialog';
    dialog.innerHTML = `
      <header>
        <h1>Alexa Event Gateway</h1>
        <button class="secondary" data-close>Schließen</button>
      </header>
      <div style="padding:16px;max-height:76vh;overflow:auto">
        <div class="fields">
          <div class="field full">
            <label style="display:flex;gap:9px;align-items:center;font-size:14px">
              <input type="checkbox" data-setting="enabled" style="width:22px;height:22px">
              Offiziellen AddOrUpdateReport-/DeleteReport-Abgleich aktivieren
            </label>
          </div>
          <div class="field full">
            <label>Alexa Event Gateway-Endpunkt</label>
            <select data-setting="endpoint">
              <option value="https://api.eu.amazonalexa.com/v3/events">Europa</option>
              <option value="https://api.amazonalexa.com/v3/events">Nordamerika</option>
              <option value="https://api.fe.amazonalexa.com/v3/events">Fernost</option>
            </select>
          </div>
          <div class="field">
            <label>Secret-Name für Client-ID</label>
            <input data-setting="client_id_secret" placeholder="alexa_skill_client_id">
          </div>
          <div class="field">
            <label>Secret-Name für Client-Secret</label>
            <input data-setting="client_secret_secret" placeholder="alexa_skill_client_secret">
          </div>
          <div class="field full">
            <label style="display:flex;gap:9px;align-items:center;font-size:14px">
              <input type="checkbox" data-setting="fallback_web_cleanup" style="width:22px;height:22px">
              Bei Event-Gateway-Fehlern entfernte Geräte zusätzlich über die Alexa-Web-API bereinigen
            </label>
          </div>
        </div>
        <div class="chip" style="display:block;margin-top:14px;line-height:1.5">
          Die Zugangsdaten werden nicht in dieser App gespeichert. Trage sie unter den oben genannten Schlüsseln in
          <code>/config/secrets.yaml</code> ein. In der Alexa Developer Console muss unter Smart Home
          <strong>Send Alexa Events</strong> aktiviert sein. Danach den Skill einmal trennen und neu verknüpfen,
          damit Home Assistant den AcceptGrant erhält.
        </div>
        <div id="event-gateway-status" class="status" style="display:block;margin-top:14px">Status wird geladen…</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px">
          <button class="primary" data-sync>Jetzt synchronisieren</button>
          <button class="secondary" data-refresh>Status aktualisieren</button>
        </div>
      </div>`;
    dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
    dialog.querySelector('[data-sync]').addEventListener('click', syncNow);
    dialog.querySelector('[data-refresh]').addEventListener('click', loadStatus);
    dialog.querySelectorAll('[data-setting]').forEach(input => {
      input.classList.add('event-gateway-setting');
      const eventName = input.type === 'checkbox' || input.tagName === 'SELECT' ? 'change' : 'input';
      input.addEventListener(eventName, () => {
        const key = input.dataset.setting;
        settings()[key] = input.type === 'checkbox' ? input.checked : input.value.trim();
        changed();
        renderSettings();
      });
    });
    document.body.appendChild(dialog);
  }

  function renderSettings() {
    const cfg = settings();
    const dialog = document.getElementById('event-gateway-dialog');
    if (!dialog) return;
    dialog.querySelectorAll('[data-setting]').forEach(input => {
      const value = cfg[input.dataset.setting];
      if (input.type === 'checkbox') input.checked = Boolean(value);
      else if (document.activeElement !== input) input.value = value || '';
    });
    const syncButton = dialog.querySelector('[data-sync]');
    if (syncButton) syncButton.disabled = !cfg.enabled;
  }

  function renderStatus(result) {
    const target = document.getElementById('event-gateway-status');
    if (!target) return;
    const pendingAdd = result.pending_add_or_update?.length || 0;
    const pendingDelete = result.pending_delete?.length || 0;
    const lines = [
      `Konfiguration: ${result.enabled ? 'aktiv' : 'deaktiviert'}`,
      `Home-Assistant-Komponente: ${result.component_installed ? 'installiert' : 'noch nicht installiert'}`,
      `Dienst nach Neustart: ${result.service_available ? 'verfügbar' : 'nicht verfügbar'}`,
      `Vorgemerkt: ${pendingAdd} hinzufügen/aktualisieren, ${pendingDelete} löschen`,
    ];
    if (result.last_success_at) lines.push(`Letzter erfolgreicher Abgleich: ${new Date(result.last_success_at * 1000).toLocaleString()}`);
    if (result.last_error) lines.push(`Letzter Fehler: ${result.last_error}`);
    target.textContent = lines.join('\n');
    target.className = `status ${result.enabled && result.service_available && !result.pending ? 'ok' : 'err'}`;
    target.style.display = 'block';
  }

  async function loadStatus() {
    const target = document.getElementById('event-gateway-status');
    if (target) {
      target.textContent = 'Status wird geladen…';
      target.className = 'status';
      target.style.display = 'block';
    }
    try {
      const response = await fetch(`${base}/api/ha-export/event-sync/status`, {cache: 'no-store'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      renderStatus(result);
    } catch (error) {
      if (target) {
        target.textContent = error.message;
        target.className = 'status err';
      }
    }
  }

  async function syncNow() {
    const button = document.querySelector('#event-gateway-dialog [data-sync]');
    const oldText = button.textContent;
    button.disabled = true;
    button.textContent = 'Synchronisiere…';
    try {
      const response = await fetch(`${base}/api/ha-export/event-sync`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({force: false}),
      });
      const result = await response.json();
      renderStatus(result.status || {});
      if (!response.ok || !result.ok) {
        const fallback = result.fallback;
        const fallbackText = fallback
          ? `\nWeb-Fallback entfernt: ${(fallback.deleted_removed || []).length}`
          : '';
        throw new Error((result.official?.error || result.error || `HTTP ${response.status}`) + fallbackText);
      }
      if (typeof window.setStatus === 'function') {
        const official = result.official || {};
        window.setStatus(
          `Alexa Event Gateway-Abgleich erfolgreich.\n`
          + `Aktualisiert: ${official.add_or_update_count || 0}\n`
          + `Gelöscht: ${official.delete_count || 0}`
        );
      }
      window.dispatchEvent(new CustomEvent('ha-export-status-changed'));
    } catch (error) {
      alert(error.message);
      await loadStatus();
    } finally {
      button.disabled = !settings().enabled;
      button.textContent = oldText;
    }
  }

  function openDialog() {
    ensureUi();
    renderSettings();
    document.getElementById('event-gateway-dialog').showModal();
    loadStatus();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensureUi);
  } else {
    ensureUi();
  }
})();
