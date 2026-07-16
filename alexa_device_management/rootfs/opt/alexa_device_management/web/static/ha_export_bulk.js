(() => {
  const base = document.documentElement.dataset.ingressPath || '';
  const selectedIds = new Set();
  let decorating = false;

  function q(id) { return document.getElementById(id); }
  function allVisibleEntities() {
    if (typeof window.visibleDevices !== 'function') return [];
    return window.visibleDevices().flatMap(device =>
      device.entities.map(entity => ({device, entity}))
    );
  }
  function configFor(id) {
    if (typeof window.cfg === 'function') return window.cfg(id);
    window.config.entities[id] ||= {enabled:false, name:'', description:'', display_category:''};
    return window.config.entities[id];
  }
  function updateCount() {
    const el = q('bulk-selected-count');
    if (el) el.textContent = String(selectedIds.size);
    const apply = q('bulk-apply');
    if (apply) apply.disabled = selectedIds.size === 0;
  }
  function setSelected(id, selected) {
    selected ? selectedIds.add(id) : selectedIds.delete(id);
    document.querySelectorAll(`.bulk-select[data-id="${CSS.escape(id)}"]`).forEach(cb => { cb.checked = selected; });
    document.querySelectorAll(`.entity-card:has(.enabled[data-id="${CSS.escape(id)}"])`).forEach(card => card.classList.toggle('bulk-marked', selected));
    updateCount();
  }
  function decorateCards() {
    if (decorating) return;
    decorating = true;
    try {
      document.querySelectorAll('.entity-card').forEach(card => {
        const enabled = card.querySelector('.enabled[data-id]');
        if (!enabled) return;
        const id = enabled.dataset.id;
        let selector = card.querySelector('.bulk-select');
        if (!selector) {
          selector = document.createElement('input');
          selector.type = 'checkbox';
          selector.className = 'bulk-select';
          selector.dataset.id = id;
          selector.title = 'Für Massenbearbeitung markieren';
          selector.setAttribute('aria-label', `${id} für Massenbearbeitung markieren`);
          selector.addEventListener('change', () => setSelected(id, selector.checked));
          const top = card.querySelector('.entity-top');
          if (top) top.insertBefore(selector, top.firstChild);
        }
        selector.checked = selectedIds.has(id);
        card.classList.toggle('bulk-marked', selectedIds.has(id));
      });
    } finally {
      decorating = false;
      updateCount();
    }
  }
  function selectBy(mode) {
    const visible = allVisibleEntities();
    if (mode === 'none') selectedIds.clear();
    else if (mode === 'all') visible.forEach(({entity}) => selectedIds.add(entity.entity_id));
    else if (mode === 'enabled') visible.forEach(({entity}) => {
      const id = entity.entity_id;
      configFor(id).enabled ? selectedIds.add(id) : selectedIds.delete(id);
    });
    else if (mode === 'technical') visible.forEach(({entity}) => {
      const id = entity.entity_id;
      if (typeof window.isTechnical === 'function' && window.isTechnical(entity)) selectedIds.add(id);
      else selectedIds.delete(id);
    });
    else if (mode === 'useful') visible.forEach(({entity}) => {
      const id = entity.entity_id;
      if (typeof window.useful === 'function' && window.useful(entity)) selectedIds.add(id);
      else selectedIds.delete(id);
    });
    decorateCards();
  }
  function findEntity(id) {
    for (const device of window.inventory?.devices || []) {
      const entity = device.entities.find(item => item.entity_id === id);
      if (entity) return {device, entity};
    }
    return null;
  }
  function previewChanges() {
    const action = q('bulk-enable').value;
    const category = q('bulk-category').value;
    const prefix = q('bulk-prefix').value;
    const suffix = q('bulk-suffix').value;
    const description = q('bulk-description').value;
    const regenerate = q('bulk-regenerate').checked;
    const clearDescription = q('bulk-clear-description').checked;
    const lines = [];
    for (const id of selectedIds) {
      const found = findEntity(id);
      const current = configFor(id);
      let name = current.name || '';
      if (regenerate && found && typeof window.suggestedName === 'function') name = window.suggestedName(found.entity, found.device);
      if (prefix) name = `${prefix}${name}`;
      if (suffix) name = `${name}${suffix}`;
      lines.push(`${id}: ${action !== 'keep' ? `Alexa=${action}` : 'Alexa unverändert'}${category ? `, Kategorie=${category}` : ''}${name !== current.name ? `, Name=“${name}”` : ''}${clearDescription ? ', Beschreibung löschen' : description ? ', Beschreibung setzen' : ''}`);
    }
    q('bulk-preview-output').textContent = lines.join('\n') || 'Keine Entitäten markiert.';
    q('bulk-preview-dialog').showModal();
  }
  async function persist() {
    const response = await fetch(`${base}/api/ha-export/autosave`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(window.config),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
  }
  async function applyChanges() {
    if (!selectedIds.size) return;
    const action = q('bulk-enable').value;
    const category = q('bulk-category').value;
    const prefix = q('bulk-prefix').value;
    const suffix = q('bulk-suffix').value;
    const description = q('bulk-description').value;
    const regenerate = q('bulk-regenerate').checked;
    const clearDescription = q('bulk-clear-description').checked;
    const button = q('bulk-apply');
    button.disabled = true;
    button.textContent = 'Übernehme…';
    try {
      for (const id of selectedIds) {
        const current = configFor(id);
        const found = findEntity(id);
        if (action === 'enable') current.enabled = true;
        else if (action === 'disable') current.enabled = false;
        if (category) current.display_category = category;
        if (regenerate && found && typeof window.suggestedName === 'function') current.name = window.suggestedName(found.entity, found.device);
        if (prefix) current.name = `${prefix}${current.name || ''}`;
        if (suffix) current.name = `${current.name || ''}${suffix}`;
        if (clearDescription) current.description = '';
        else if (description) current.description = description;
      }
      await persist();
      if (typeof window.render === 'function') window.render();
      decorateCards();
      const status = q('status');
      if (status) {
        status.textContent = `${selectedIds.size} Entitäten wurden per Bulk-Editor geändert und gespeichert.`;
        status.className = 'status ok';
      }
    } catch (error) {
      const status = q('status');
      if (status) {
        status.textContent = `Bulk-Änderung fehlgeschlagen: ${error.message}`;
        status.className = 'status err';
      }
    } finally {
      button.textContent = 'Änderungen übernehmen';
      button.disabled = selectedIds.size === 0;
    }
  }
  function insertUi() {
    if (q('bulk-editor')) return;
    const host = document.querySelector('.toolbar');
    if (!host) return;
    const section = document.createElement('section');
    section.id = 'bulk-editor';
    section.innerHTML = `
      <div class="bulk-editor-head">
        <div><strong>Bulk-Editor</strong><div class="muted"><span id="bulk-selected-count">0</span> Entitäten markiert</div></div>
        <div class="bulk-selection-actions">
          <button class="secondary" data-select="all">Sichtbare</button>
          <button class="secondary" data-select="enabled">Aktivierte</button>
          <button class="secondary" data-select="useful">Sinnvolle</button>
          <button class="secondary" data-select="technical">Technische</button>
          <button class="secondary" data-select="none">Auswahl löschen</button>
        </div>
      </div>
      <div class="bulk-editor-grid">
        <label>Alexa-Status<select id="bulk-enable"><option value="keep">Unverändert</option><option value="enable">Aktivieren</option><option value="disable">Deaktivieren</option></select></label>
        <label>Kategorie<select id="bulk-category"><option value="">Unverändert</option>${(window.inventory?.display_categories || []).map(c => `<option value="${c}">${c}</option>`).join('')}</select></label>
        <label>Namenspräfix<input id="bulk-prefix" placeholder="z. B. EG " /></label>
        <label>Namenssuffix<input id="bulk-suffix" placeholder="z. B. Büro" /></label>
        <label class="bulk-wide">Beschreibung<textarea id="bulk-description" placeholder="Leer lassen = unverändert"></textarea></label>
        <label class="bulk-check"><input type="checkbox" id="bulk-regenerate" /> Alexa-Namen aus HA-Daten neu erzeugen</label>
        <label class="bulk-check"><input type="checkbox" id="bulk-clear-description" /> Beschreibungen löschen</label>
      </div>
      <div class="bulk-editor-actions"><button class="secondary" id="bulk-preview">Vorschau</button><button class="primary" id="bulk-apply" disabled>Änderungen übernehmen</button></div>`;
    host.insertAdjacentElement('afterend', section);
    section.querySelectorAll('[data-select]').forEach(button => button.addEventListener('click', () => selectBy(button.dataset.select)));
    q('bulk-preview').addEventListener('click', previewChanges);
    q('bulk-apply').addEventListener('click', applyChanges);

    const dialog = document.createElement('dialog');
    dialog.id = 'bulk-preview-dialog';
    dialog.innerHTML = '<header><h1>Bulk-Vorschau</h1><button class="secondary" type="button">Schließen</button></header><pre id="bulk-preview-output"></pre>';
    dialog.querySelector('button').addEventListener('click', () => dialog.close());
    document.body.appendChild(dialog);
  }
  function installStyles() {
    const style = document.createElement('style');
    style.textContent = `
      #bulk-editor{margin:0 0 12px;padding:12px;border:1px solid #cbd5e1;border-radius:12px;background:#fff;box-shadow:0 1px 3px rgba(15,23,42,.05)}
      .bulk-editor-head{display:flex;gap:12px;align-items:center;justify-content:space-between;margin-bottom:10px}.bulk-selection-actions,.bulk-editor-actions{display:flex;gap:7px;flex-wrap:wrap}
      .bulk-editor-grid{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:9px}.bulk-wide{grid-column:span 2}.bulk-check{display:flex;align-items:center;gap:8px;margin:0}.bulk-check input{width:20px;height:20px;flex:0 0 auto}
      .bulk-editor-actions{justify-content:flex-end;margin-top:10px}.bulk-select{width:22px!important;height:22px!important;flex:0 0 auto;margin:1px 0 0}.entity-card.bulk-marked{outline:2px solid #8b5cf6;outline-offset:-2px}
      @media(max-width:800px){.bulk-editor-head{align-items:flex-start;flex-direction:column}.bulk-editor-grid{grid-template-columns:1fr 1fr}.bulk-wide{grid-column:1/-1}}
      @media(max-width:520px){.bulk-editor-grid{grid-template-columns:1fr}.bulk-wide{grid-column:auto}.bulk-selection-actions{display:grid;grid-template-columns:1fr 1fr;width:100%}.bulk-editor-actions button{flex:1}}
    `;
    document.head.appendChild(style);
  }

  installStyles();
  const start = () => {
    insertUi();
    decorateCards();
    const root = q('devices');
    if (root) new MutationObserver(decorateCards).observe(root, {childList:true, subtree:true});
  };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', start) : start();
})();