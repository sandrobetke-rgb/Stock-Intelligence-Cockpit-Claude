import { useEffect, useRef } from "react";

/** TradingView-Symbol aus unserem Ticker: SAP.DE -> XETR:SAP, BRK-B -> BRK.B (US ohne Börsenpräfix, TradingView löst auf). */
export function tvSymbol(symbol: string, region?: string) {
  if (symbol.endsWith(".DE") || region === "DE") return `XETR:${symbol.replace(/\.DE$/, "")}`;
  return symbol.replace(/-/g, ".");
}

/** Eingebetteter TradingView-Chart (kostenloses Widget): Tageskerzen mit EMA 20/50/200 und Volumen. */
export function TvChart({ symbol, region }: { symbol: string; region?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const sym = tvSymbol(symbol, region);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.innerHTML = '<div class="tradingview-widget-container__widget" style="height:100%;width:100%"></div>';
    const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    const sc = document.createElement("script");
    sc.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    sc.async = true;
    sc.type = "text/javascript";
    sc.innerHTML = JSON.stringify({
      autosize: true, symbol: sym, interval: "D", range: "12M", timezone: "Europe/Berlin", theme: dark ? "dark" : "light",
      style: "1", locale: "de_DE", allow_symbol_change: true, hide_side_toolbar: false, withdateranges: true,
      studies: [
        { id: "MAExp@tv-basicstudies", inputs: { length: 20 } },
        { id: "MAExp@tv-basicstudies", inputs: { length: 50 } },
        { id: "MAExp@tv-basicstudies", inputs: { length: 200 } },
      ],
      support_host: "https://www.tradingview.com",
    });
    el.appendChild(sc);
    return () => { el.innerHTML = ""; };
  }, [sym]);
  return (
    <div className="tv-wrap">
      <div className="tradingview-widget-container tv-chart" ref={box} />
      <p className="small muted tv-foot">
        Chart: <a href={`https://de.tradingview.com/chart/?symbol=${encodeURIComponent(sym)}`} target="_blank" rel="noopener noreferrer">In TradingView öffnen</a>
        {" "}· Tageskerzen mit EMA 20/50/200. Daten von TradingView, ggf. verzögert.
      </p>
    </div>
  );
}
