(() => {
  const byId = id => document.getElementById(id);
  const symbolsInput = document.querySelector('[name="strategy_lab_extra_symbols"]');
  const symbolsList = byId("active-lab-symbol-list");
  const count = byId("active-lab-symbol-count");
  if (!symbolsInput || !symbolsList || !count) return;

  let baseSymbols = [];
  let currentExtras = [];

  function render() {
    const extras = symbolsInput.value.split(",").map(value => value.trim().toUpperCase()).filter(Boolean);
    const symbols = [...new Set([...baseSymbols, ...extras])];
    count.textContent = `${symbols.length} symbols`;
    symbolsList.replaceChildren();
    if (!symbols.length) {
      symbolsList.textContent = "No symbols configured.";
      return;
    }
    for (const symbol of symbols) {
      const chip = document.createElement("span");
      chip.className = "active-lab-symbol";
      chip.textContent = symbol;
      symbolsList.append(chip);
    }
  }

  async function load() {
    try {
      const response = await fetch("/api/settings");
      if (!response.ok) throw new Error("Unable to load active symbols");
      const settings = await response.json();
      currentExtras = String(settings.strategy_lab_extra_symbols || "")
        .split(",").map(value => value.trim().toUpperCase()).filter(Boolean);
      symbolsInput.value = settings.strategy_lab_extra_symbols || "";
      baseSymbols = (settings.strategy_lab_symbols || [])
        .map(value => String(value).trim().toUpperCase())
        .filter(value => !currentExtras.includes(value));
      render();
    } catch (_) {
      count.textContent = "Unavailable";
      symbolsList.textContent = "Could not load the current Strategy Lab symbol list.";
    }
  }

  symbolsInput.addEventListener("input", render);
  byId("open-settings").addEventListener("click", load);
  const message = byId("settings-message");
  new MutationObserver(() => {
    if (message.classList.contains("success")) load();
  }).observe(message, { attributes: true, childList: true, characterData: true });

  load();
})();
