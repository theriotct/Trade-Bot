(() => {
  const detail = document.getElementById("paper-mode-details");
  if (!detail) return;
  async function refresh() {
    try {
      const response = await fetch("/health", { cache: "no-store" });
      if (!response.ok) throw new Error("Health check failed");
      const health = await response.json();
      const execution = health.execution_mode === "alpaca_paper" ? "Alpaca paper orders" : "Local paper simulation";
      const feed = health.market_data_provider === "alpaca" ? "Alpaca IEX bars" : "Yahoo Finance bars";
      detail.textContent = `${execution} · ${feed}`;
    } catch (_) {
      detail.textContent = "Paper-only trading · service status unavailable";
    }
  }
  refresh();
  window.setInterval(refresh, 30000);
})();
