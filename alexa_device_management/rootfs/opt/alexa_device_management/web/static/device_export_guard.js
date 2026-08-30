(() => {
  function relabel() {
    for (const button of document.querySelectorAll('button[data-action="prepare-device"]')) {
      if (button.textContent !== "Gerät exportieren") button.textContent = "Gerät exportieren";
      const title = "Wählt automatisch genau eine geeignete Haupt-Entity für Alexa aus";
      if (button.title !== title) button.title = title;
    }
  }

  const content = document.getElementById("content");
  if (content) {
    new MutationObserver(relabel).observe(content, {childList: true, subtree: true});
  }
  relabel();
})();
