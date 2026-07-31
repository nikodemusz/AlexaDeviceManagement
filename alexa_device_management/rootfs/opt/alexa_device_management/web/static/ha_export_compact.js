(() => {
  const STORAGE_KEY = 'alexa-device-management-ha-compact-view';
  const expandedEntities = new Set();
  let compactEnabled = true;

  try {
    compactEnabled = localStorage.getItem(STORAGE_KEY) !== 'detailed';
  } catch (_) {
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    })[char]);
  }

  function entityConfig(entityId) {
    return window.config?.entities?.[entityId] || {};
  }

  function applyMode() {
    document.body.classList.toggle('ha-compact-disabled', !compactEnabled);
    const button = document.getElementById('btn-compact-view');
    if (button) {
      button.setAttribute('aria-pressed', compactEnabled ? 'true' : 'false');
      button.textContent = compactEnabled ? 'Ansicht: kompakt' : 'Ansicht: detailliert';
      button.title = compactEnabled
        ? 'Entities als platzsparende Liste anzeigen'
        : 'Alle Entity-Felder direkt als Kacheln anzeigen';
    }
  }

  function toggleMode() {
    compactEnabled = !compactEnabled;
    try {
      localStorage.setItem(STORAGE_KEY, compactEnabled ? 'compact' : 'detailed');
    } catch (_) {
    }
    applyMode();
    enhanceEntities();
  }

  function ensureModeButton() {
    const bulkbar = document.querySelector('.bulkbar');
    if (!bulkbar || document.getElementById('btn-compact-view')) return;
    const button = document.createElement('button');
    button.id = 'btn-compact-view';
    button.className = 'secondary';
    button.type = 'button';
    button.addEventListener('click', toggleMode);
    bulkbar.appendChild(button);
    applyMode();
  }

  function statusMarkup(entityId, card) {
    const config = entityConfig(entityId);
    const state = card.querySelector('.capability:last-child')?.textContent?.match(/Zustand:\s*([^·]+)/)?.[1]?.trim();
    const category = config.display_category || card.querySelector('.category option:checked')?.textContent || 'Automatisch';
    const values = [];
    if (config.name) values.push(`<span class="configured-name">Alexa: ${esc(config.name)}</span>`);
    values.push(`<span>${esc(category)}</span>`);
    if (state) values.push(`<span>Zustand: ${esc(state)}</span>`);
    return values.join('<span aria-hidden="true">•</span>');
  }

  function enhanceCard(card) {
    const checkbox = card.querySelector('.enabled[data-id]');
    const entityId = checkbox?.dataset.id;
    const top = card.querySelector('.entity-top');
    const title = card.querySelector('.entity-title');
    if (!entityId || !top || !title) return;

    card.dataset.entityId = entityId;
    card.classList.toggle('compact-expanded', expandedEntities.has(entityId));

    let status = title.querySelector('.compact-entity-status');
    if (!status) {
      status = document.createElement('div');
      status.className = 'compact-entity-status';
      title.appendChild(status);
    }
    const markup = statusMarkup(entityId, card);
    if (status.innerHTML !== markup) status.innerHTML = markup;

    let actions = card.querySelector('.compact-entity-actions');
    if (!actions) {
      actions = document.createElement('div');
      actions.className = 'compact-entity-actions';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary compact-edit';
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        if (expandedEntities.has(entityId)) expandedEntities.delete(entityId);
        else expandedEntities.add(entityId);
        card.classList.toggle('compact-expanded', expandedEntities.has(entityId));
        button.textContent = expandedEntities.has(entityId) ? 'Schließen' : 'Bearbeiten';
        button.setAttribute('aria-expanded', expandedEntities.has(entityId) ? 'true' : 'false');
        if (expandedEntities.has(entityId)) {
          card.querySelector('.alexaname')?.focus({preventScroll: true});
          card.scrollIntoView({block: 'nearest', behavior: 'smooth'});
        }
      });
      actions.appendChild(button);
      card.appendChild(actions);
    }

    const editButton = actions.querySelector('.compact-edit');
    if (editButton) {
      editButton.textContent = expandedEntities.has(entityId) ? 'Schließen' : 'Bearbeiten';
      editButton.setAttribute('aria-expanded', expandedEntities.has(entityId) ? 'true' : 'false');
      editButton.setAttribute('aria-label', `${expandedEntities.has(entityId) ? 'Bearbeitung schließen' : 'Entity bearbeiten'}: ${entityId}`);
    }
  }

  function enhanceEntities() {
    ensureModeButton();
    applyMode();
    document.querySelectorAll('#devices .entity-card').forEach(enhanceCard);
  }

  const originalRender = window.render;
  if (typeof originalRender === 'function') {
    window.render = function compactAwareRender(...args) {
      const result = originalRender.apply(this, args);
      requestAnimationFrame(enhanceEntities);
      return result;
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', enhanceEntities);
  } else {
    enhanceEntities();
  }
})();
