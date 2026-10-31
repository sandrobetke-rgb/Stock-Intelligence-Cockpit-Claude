import { useState } from "react";
import { STATUS_LABEL, fmt, useData } from "../data";
import type { MarketEvent, Meta } from "../types";
import { Direction, Empty, Gate, Page, Panel, Src, Tag, Verif } from "../ui";

type ME = Meta & { current: MarketEvent[]; upcoming: MarketEvent[]; feeds: { id: string; name: string; status: string; message?: string }[]; timezone_note?: string };

function Row({ e }: { e: MarketEvent }) {
  return (
    <li className={`ev ev-${e.kind} lvl-${e.relevance_level}`}>
      <div className="ev-when">
        <span className={`ev-status st-${e.status}`}>{STATUS_LABEL[e.status]}</span>
        <time dateTime={e.time ?? undefined}>{fmt.dt(e.time, e.date_only)}</time>
        {e.kind === "event" ? <span className="small muted">Zeitzone der Quelle: {e.timezone}</span> : <span className="small muted">{fmt.rel(e.time)}</span>}
      </div>
      <div className="ev-body">
        <a href={e.url} target="_blank" rel="noopener noreferrer" className="ev-title">{e.title}</a>
        {e.summary ? <p className="small">{e.summary}</p> : null}
        <div className="ev-tags">
          {e.relevance_level === "high" ? <Tag tone="hi">hohe Relevanz</Tag> : null}
          <Tag>{e.relevance}</Tag>
          {e.categories.map((c) => <Tag key={c}>{c}</Tag>)}
          {e.markets.map((m) => <Tag key={m} tone="mk">{m}</Tag>)}
          {e.sectors.map((m) => <Tag key={m}>{m}</Tag>)}
          {e.tickers.map((m) => <Tag key={m}>{m}</Tag>)}
          {e.kind === "news" ? <Direction d={e.direction} /> : null}
          <Verif v={e.verification} />
        </div>
        {e.changes.length ? (
          <ul className="changes small">
            {e.changes.map((c, i) => <li key={i}>{fmt.dt(c.changed_at)}: {c.field === "time" ? "Termin" : "Status"} geändert von {c.field === "time" ? fmt.dt(c.from) : STATUS_LABEL[c.from ?? ""] ?? c.from} auf {c.field === "time" ? fmt.dt(c.to) : STATUS_LABEL[c.to ?? ""] ?? c.to}</li>)}
          </ul>
        ) : null}
        <div className="small muted">Quelle: <Src url={e.url} label={e.source} />, zuletzt geprüft {fmt.rel(e.last_checked_at)}</div>
      </div>
    </li>
  );
}

export function MarketTicker() {
  const s = useData<ME>("market-events.json");
  const [market, setMarket] = useState("");
  return (
    <Gate s={s}>
      {(d) => {
        const mk = [...new Set([...d.current, ...d.upcoming].flatMap((e) => e.markets))].sort();
        const f = (e: MarketEvent) => !market || e.markets.includes(market);
        return (
          <Page title="Markt- & Wirtschaftsticker"
            intro="Aktuelle und bevorstehende Ereignisse mit plausibler Bedeutung für Aktienmärkte, Branchen oder die Gesamtwirtschaft. Hohe Relevanz ist keine Kursprognose."
            actions={<label className="filters inline">Markt<select value={market} onChange={(e) => setMarket(e.target.value)}><option value="">Alle</option>{mk.map((m) => <option key={m}>{m}</option>)}</select></label>}>
            <div className="grid-2">
              <Panel title="Kommende Termine" note={d.timezone_note}>
                {d.upcoming.filter(f).length ? <ol className="events">{d.upcoming.filter(f).map((e) => <Row key={e.id} e={e} />)}</ol>
                  : <Empty>Keine geplanten Termine. Neue Termine werden in market_calendar.csv mit offizieller Quelle gepflegt.</Empty>}
              </Panel>
              <Panel title="Aktuelle Nachrichten">
                {d.current.filter(f).length ? <ol className="events">{d.current.filter(f).map((e) => <Row key={e.id} e={e} />)}</ol>
                  : <Empty>Keine aktuellen marktrelevanten Meldungen aus den angebundenen Quellen.</Empty>}
              </Panel>
            </div>
            <Panel title="Angebundene Feeds">
              <ul className="plain">{d.feeds.map((x) => <li key={x.id}>{x.name}: {x.status === "ok" ? <Tag tone="ok">ok</Tag> : x.status === "error" ? <><Tag tone="err">Fehler</Tag> <span className="small">{x.message}</span></> : <Tag>{x.status}</Tag>}</li>)}</ul>
            </Panel>
          </Page>
        );
      }}
    </Gate>
  );
}
