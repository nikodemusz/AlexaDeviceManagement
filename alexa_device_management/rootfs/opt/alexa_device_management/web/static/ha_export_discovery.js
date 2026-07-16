(() => {
  const base = document.documentElement.dataset.ingressPath || '';

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    })[char]);
  }

  function ensureUi() {
    const header = document.querySelector('body > header');
    if (header && !document.getElementById('btn-discovery-preview')) {
      const button = document.createElement('button');
      button.id = 'btn-discovery-preview';
      button.className = 'secondary';
      button.textContent = 'Discovery-Vorschau';
      const yamlButton = document.getElementById('btn-preview');
      header.insertBefore(button, yamlButton || null);
      button.addEventListener('click', openPreview);
    }

    if (!document.getElementById('discovery-dialog')) {
      const dialog = document.createElement('dialog');
      dialog.id = 'discovery-dialog';
      dialog.innerHTML = `
        <header>
          <h1>Alexa Discovery-Vorschau</h1>
          <button class="secondary" data-close-discovery>Schließen</button>
        </header>
        <div class="discovery-content" style="padding:16px;max-height:75vh;overflow:auto"></div>`;
      document.body.appendChild(dialog);
      dialog.querySelector('[data-close-discovery]').addEventListener('click', () => dialog.close());
    }
  }

  function countCards(title, values) {
    const entries = Object.entries(values || {});
    if (!entries.length) return '';
    return `<section><h3>${escapeHtml(title)}</h3><div class="summary">${entries.map(([key, value]) =>
      `<div class="chip"><strong>${escapeHtml(value)}</strong> ${escapeHtml(key)}</div>`
    ).join('')}</div></section>`;
  }

  function render(result) {
    const content = document.querySelector('#discovery-dialog .discovery-content');
    const statusClass = result.ok ? 'good' : 'warn';
    const warnings = (result.warnings || []).map(item => `
      <div class="chip ${item.severity === 'error' ? 'warn' : ''}" style="display:block;margin-bottom:8px">
        <strong>${item.severity === 'error' ? 'Fehler' : 'Hinweis'}:</strong>
        ${escapeHtml(item.message)}
        ${item.entity_id ? `<div class="entity-id">${escapeHtml(item.entity_id)}</div>` : ''}
      </div>`).join('');

    const endpoints = (result.endpoints || []).map(endpoint => `
      <tr>
        <td>${escapeHtml(endpoint.name)}</td>
        <td><span class="badge">${escapeHtml(endpoint.category)}</span></td>
        <td>${escapeHtml(endpoint.area)}</td>
        <td class="entity-id">${escapeHtml(endpoint.entity_id)}</td>
      </tr>`).join('');

    content.innerHTML = `
      <div class="summary">
        <div class="chip ${statusClass}"><strong>${escapeHtml(result.endpoint_count || 0)}</strong> Alexa-Endpunkte</div>
        <div class="chip ${result.error_count ? 'warn' : 'good'}"><strong>${escapeHtml(result.error_count || 0)}</strong> Fehler</div>
        <div class="chip ${result.warning_count ? 'warn' : 'good'}"><strong>${escapeHtml(result.warning_count || 0)}</strong> Hinweise</div>
        <div class="chip"><strong>${escapeHtml((result.duplicate_names || []).length)}</strong> doppelte Namen</div>
      </div>
      ${countCards('Kategorien', result.category_counts)}
      ${countCards('Bereiche', result.area_counts)}
      ${warnings ? `<section><h3>Prüfergebnisse</h3>${warnings}</section>` : '<div class="chip good">Keine Discovery-Probleme erkannt.</div>'}
      <section>
        <h3>Alexa würde folgende Endpunkte erhalten</h3>
        <div style="overflow:auto">
          <table style="width:100%;border-collapse:collapse">
            <thead><tr><th>Name</th><th>Kategorie</th><th>Bereich</th><th>Entity-ID</th></tr></thead>
            <tbody>${endpoints || '<tr><td colspan="4">Keine Entitäten ausgewählt.</td></tr>'}</tbody>
          </table>
        </div>
      </section>`;
  }

  async function openPreview() {
    ensureUi();
    const button = document.getElementById('btn-discovery-preview');
    const dialog = document.getElementById('discovery-dialog');
    const content = dialog.querySelector('.discovery-content');
    button.disabled = true;
    content.textContent = 'Discovery-Vorschau wird berechnet…';
    dialog.showModal();
    try {
      const response = await fetch(`${base}/api/ha-export/discovery-preview`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          configuration: window.config || {},
          devices: (window.inventory || {}).devices || [],
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      render(result);
    } catch (error) {
      content.innerHTML = `<div class="chip warn">Discovery-Vorschau fehlgeschlagen: ${escapeHtml(error.message)}</div>`;
    } finally {
      button.disabled = false;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensureUi);
  } else {
    ensureUi();
  }
})();
