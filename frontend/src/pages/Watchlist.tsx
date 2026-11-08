import { useState } from "react";
import { githubWatchlistUrl, fmt, repoInfo, useData, useWatchlist } from "../data";
import type { AlertsData } from "../types";
import { CompanyLink, DataTable, Empty, EventBadges, Gate, Page, Panel, Tag, WatchStar } from "../ui";
import type { Stocks } from "./QualityStocks";

export function WatchlistPage() {
  const a = useData<AlertsData>("alerts.json");
  const s = useData<Stocks>("stocks.json");
  const wl = useWatchlist();
  const server = a.data?.watchlist ?? [];
  const same = server.length === wl.list.length && server.every((x) => wl.list.includes(x));
  const rows = (s.data?.stocks ?? []).filter((r) => wl.list.includes(r.symbol));
  const { owner, repo } = repoInfo();
  const [q, setQ] = useState("");
  const all = s.data?.stocks ?? [];
  const hits = q.trim().length >= 1 ? all.filter((r) => r.symbol.toLowerCase().startsWith(q.trim().toLowerCase())
    || r.name.toLowerCase().includes(q.trim().toLowerCase())).slice(0, 8) : [];
  return (
    <Page title="Watchlist & Alarme"
      intro="Aktien mit ☆ markieren (überall im Cockpit). Damit die Alarme sie kennen, speicherst du die Liste einmal in GitHub. Danach wirst du bei neuen Ereignissen benachrichtigt.">
      <Panel title={`Deine Watchlist (${wl.list.length})`}>
        <div className="wl-add">
          <label>Aktie hinzufügen<input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ticker oder Name, z. B. NVDA oder Siemens" /></label>
          {hits.length ? (
            <ul className="wl-hits">{hits.map((r) => (
              <li key={r.symbol}>
                <button className={`btn ${wl.has(r.symbol) ? "ghost" : ""}`} onClick={() => wl.toggle(r.symbol)}>{wl.has(r.symbol) ? "★ entfernen" : "☆ hinzufügen"}</button>
                <strong>{r.symbol}</strong> <span className="muted">{r.name}</span>
              </li>
            ))}</ul>
          ) : q.trim() ? <p className="small muted">Keine Aktie im Universum gefunden.</p> : null}
        </div>
        {!same ? (
          <div className="state state-warn">
            <p>Die Liste in diesem Browser weicht von der gespeicherten Alarm-Liste ab ({server.length} Aktien).</p>
            <p>
              <a className="btn" href={githubWatchlistUrl(wl.list)} target="_blank" rel="noopener noreferrer">Für Alarme in GitHub speichern</a>{" "}
              {server.length ? <button className="btn ghost" onClick={() => wl.replace(server)}>Gespeicherte Liste hierher übernehmen</button> : null}
            </p>
            <p className="small">GitHub öffnet eine vorbereitete Datei: unten bzw. oben rechts auf <strong>„Commit changes“</strong> klicken, fertig. Nach etwa 5 Minuten ist die Liste aktiv.</p>
          </div>
        ) : <p className="small muted">Gespeichert und aktiv für Alarme{a.data?.watchlist_file ? ` (Stand ${a.data.watchlist_file.replace(".csv", "")})` : ""}.</p>}
        <DataTable rows={rows} rowKey={(r) => r.symbol} initialSort={{ key: "s", dir: 1 }} empty="Noch keine Aktien markiert. Oben suchen und hinzufügen oder überall im Cockpit auf ☆ tippen."
          cols={[
            { key: "s", label: "Aktie", render: (r) => <><CompanyLink symbol={r.symbol} name={r.name} /><div><EventBadges events={r.events} max={3} /></div></>, sort: (r) => r.symbol },
            { key: "k", label: "Kurs", num: true, render: (r) => <>{fmt.num(r.market.last_close, 2)}<div className="small muted">{fmt.pct(r.market.perf_20d, 1)} (20 T.)</div></> },
            { key: "sw", label: "Setup", render: (r) => r.swing?.hits.length ? r.swing.hits.map((h) => <Tag key={h} tone="hi">{h}</Tag>) : <span className="muted">–</span> },
            { key: "q", label: "Quality", num: true, render: (r) => fmt.num(r.quality.score, 0), sort: (r) => r.quality.score },
            { key: "sig", label: "Signale", render: (r) => <>
              {r.insider.open_market_buys ? <Tag tone="ok">Insider +{r.insider.open_market_buys}</Tag> : null}
              {r.superinvestors?.buyers ? <Tag tone="ok">Superinv. +{r.superinvestors.buyers}</Tag> : null}
              {r.superinvestors?.sellers ? <Tag tone="err">Superinv. −{r.superinvestors.sellers}</Tag> : null}
              {r.politicians?.buys ? <Tag tone="ok">Politiker +{r.politicians.buys}</Tag> : null}
              {r.political.trump_bonus_active ? <Tag tone="hi">Trump</Tag> : null}
            </> },
          ]} />
      </Panel>
      <Gate s={a}>
        {(d) => (
          <>
            <Panel title="Benachrichtigung">
              <ul className="plain small">
                <li>Push aufs Handy: {d.channels.push ? <Tag tone="ok">eingerichtet</Tag> : <Tag tone="warn">nicht eingerichtet</Tag>}</li>
                <li>E-Mail: {d.channels.email ? <Tag tone="ok">eingerichtet</Tag> : <Tag>nicht eingerichtet (optional)</Tag>}</li>
                <li>Im Cockpit: <Tag tone="ok">immer</Tag> (Liste unten)</li>
              </ul>
              {!d.channels.push ? (
                <details className="howto">
                  <summary>Push-Nachrichten einrichten (kostenlos, ohne Konto)</summary>
                  <ol>
                    <li>App <strong>ntfy</strong> installieren (App Store / Google Play).</li>
                    <li>In der App auf <strong>+</strong> tippen und einen langen, geheimen Themennamen ausdenken, z. B. <code>sic-{owner.slice(0, 6)}-{Math.random().toString(36).slice(2, 10)}</code>. Abonnieren.</li>
                    <li>In GitHub: <a href={`https://github.com/${owner}/${repo}/settings/secrets/actions/new`} target="_blank" rel="noopener noreferrer">neues Secret anlegen</a>, Name <code>NTFY_TOPIC</code>, Wert = derselbe Themenname.</li>
                  </ol>
                </details>
              ) : null}
            </Panel>
            <Panel title="Alarme" note="Jedes Ereignis wird nur einmal gemeldet. Alarme sind Hinweise, keine Handelsempfehlung.">
              {d.history.length ? (
                <ul className="alerts">{d.history.slice(0, 100).map((x) => (
                  <li key={x.key} className={`prio-${x.priority}`}>
                    <div className="small muted">{fmt.dt(x.created_at)} <Tag>{x.kind_label}</Tag></div>
                    <div>{x.symbol ? <CompanyLink symbol={x.symbol} /> : null} <strong>{x.title}</strong></div>
                    {x.kind === "digest" ? (
                      <div className="small digest">{x.text.split("; ").map((part) => {
                        const [sym, ...restTxt] = part.split(" ");
                        return all.some((r) => r.symbol === sym)
                          ? <span key={part} className="dg-item"><WatchStar symbol={sym} /><a href={`#/company/${encodeURIComponent(sym)}`}>{sym}</a> {restTxt.join(" ")}</span>
                          : <span key={part} className="dg-item">{part}</span>;
                      })}</div>
                    ) : <div className="small">{x.text} {x.url ? <a href={x.url} target="_blank" rel="noopener noreferrer">Quelle</a> : null}</div>}
                  </li>
                ))}</ul>
              ) : <Empty>Noch keine Alarme. Sie erscheinen nach dem nächsten Abendlauf.</Empty>}
            </Panel>
          </>
        )}
      </Gate>
    </Page>
  );
}
