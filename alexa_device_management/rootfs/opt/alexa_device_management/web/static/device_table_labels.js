(() => {
  function updateLabels() {
    const header = document.querySelector('.device-table th.col-manufacturer.sortable');
    if (header && !header.dataset.descriptionLabelApplied) {
      const arrow = header.querySelector('.sort-arrow');
      header.childNodes.forEach(node => {
        if (node.nodeType === Node.TEXT_NODE) node.textContent = '';
      });
      header.insertBefore(document.createTextNode('Beschreibung'), arrow || null);
      header.dataset.descriptionLabelApplied = 'true';
      header.title = 'Von Alexa bzw. dem Skill gelieferte Gerätebeschreibung';
    }

    const filter = document.getElementById('f-manufacturer');
    if (filter) {
      filter.placeholder = 'Beschreibung filtern…';
      filter.setAttribute('aria-label', 'Beschreibung filtern');
    }
  }

  updateLabels();
  new MutationObserver(updateLabels).observe(document.body, {childList: true, subtree: true});
})();
