(() => {
  const state = document.getElementById("news-state");
  const metrics = document.getElementById("news-metrics");
  const feed = document.getElementById("news-feed");
  const trades = document.getElementById("news-trades");
  if (!state || !metrics || !feed || !trades) return;

  const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };

  async function refreshNews() {
    try {
      const response = await fetch("/api/news", { cache: "no-store" });
      if (!response.ok) throw new Error(`News API returned ${response.status}`);
      const data = await response.json();
      const lab = data.lab || {};
      if (!data.enabled) state.textContent = "Off · set NEWS_ENABLED=true in .env to start";
      else if (!data.configured) state.textContent = "Waiting for Alpaca API keys in .env";
      else state.textContent = `Connected · ${data.provider} · refreshes with scanner`;

      metrics.replaceChildren(
        node("span", "", `${lab.closed_trades || 0} closed`),
        node("span", "", `${lab.win_rate || 0}% wins`),
        node("span", Number(lab.total_pnl) >= 0 ? "positive" : "negative", `${money.format(lab.total_pnl || 0)} total P/L`),
        node("span", "", `${lab.open_positions || 0} open`),
      );

      trades.replaceChildren();
      for (const trade of (lab.recent_trades || []).slice(0, 5)) {
        const row = node("div", "news-trade-row");
        const label = node("span", "", `${trade.symbol} · ${trade.reason}`);
        const result = node("strong", Number(trade.pnl) >= 0 ? "positive" : "negative", money.format(trade.pnl));
        row.append(label, result);
        trades.append(row);
      }

      feed.replaceChildren();
      if (!data.articles?.length) {
        feed.append(node("p", "empty", data.enabled && data.configured ? "Waiting for matching headlines…" : "Recent headlines will appear after news access is enabled."));
      } else {
        for (const article of data.articles.slice(0, 12)) {
          const row = node("article", "news-item");
          const detail = node("div", "news-copy");
          const symbols = node("span", "news-symbols", (article.symbols || []).join(" · "));
          let articleUrl = "";
          try {
            const parsedUrl = new URL(article.url);
            if (["https:", "http:"].includes(parsedUrl.protocol)) articleUrl = parsedUrl.href;
          } catch (_) {}
          const headline = articleUrl ? node("a", "news-headline", article.headline) : node("strong", "news-headline", article.headline);
          if (articleUrl) {
            headline.href = articleUrl;
            headline.target = "_blank";
            headline.rel = "noreferrer";
          }
          const summary = article.summary ? node("p", "news-summary", article.summary) : null;
          const meta = node("small", "news-meta", `${article.source || "Alpaca News"} · ${new Date(article.published_at).toLocaleString()}`);
          detail.append(symbols, headline);
          if (summary) detail.append(summary);
          detail.append(meta);
          const score = Number(article.sentiment_score || 0);
          const badge = node("span", `sentiment-badge ${score > 0 ? "positive" : score < 0 ? "negative" : "neutral"}`, `Keyword score ${score > 0 ? "+" : ""}${score}`);
          row.append(detail, badge);
          feed.append(row);
        }
      }
    } catch (_) {
      state.textContent = "News service unavailable · check worker status";
    }
  }

  refreshNews();
  window.setInterval(refreshNews, 30000);
})();
