(() => {
  const base = document.documentElement.dataset.ingressPath || '';
  let observerBusy = false;

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    })[char]);
  }

  function config() {
    return window.config || null;
  }

  function groupSettings() {
    const current = config();
    if (!current) return null;
    return current.group_sync ||= {
      enabled: true,
      create_missing: true,
      remove_from_other_groups: false,
    };
  }

  function entityConfig(entityId) {
    const current = config();
    if (!current) return null;
    current.entities ||= {};
    return current.entities[entityId] ||= {
      enabled: false,
      name: '',
      description: '',
      display_category: '',
      alexa_group: '',
    };
  }

  function deviceForEntity(entityId) {
    return ((window.inventory || {}).devices || []).find(device =>
      (device.entities || []).some(entity => entity.entity_id === entityId)
    );
  }

  function dispatchConfigChange(element, eventName = 'input') {
    document.body.dataset.configDirty = 'true';
    element.dispatchEvent(new Event(eventName, {bubbles: true}));
  }

  function ensureHaControls() {
    if (!document.querySelector('.bulkbar') || document.getElementById('alexa-group-sync-controls')) return;
    const settings = groupSettings();
    if (!settings) return;

    const panel = document.createElement('div');
    panel.id = 'alexa-group-sync-controls';
    panel.className = 'chip';
    panel.style.cssText = 'display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px';
    panel.innerHTML = `
      <strong>Alexa-Gruppen</strong>
      <label style="display:flex;gap:6px;align-items:center;margin:0;font-weight:500">
        <input id="group-auto-area" class="group-sync-control" type="checkbox" style="width:auto" ${settings.enabled !== false ? 'checked' : ''}>
        HA-Bereich automatisch übernehmen
      </label>
      <label style="display:flex;gap:6px;align-items:center;margin:0;font-weight:500">
        <input id="group-create-missing" class="group-sync-control" type="checkbox" style="width:auto" ${settings.create_missing !== false ? 'checked' : ''}>
        Fehlende Gruppen erstellen
      </label>
      <label style="display:flex;gap:6px;align-items:center;margin:0;font-weight:500">
        <input id="group-remove-other" class="group-sync-control" type="checkbox" style="width:auto" ${settings.remove_from_other_groups ? 'checked' : ''}>
        Aus anderen Gruppen entfernen
      </label>
      <button class="secondary" id="btn-copy-ha-areas">HA-Bereiche übernehmen</button>
      <button class="primary" id="btn-sync-alexa-groups">Mit Alexa synchronisieren</button>
      <button class="secondary" id="btn-open-alexa-groups">Gruppen verwalten</button>`;
    document.querySelector('.bulkbar').insertAdjacentElement('afterend', panel);

    panel.querySelector('#group-auto-area').addEventListener('change', event => {
      settings.enabled = event.target.checked;
      dispatchConfigChange(event.target, 'change');
    });
    panel.querySelector('#group-create-missing').addEventListener('change', event => {
      settings.create_missing = event.target.checked;
      dispatchConfigChange(event.target, 'change');
    });
    panel.querySelector('#group-remove-other').addEventListener('change', event => {
      settings.remove_from_other_groups = event.target.checked;
      dispatchConfigChange(event.target, 'change');
    });
    panel.querySelector('#btn-copy-ha-areas').addEventListener('click', copyAreas);
    panel.querySelector('#btn-sync-alexa-groups').addEventListener('click', syncGroups);
    panel.querySelector('#btn-open-alexa-groups').addEventListener('click', openManager);
  }

  function ensureEntityFields() {
    if (observerBusy || !config()) return;
    observerBusy = true;
    try {
      document.querySelectorAll('.entity-card').forEach(card => {
        if (card.querySelector('.alexagroup')) return;
        const enabled = card.querySelector('.enabled[data-id]');
        const fields = card.querySelector('.fields');
        if (!enabled || !fields) return;
        const entityId = enabled.dataset.id;
        const current = entityConfig(entityId);
        const area = deviceForEntity(entityId)?.area_name || '';
        const wrapper = document.createElement('div');
        wrapper.className = 'field';
        wrapper.innerHTML = `
          <label>Alexa-Gruppe</label>
          <input class="alexagroup" data-id="${escapeHtml(entityId)}"
            value="${escapeHtml(current.alexa_group || '')}"
            placeholder="${escapeHtml(area || 'Optionaler Alexa-Raum')}">`;
        const description = fields.querySelector('.field.full');
        fields.insertBefore(wrapper, description || null);
        wrapper.querySelector('input').addEventListener('input', event => {
          entityConfig(entityId).alexa_group = event.target.value;
          document.getElementById('btn-restart')?.classList.add('hidden');
        });
      });
    } finally {
      observerBusy = false;
    }
  }

  function applyAreaDefaults() {
    if (groupSettings()?.enabled === false) return 0;
    let changed = 0;
    for (const device of (window.inventory || {}).devices || []) {
      const area = String(device.area_name || '').trim();
      if (!area) continue;
      for (const entity of device.entities || []) {
        const current = entityConfig(entity.entity_id);
        if (!current?.enabled || String(current.alexa_group || '').trim()) continue;
        current.alexa_group = area;
        changed += 1;
      }
    }
    return changed;
  }

  function copyAreas() {
    let changed = 0;
    for (const device of (window.inventory || {}).devices || []) {
      const area = String(device.area_name || '').trim();
      if (!area) continue;
      for (const entity of device.entities || []) {
        const current = entityConfig(entity.entity_id);
        if (!current?.enabled || current.alexa_group === area) continue;
        current.alexa_group = area;
        changed += 1;
      }
    }
    window.render?.();
    ensureEntityFields();
    const button = document.getElementById('btn-copy-ha-areas');
    if (button) dispatchConfigChange(button, 'change');
    window.setStatus?.(`${changed} aktivierte Entitäten haben ihren HA-Bereich als Alexa-Gruppe erhalten.`);
  }

  async function syncGroups() {
    const button = document.getElementById('btn-sync-alexa-groups');
    if (!button) return;
    const settings = groupSettings();
    button.disabled = true;
    const oldText = button.textContent;
    button.textContent = 'Synchronisiere…';
    try {
      const response = await fetch(`${base}/api/ha-export/group-sync`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          configuration: config(),
          create_missing: settings.create_missing !== false,
          remove_from_other_groups: Boolean(settings.remove_from_other_groups),
        }),
      });
      const result = await response.json();
      const failures = (result.results || []).filter(item => !item.ok);
      const details = failures.slice(0, 8).map(item => `${item.entity_id}: ${item.error}`).join('\n');
      if (!response.ok && response.status !== 207) throw new Error(result.error || details || `HTTP ${response.status}`);
      const message = `${result.successful || 0}/${result.total || 0} Gruppenzuordnungen bestätigt, ${result.changed || 0} geändert.` +
        (failures.length ? `\n${details}` : '');
      window.setStatus?.(message, failures.length === 0);
    } catch (error) {
      window.setStatus?.(`Alexa-Gruppensynchronisierung fehlgeschlagen: ${error.message}`, false);
    } finally {
      button.disabled = false;
      button.textContent = oldText;
    }
  }

  function ensureDialog() {
    let dialog = document.getElementById('alexa-group-dialog');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'alexa-group-dialog';
    dialog.style.cssText = 'width:min(1100px,96vw);border:0;border-radius:12px;padding:0';
    dialog.innerHTML = `
      <header><h1>Alexa-Gruppen verwalten</h1><button class="secondary" data-close>Schließen</button></header>
      <div data-content style="padding:16px;max-height:78vh;overflow:auto">Lade Gruppen…</div>`;
    document.body.appendChild(dialog);
    dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
    return dialog;
  }

  function renderManager(dialog, result) {
    const groups = result.groups || [];
    const devices = result.devices || [];
    const options = groups.map(group => `<option value="${escapeHtml(group.name)}">${escapeHtml(group.name)}</option>`).join('');
    const groupCards = groups.map(group => `
      <section class="device" style="padding:12px">
        <strong>${escapeHtml(group.name)}</strong>
        <div class="meta">${group.members.length} Mitglieder</div>
        <div style="margin-top:8px">${group.members.map(member => `<span class="badge" style="margin-right:5px">${escapeHtml(member.name)}</span>`).join('') || '<span class="muted">Leer</span>'}</div>
      </section>`).join('');
    const rows = devices.map(device => `
      <tr>
        <td>${escapeHtml(device.name)}${device.entity_id ? `<div class="entity-id">${escapeHtml(device.entity_id)}</div>` : ''}</td>
        <td>${escapeHtml(device.room || '—')}</td>
        <td><input data-group-name placeholder="Neue oder vorhandene Gruppe" list="alexa-group-names"></td>
        <td><button class="secondary" data-assign="${escapeHtml(device.id)}">Zuordnen</button></td>
      </tr>`).join('');
    dialog.querySelector('[data-content]').innerHTML = `
      <datalist id="alexa-group-names">${options}</datalist>
      <section><h2>Vorhandene Gruppen</h2>${groupCards || '<div class="chip warn">Keine Alexa-Gruppen gefunden.</div>'}</section>
      <section><h2>Gerät zuordnen</h2><div style="overflow:auto"><table style="width:100%;border-collapse:collapse">
        <thead><tr><th style="text-align:left">Gerät</th><th style="text-align:left">Aktuelle Gruppe</th><th style="text-align:left">Zielgruppe</th><th></th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4">Keine Smart-Home-Geräte gefunden.</td></tr>'}</tbody>
      </table></div></section>`;
    dialog.querySelectorAll('[data-assign]').forEach(button => button.addEventListener('click', async () => {
      const input = button.closest('tr').querySelector('[data-group-name]');
      const groupName = input.value.trim();
      if (!groupName) return;
      button.disabled = true;
      try {
        const response = await fetch(`${base}/api/alexa-groups/assign`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({device_id: button.dataset.assign, group_name: groupName, create_missing: true}),
        });
        const updated = await response.json();
        if (!response.ok) throw new Error(updated.error || `HTTP ${response.status}`);
        renderManager(dialog, updated);
      } catch (error) {
        alert(`Gruppenzuordnung fehlgeschlagen: ${error.message}`);
        button.disabled = false;
      }
    }));
  }

  async function openManager() {
    const dialog = ensureDialog();
    dialog.querySelector('[data-content]').textContent = 'Lade Alexa-Gruppen…';
    dialog.showModal();
    try {
      const response = await fetch(`${base}/api/alexa-groups`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      renderManager(dialog, result);
    } catch (error) {
      dialog.querySelector('[data-content]').innerHTML = `<div class="chip warn">${escapeHtml(error.message)}</div>`;
    }
  }

  function ensureInventoryButton() {
    if (location.pathname.endsWith('/ha-export')) return;
    const header = document.querySelector('body > header');
    if (!header || document.getElementById('btn-open-alexa-groups')) return;
    const button = document.createElement('button');
    button.id = 'btn-open-alexa-groups';
    button.className = 'btn btn-primary';
    button.textContent = 'Gruppen';
    button.title = 'Alexa-Gruppen anzeigen und Geräte zuordnen';
    button.addEventListener('click', openManager);
    header.appendChild(button);
  }

  document.addEventListener('click', event => {
    if (!event.target.matches('.prepare, #btn-enable-visible')) return;
    setTimeout(() => {
      if (applyAreaDefaults()) {
        window.render?.();
        ensureEntityFields();
      }
    }, 0);
  }, true);

  const observer = new MutationObserver(() => {
    ensureHaControls();
    ensureEntityFields();
    ensureInventoryButton();
  });

  function init() {
    ensureHaControls();
    ensureEntityFields();
    ensureInventoryButton();
    observer.observe(document.body, {childList: true, subtree: true});
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
