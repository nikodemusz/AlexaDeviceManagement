(function () {
  'use strict';

  const GRAPHQL_SOURCE = 'graphql';

  function decorateGraphqlRows() {
    const sourceFilter = document.getElementById('f-source');
    if (sourceFilter && ![...sourceFilter.options].some(option => option.value === GRAPHQL_SOURCE)) {
      const option = document.createElement('option');
      option.value = GRAPHQL_SOURCE;
      option.textContent = '⚠ Inaktiv / verwaist';
      sourceFilter.appendChild(option);
    }

    document.querySelectorAll('.row-check[data-source="graphql"]').forEach(checkbox => {
      const row = checkbox.closest('tr');
      if (!row) return;

      row.classList.remove('row-echo', 'row-smart-home');
      row.classList.add('row-orphaned');

      const status = row.querySelector('.online-dot');
      if (status) status.title = 'Inaktiv / verwaist';

      const badge = row.querySelector('.col-source .badge');
      if (badge) {
        badge.className = 'badge badge-inactive';
        badge.textContent = '⚠ Inaktiv';
      }

      const renameButton = row.querySelector('.btn-rename');
      if (renameButton) {
        renameButton.hidden = true;
        renameButton.disabled = true;
        renameButton.title = 'Verwaiste Endpunkte können nur gelöscht werden';
      }
    });
  }

  const originalRenderDevices = window.renderDevices;
  if (typeof originalRenderDevices === 'function') {
    window.renderDevices = function renderDevicesWithEndpointInventory(devices) {
      originalRenderDevices(devices);
      decorateGraphqlRows();
    };
  }

  decorateGraphqlRows();
})();
