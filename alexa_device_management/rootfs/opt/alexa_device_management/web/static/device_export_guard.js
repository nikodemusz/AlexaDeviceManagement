(() => {
  function relabel() {
    for (const button of document.querySelectorAll('button[data-action="prepare-device"]')) {
      if (button.textContent !== "Gerät exportieren") button.textContent = "Gerät exportieren";
    }
  }

  const content = document.getElementById("content");
  if (content) {
    new MutationObserver(relabel).observe(content, {childList: true, subtree: true});
  }
  relabel();
})();
