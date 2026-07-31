(() => {
  const base = document.documentElement.dataset.ingressPath || '';
  let refreshInFlight = false;

  function ensureUi() {
    const summary = document.querySelector('.summary');
    if (summary && !document.getElementById('lifecycle-state')) {
      const chip = document.createElement('div');
      chip.id = 'lifecycle-state';
      chip.className = 'chip';
      chip.textContent = 'Ablaufstatus wird geladen…';
      summary.appendChild(chip);
    }

    const header = document.querySelector('body > header');
    if (!header || document.getElementById('btn-alexa-discovery')) return;
    const button = document.createElement('button');
    button.id = 'btn-alexa-discovery';
    button.className = 'secondary';
    button.textContent = 'Alexa-Gerätesuche';
    button.addEventListener('click', showGuide);
    const restart = document.getElementById('btn-restart');
    header.insertBefore(button, restart || null);

    const dialog = document.createElement('dialog');
    dialog.id = 'discovery-guide-dialog';
    dialog.innerHTML = `
      <header><h1>Alexa-Gerätesuche</h1><button class="secondary" data-close>Schließen</button></header>
      <div style="padding:16px;max-height:70vh;overflow:auto">
        <div id="discovery-guide-content">Lade Anleitung…</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px">
          <button class="primary" data-confirm>Gerätesuche erledigt</button>
        </div>
      </div>`;
    dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
    dialog.querySelector('[data-confirm]').addEventListener('click', markComplete);
    document.body.appendChild(dialog);
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    })[char]);
  }

  function renderStatus(status) {
    const chip = document.getElementById('lifecycle-state');
    if (!chip) return;
    chip.className = 'chip';
    if (status.changes_pending) {
      chip.textContent = 'Änderungen noch nicht ausgerollt';
      chip.classList.add('warn');
    } else if (status.restart_required) {
      chip.textContent = 'Home Assistant muss neu gestartet werden';
      chip.classList.add('warn');
    } else if (status.event_sync_pending) {
      const adds = status.event_sync?.pending_add_or_update?.length || 0;
      const deletes = status.event_sync?.pending_delete?.length || 0;
      chip.textContent = `Alexa Event Gateway ausstehend: ${adds} aktualisieren, ${deletes} löschen`;
      chip.classList.add('warn');
    } else if (status.discovery_pending) {
      chip.textContent = 'Alexa-Gerätesuche steht noch aus';
      chip.classList.add('warn');
    } else if (status.deploy_state === 'success') {
      chip.textContent = status.event_sync?.enabled
        ? 'Deployment, Neustart und Alexa-Abgleich aktuell'
        : 'Deployment, Neustart und Gerätesuche aktuell';
      chip.classList.add('good');
    } else {
      chip.textContent = 'Noch kein vollständiger Deployment-Ablauf';
    }

    const discovery = document.getElementById('btn-alexa-discovery');
    if (discovery) discovery.textContent = status.event_sync?.enabled ? 'Manuelle Gerätesuche' : 'Alexa-Gerätesuche';
    const restart = document.getElementById('btn-restart');
    if (restart && status.restart_required) restart.classList.remove('hidden');
  }

  async function refreshStatus() {
    if (refreshInFlight || document.hidden) return;
    refreshInFlight = true;
    try {
      const response = await fetch(`${base}/api/ha-export/lifecycle-status`, {cache: 'no-store'});
      if (!response.ok) return;
      renderStatus(await response.json());
    } catch (_) {
    } finally {
      refreshInFlight = false;
    }
  }

  async function showGuide() {
    const dialog = document.getElementById('discovery-guide-dialog');
    const content = document.getElementById('discovery-guide-content');
    dialog.showModal();
    try {
      const response = await fetch(`${base}/api/ha-export/discovery-guide`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      const eventSync = result.lifecycle?.event_sync;
      const official = eventSync?.enabled
        ? `<div class="status ok" style="display:block">Der offizielle Event-Gateway-Abgleich ist aktiviert. Verwende nach dem Neustart zuerst den Button <strong>Event Gateway</strong>. Die manuelle Gerätesuche ist nur noch ein Fallback.</div>`
        : '';
      content.innerHTML = `
        ${official}
        <div class="status ${result.lifecycle?.discovery_pending ? 'err' : 'ok'}" style="display:block">
          ${result.lifecycle?.discovery_pending ? 'Die Gerätesuche ist nach dem letzten Neustart noch offen.' : 'Keine offene manuelle Gerätesuche gespeichert.'}
        </div>
        <p>${esc(result.reason)}</p>
        <ol>${(result.steps || []).map(step => `<li style="margin-bottom:8px">${esc(step)}</li>`).join('')}</ol>
        <div class="chip"><strong>Sprachbefehl:</strong> ${esc(result.voice_command)}</div>`;
    } catch (error) {
      content.innerHTML = `<div class="status err" style="display:block">${esc(error.message)}</div>`;
    }
  }

  async function markComplete() {
    const button = document.querySelector('#discovery-guide-dialog [data-confirm]');
    button.disabled = true;
    try {
      const response = await fetch(`${base}/api/ha-export/discovery-complete`, {method: 'POST'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      renderStatus(result);
      document.getElementById('discovery-guide-dialog').close();
      if (typeof window.setStatus === 'function') window.setStatus('Alexa-Gerätesuche als erledigt markiert.');
    } catch (error) {
      alert(error.message);
    } finally {
      button.disabled = false;
    }
  }

  ensureUi();
  refreshStatus();
  window.addEventListener('focus', refreshStatus);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refreshStatus();
  });
  window.addEventListener('ha-export-status-changed', refreshStatus);
  setInterval(refreshStatus, 60000);
})();
