(() => {
  const base = document.documentElement.dataset.ingressPath || '';

  function ensureUi() {
    const header = document.querySelector('body > header');
    if (!header || document.getElementById('btn-consistency')) return;
    const button = document.createElement('button');
    button.id = 'btn-consistency';
    button.className = 'secondary';
    button.textContent = 'Konsistenz prüfen';
    button.addEventListener('click', runCheck);
    const preview = document.getElementById('btn-preview');
    header.insertBefore(button, preview || null);

    const dialog = document.createElement('dialog');
    dialog.id = 'consistency-dialog';
    dialog.innerHTML = `
      <header><h1>Konsistenzprüfung</h1><button class="secondary" data-close>Schließen</button></header>
      <div style="padding:16px;max-height:70vh;overflow:auto">
        <div id="consistency-summary" class="summary"></div>
        <div id="consistency-findings"></div>
      </div>`;
    dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
    document.body.appendChild(dialog);
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    })[char]);
  }

  function render(result) {
    const summary = document.getElementById('consistency-summary');
    const findings = document.getElementById('consistency-findings');
    summary.innerHTML = `
      <div class="chip ${result.ok ? 'good' : 'warn'}">Status: ${result.ok ? 'in Ordnung' : 'Handlungsbedarf'}</div>
      <div class="chip">${result.errors || 0} Fehler</div>
      <div class="chip">${result.warnings || 0} Warnungen</div>
      <div class="chip">${result.selected_count || 0} ausgewählt</div>
      <div class="chip">${result.deployed_count || 0} ausgerollt</div>`;

    if (!result.findings?.length) {
      findings.innerHTML = '<div class="status ok" style="display:block">Keine Inkonsistenzen gefunden.</div>';
      return;
    }
    findings.innerHTML = result.findings.map(item => `
      <article class="entity-card ${item.severity === 'error' ? 'selected' : ''}" style="margin-bottom:10px">
        <div class="entity-top"><div class="entity-title">
          <strong>${item.severity === 'error' ? 'Fehler' : 'Warnung'}: ${esc(item.message)}</strong>
          <div class="entity-id">${esc(item.code)}</div>
        </div></div>
        ${item.entity_id ? `<div class="entity-id">${esc(item.entity_id)}</div>` : ''}
        ${item.entities?.length ? `<div class="entity-id">${item.entities.map(esc).join('<br>')}</div>` : ''}
        ${item.repair ? `<div class="capability"><strong>Vorschlag:</strong> ${esc(item.repair)}</div>` : ''}
      </article>`).join('');
  }

  async function runCheck() {
    const button = document.getElementById('btn-consistency');
    const dialog = document.getElementById('consistency-dialog');
    const old = button.textContent;
    button.disabled = true;
    button.textContent = 'Prüfe…';
    try {
      const response = await fetch(`${base}/api/ha-export/consistency-check`, {method: 'POST'});
      const result = await response.json();
      if (response.status >= 500) throw new Error(result.error || `HTTP ${response.status}`);
      render(result);
      dialog.showModal();
    } catch (error) {
      if (typeof window.setStatus === 'function') window.setStatus(`Konsistenzprüfung fehlgeschlagen: ${error.message}`, false);
      else alert(error.message);
    } finally {
      button.disabled = false;
      button.textContent = old;
    }
  }

  ensureUi();
})();
