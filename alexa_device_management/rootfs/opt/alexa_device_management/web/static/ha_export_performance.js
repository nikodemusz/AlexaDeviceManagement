(() => {
  const root = document.getElementById('devices');
  if (!root) return;

  function configFor(entityId) {
    const config = window.config;
    if (!config?.entities) return null;
    return config.entities[entityId] ||= {
      enabled: false,
      name: '',
      description: '',
      display_category: '',
    };
  }

  function markDirty() {
    document.getElementById('btn-restart')?.classList.add('hidden');
    document.body.dataset.configDirty = 'true';
  }

  function updateSelectedCount() {
    const target = document.getElementById('selected-count');
    if (!target || !window.config?.entities) return;
    let selected = 0;
    for (const settings of Object.values(window.config.entities)) {
      if (settings?.enabled) selected += 1;
    }
    target.textContent = String(selected);
  }

  function updateCardState(input) {
    const card = input.closest('.entity-card');
    card?.classList.toggle('selected', input.checked);

    const device = input.closest('.device');
    if (device) {
      const hasSelected = Boolean(device.querySelector('.enabled:checked'));
      device.classList.toggle('has-selected', hasSelected);
    }
  }

  // Stop the legacy per-element handlers before they trigger a complete render of
  // every device card. All common editor changes are applied directly to the DOM.
  root.addEventListener('change', event => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;

    if (target.matches('.enabled')) {
      event.stopImmediatePropagation();
      const settings = configFor(target.dataset.id);
      if (!settings) return;
      settings.enabled = target.checked;
      updateCardState(target);
      updateSelectedCount();
      markDirty();
      return;
    }

    if (target.matches('.category')) {
      event.stopImmediatePropagation();
      const settings = configFor(target.dataset.id);
      if (!settings) return;
      settings.display_category = target.value;
      markDirty();
    }
  }, true);

  root.addEventListener('input', event => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;
    if (!target.matches('.alexaname, .description')) return;

    event.stopImmediatePropagation();
    const settings = configFor(target.dataset.id);
    if (!settings) return;

    if (target.matches('.alexaname')) settings.name = target.value;
    else settings.description = target.value;
    markDirty();
  }, true);
})();
