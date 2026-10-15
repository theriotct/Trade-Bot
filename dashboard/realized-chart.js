(() => {
  const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
  const escapeHtml = value => String(value ?? "").replace(/[&<>\'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  }[character]));
  const chart = document.getElementById("realized-chart");
  const summary = document.getElementById("realized-chart-summary");
  const note = document.getElementById("realized-chart-note");

  function render(data) {
    const trades = data.trades || [];
    if (!trades.length) {
      summary.textContent = "0 closed trades";
      chart.innerHTML = '<p class="chart-empty">The graph will appear after the first paper trade closes.</p>';
      return;
    }

    const opening = Number(data.opening_realized_pnl) || 0;
    let cumulative = opening;
    const points = trades.map(trade => {
      cumulative = Math.round((cumulative + (Number(trade.pnl) || 0)) * 100) / 100;
      return { ...trade, cumulative };
    });

    const width = 1000;
    const height = 390;
    const left = 92;
    const right = 35;
    const top = 30;
    const bottom = 57;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const values = [opening, ...points.map(point => point.cumulative)];
    const low = Math.min(0, ...values);
    const high = Math.max(0, ...values);
    const padding = Math.max((high - low) * .12, Math.max(Math.abs(high), Math.abs(low), 1) * .035, 1);
    const min = low - padding;
    const max = high + padding;
    const x = index => points.length === 1
      ? left + plotWidth / 2
      : left + (index / (points.length - 1)) * plotWidth;
    const y = value => top + ((max - value) / (max - min)) * plotHeight;
    const ticks = Array.from({ length: 5 }, (_, index) => max - ((max - min) * index) / 4);
    const grid = ticks.map(value => {
      const tickY = y(value);
      return `<line class="realized-gridline" x1="${left}" y1="${tickY}" x2="${width - right}" y2="${tickY}" />
        <text class="realized-y-label" x="${left - 12}" y="${tickY + 4}" text-anchor="end">${escapeHtml(money.format(value))}</text>`;
    }).join("");
    const baseline = `<polyline class="realized-line" points="${left},${y(opening)} ${points.map((point, index) => `${x(index)},${y(point.cumulative)}`).join(" ")}" />`;
    const markers = points.map((point, index) => {
      const timestamp = new Date(point.timestamp);
      const tradePnl = Number(point.pnl) || 0;
      const label = `${timestamp.toLocaleString()} · ${point.symbol} · ${point.practice} · close ${money.format(tradePnl)} · cumulative ${money.format(point.cumulative)}`;
      return `<circle class="realized-node ${tradePnl >= 0 ? "realized-node-up" : "realized-node-down"}" cx="${x(index)}" cy="${y(point.cumulative)}" r="${points.length > 1500 ? 2.2 : 3.6}"><title>${escapeHtml(label)}</title></circle>`;
    }).join("");
    const dateFormat = points.length > 1 && new Date(points[0].timestamp).toDateString() === new Date(points.at(-1).timestamp).toDateString()
      ? { hour: "numeric", minute: "2-digit" }
      : { month: "short", day: "numeric" };
    const dateLabels = [0, Math.floor((points.length - 1) / 2), points.length - 1]
      .filter((index, position, indexes) => indexes.indexOf(index) === position)
      .map(index => `<text class="realized-x-label" x="${x(index)}" y="${height - 17}" text-anchor="${index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"}">${escapeHtml(new Date(points[index].timestamp).toLocaleString([], dateFormat))}</text>`)
      .join("");

    chart.innerHTML = `<div class="realized-chart-scroll"><svg class="realized-line-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Cumulative realized profit and loss across closed paper trades">
      <title>Cumulative realized P/L after each trade close</title>
      <desc>Each colored point marks one close. The line shows total realized profit or loss after that close. Hover a point for the symbol, strategy, and trade P/L.</desc>
      ${grid}<line class="realized-zero" x1="${left}" y1="${y(0)}" x2="${width - right}" y2="${y(0)}" />
      ${baseline}${markers}${dateLabels}
    </svg></div>`;

    summary.textContent = `${points.length.toLocaleString()} closes · ${money.format(cumulative)} cumulative`;
    note.textContent = data.truncated
      ? `Showing the latest ${points.length.toLocaleString()} closes. The line starts at ${money.format(opening)}, the realized total before this window. Hover any point for close details.`
      : "Each point is a closed trade across the selected strategy and Strategy Lab portfolios. Hover a point for close details.";
  }

  async function refresh() {
    try {
      const response = await fetch("/api/realized-history");
      if (!response.ok) throw new Error("Could not load close history");
      render(await response.json());
    } catch (_) {
      summary.textContent = "History unavailable";
      chart.innerHTML = '<p class="chart-empty">Could not load realized trade history. It will retry shortly.</p>';
    }
  }

  refresh();
  window.setInterval(refresh, 60000);
})();
