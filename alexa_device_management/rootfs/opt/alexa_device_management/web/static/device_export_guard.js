(() => {
  function relabel() {
    for (const button of document.querySelectorAll('button[data-action="prepare-device"]')) {
      button.textContent = "Gerät exportieren";
      button.title = "Wählt automatisch genau eine geeignete Haupt-Entity für Alexa aus";
    }
  }

  const content = document.getElementById("content");
  if (content) {
    new MutationObserver(relabel).observe(content, {childList: true, subtree: true});
  }
  relabel();
})();
