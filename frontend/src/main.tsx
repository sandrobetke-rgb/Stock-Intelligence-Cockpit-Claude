import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { STATUS_LABEL, fmt, useData } from "./data";
import type { MarketEvent, Meta, Summary } from "./types";
import { Dashboard } from "./pages/Dashboard";
import { Radar } from "./pages/Radar";
import { Trump } from "./pages/Trump";
import { MarketTicker } from "./pages/MarketTicker";
import { QualityStocks } from "./pages/QualityStocks";
import { Company } from "./pages/Company";
import { InsiderPage } from "./pages/Insider";
import { Superinvestors } from "./pages/Superinvestors";
import { Politicians } from "./pages/Politicians";
import { SwingPage } from "./pages/Swing";
import { WatchlistPage } from "./pages/Watchlist";
import { Confluence } from "./pages/Confluence";
import { ReportPage } from "./pages/Report";
import { SocialPage } from "./pages/Social";
import { FactCheck } from "./pages/FactCheck";
import { RiskOverview } from "./pages/Risk";

const NAV = [
  ["report", "Tagesbericht"],
  ["dashboard", "Dashboard"],
  ["watchlist", "Watchlist & Alarme"],
  ["swing", "Swing-Setups"],
  ["confluence", "Signal-Zusammenfluss"],
  ["radar", "Opportunity Radar"],
  ["trump", "Trump Mention Radar"],
  ["ticker", "Markt- & Wirtschaftsticker"],
  ["quality", "Quality Stocks"],
  ["superinvestors", "Superinvestoren"],
  ["politicians", "Politiker-Trades"],
  ["insider", "Insider & Institutionen"],
  ["social", "Social Media"],
  ["factcheck", "Fact-Checking"],
  ["risk", "Risk Overview"],
] as const;

function useRoute() {
  const get = () => window.location.hash.replace(/^#\/?/, "") || "dashboard";
  const [r, setR] = useState(get);
  useEffect(() => {
    const h = () => { setR(get()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  return r;
}

function TickerBand() {
  const s = useData<Meta & { current: MarketEvent[]; upcoming: MarketEvent[] }>("market-events.json");
  if (!s.data) return <div className="band band-empty">{s.error ? "Ticker nicht verfügbar" : " "}</div>;
  const items = [
    ...s.data.upcoming.slice(0, 6),
    ...s.data.current.filter((c) => c.relevance_level === "high" || c.kind === "news").slice(0, 10),
  ];
  if (!items.length) return <div className="band band-empty">Keine aktuellen oder geplanten Einträge</div>;
  const row = items.map((e) => (
    <a key={e.id} href="#/ticker" className={`band-item ${e.kind === "event" ? "is-planned" : "is-news"} lvl-${e.relevance_level}`}>
      <span className="band-kind">{e.kind === "event" ? STATUS_LABEL[e.status] : fmt.rel(e.time)}</span>
      {e.kind === "event" ? <span className="band-time">{fmt.dt(e.time, e.date_only)}</span> : null}
      <span className="band-title">{e.title_de || e.title}</span>
    </a>
  ));
  return (
    <div className="band" aria-label="Markt- und Wirtschaftsticker">
      <div className="band-track">{row}<span aria-hidden="true" className="band-dup">{row}</span></div>
    </div>
  );
}

function App() {
  const route = useRoute();
  const summary = useData<Summary>("summary.json");
  const [section, ...rest] = route.split("/");
  let page;
  switch (section) {
    case "radar": page = <Radar />; break;
    case "trump": page = <Trump />; break;
    case "ticker": page = <MarketTicker />; break;
    case "quality": page = <QualityStocks />; break;
    case "company": page = <Company symbol={decodeURIComponent(rest.join("/"))} />; break;
    case "insider": page = <InsiderPage />; break;
    case "politicians": page = <Politicians />; break;
    case "swing": page = <SwingPage />; break;
    case "watchlist": page = <WatchlistPage />; break;
    case "confluence": page = <Confluence />; break;
    case "report": page = <ReportPage />; break;
    case "superinvestors": page = <Superinvestors manager={rest.length ? decodeURIComponent(rest.join("/")) : undefined} />; break;
    case "social": page = <SocialPage />; break;
    case "factcheck": page = <FactCheck />; break;
    case "risk": page = <RiskOverview />; break;
    default: page = <Dashboard />;
  }
  const demo = summary.data?.mode === "demo";
  return (
    <div className="shell">
      <a className="skip" href="#main">Zum Inhalt springen</a>
      <aside className="side">
        <a className="brand" href="#/dashboard">
          <span className="brand-mark" aria-hidden="true"><i className="bm-q" /><i className="bm-m" /><i className="bm-p" /><i className="bm-r" /></span>
          <span>Stock Intelligence<br />Cockpit</span>
        </a>
        <nav aria-label="Bereiche">
          {NAV.map(([k, label]) => (
            <a key={k} href={`#/${k}`} className={section === k || (k === "quality" && section === "company") ? "active" : ""}
              aria-current={section === k ? "page" : undefined}>{label}</a>
          ))}
        </nav>
        <p className="side-foot">
          {summary.data ? <>Stand {fmt.dt(summary.data.generated_at)}</> : null}
          <br />Keine Anlageberatung.
        </p>
      </aside>
      <div className="main-col">
        <TickerBand />
        {summary.data && !demo && (() => {
          const ageH = (Date.now() - new Date(summary.data.generated_at).getTime()) / 36e5;
          const wd = new Date().getDay();
          return ageH > (wd === 0 || wd === 1 ? 60 : 30) ? (
            <div className="demo-banner" role="alert">Die Daten sind {Math.round(ageH)} Stunden alt. Der letzte automatische Lauf ist vermutlich fehlgeschlagen. Bitte unter GitHub → Actions prüfen.</div>
          ) : null;
        })()}
        {demo ? (
          <div className="demo-banner" role="alert">
            DEMO-Daten: Alle Unternehmen (Ticker DMxx), Zitate und Kennzahlen sind synthetisch. Echte Daten erscheinen, sobald die
            Pipeline in GitHub Actions gelaufen ist und <code>data/</code> veröffentlicht hat. Nur die Zentralbanktermine im Ticker sind real.
          </div>
        ) : null}
        <main id="main">{page}</main>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
