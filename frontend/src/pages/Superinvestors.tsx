import { useMemo, useState } from "react";
import { SI_ACTION, SI_TONE, fmt, useData } from "../data";
import type { BigStake, CorpEvent, Insider, Meta, SiManager, SiStock } from "../types";
import { CompanyLink, DataTable, Empty, EventBadges, Gate, Page, Panel, Src, Tag } from "../ui";

type SI = Meta & {
  managers: SiManager[]; stocks: SiStock[]; errors: { manager: string; error: string }[]; note: string;
  stakes?: BigStake[]; insider_trades?: Insider[];
};

const FRESH_DAYS = 28;

function Stock({ s }: { s: { symbol: string | null; issuer: string; in_universe: boolean; events?: CorpEvent[] } }) {
  return (
    <>
      {s.symbol && s.in_universe ? <CompanyLink symbol={s.symbol} name={s.issuer} />
        : <span><strong>{s.symbol ?? "–"}</strong> <span className="co-name">{s.issuer}</span></span>}
      <EventBadges events={s.events} />
    </>
  );
}

export function Superinvestors({ manager }: { manager?: string }) {
  const s = useData<SI>("superinvestors.json");
  return <Gate s={s}>{(d) => (manager ? <ManagerView d={d} cik={manager} /> : <Overview d={d} />)}</Gate>;
}

/** Ranglisten aus den Depots neu berechnen (für den 4-Wochen-Filter). */
function aggregate(managers: SiManager[], events: Map<string, CorpEvent[] | undefined>): SiStock[] {
  const agg = new Map<string, SiStock>();
  for (const m of managers) {
    if (m.stale) continue;
    for (const p of m.positions) {
      const k = p.symbol ?? p.cusip;
      const a = agg.get(k) ?? { symbol: p.symbol, cusip: p.cusip, issuer: p.issuer, in_universe: p.in_universe, holders: 0, buyers: 0,
        new_buyers: 0, sellers: 0, sold_out: 0, value: 0, managers: [], events: p.symbol ? events.get(p.symbol) : undefined };
      a.holders += p.action !== "sold_out" ? 1 : 0;
      a.buyers += p.action === "new" || p.action === "increased" ? 1 : 0;
      a.new_buyers += p.action === "new" ? 1 : 0;
      a.sellers += p.action === "reduced" || p.action === "sold_out" ? 1 : 0;
      a.sold_out += p.action === "sold_out" ? 1 : 0;
      a.value += p.value;
      a.managers.push({ manager: m.manager, fund: m.fund, action: p.action, weight_pct: p.weight_pct,
        shares_change_pct: p.shares_change_pct, value: p.value, report_date: m.report_date });
      agg.set(k, a);
    }
  }
  return [...agg.values()];
}

function Overview({ d }: { d: SI }) {
  const [view, setView] = useState<"buys" | "sells" | "held">("buys");
  const [fresh, setFresh] = useState(false);
  const cutoff = new Date(Date.now() - FRESH_DAYS * 864e5).toISOString().slice(0, 10);
  const freshManagers = d.managers.filter((m) => !m.stale && m.filed_at >= cutoff);
  const stocks = useMemo(() => {
    if (!fresh) return d.stocks;
    const ev = new Map(d.stocks.map((s) => [s.symbol ?? s.cusip, s.events] as const));
    return aggregate(freshManagers, ev);
  }, [d, fresh, freshManagers.length]);
  const rows = useMemo(() => {
    const st = stocks.filter((x) => x.symbol || x.issuer);
    if (view === "buys") return st.filter((x) => x.buyers > 0).sort((a, b) => b.buyers - a.buyers || b.new_buyers - a.new_buyers || b.value - a.value);
    if (view === "sells") return st.filter((x) => x.sellers > 0).sort((a, b) => b.sellers - a.sellers || b.sold_out - a.sold_out);
    return [...st].sort((a, b) => b.holders - a.holders || b.value - a.value);
  }, [stocks, view]);
  const quarter = d.managers.filter((m) => !m.stale).map((m) => m.report_date).sort().pop();
  const stakes = (d.stakes ?? []).filter((s) => s.filed_at >= cutoff || !fresh);
  const trades = (d.insider_trades ?? []).filter((t) => (t.filed_at ?? "") >= cutoff || !fresh);
  return (
    <Page title="Superinvestoren"
      intro={<>Was große Investoren laut ihren Pflichtmeldungen bei der SEC halten, kaufen und verkaufen. Quartalsdepots (13F) zeigen den Stand
        zum Quartalsende mit bis zu 45 Tagen Verzug (jüngster Stichtag {fmt.date(quarter)}). Schneller sind Großbeteiligungen über 5 % (13D/13G, 5–10 Tage)
        und Direktkäufe von Großaktionären (Form 4, 2 Tage), beide weiter unten.</>}>
      <Panel>
        <div className="filters inline" role="tablist">
          {([["buys", "Meistgekauft"], ["sells", "Meistverkauft"], ["held", "Am häufigsten gehalten"]] as const).map(([k, l]) => (
            <button key={k} role="tab" aria-selected={view === k} className={`tab ${view === k ? "sel" : ""}`} onClick={() => setView(k)}>{l}</button>
          ))}
          <label className="check"><input type="checkbox" checked={fresh} onChange={(e) => setFresh(e.target.checked)} />
            Nur Meldungen der letzten 4 Wochen ({freshManagers.length} von {d.managers.length} Investoren)</label>
        </div>
        <DataTable rows={rows} rowKey={(r) => r.cusip} limit={50}
          empty={fresh ? "Keine 13F-Meldung in den letzten 4 Wochen. Die nächsten Quartalsdepots sind bis 14. Februar, 15. Mai, 14. August und 14. November fällig." : "Noch keine 13F-Daten."}
          cols={[
            { key: "s", label: "Aktie", render: (r) => <Stock s={r} /> },
            { key: "h", label: "Halter", num: true, render: (r) => r.holders, sort: (r) => r.holders },
            { key: "b", label: "Käufer", num: true, render: (r) => r.buyers ? <span className="pos">{r.buyers}{r.new_buyers ? ` (${r.new_buyers} neu)` : ""}</span> : "–", sort: (r) => r.buyers },
            { key: "v", label: "Verkäufer", num: true, render: (r) => r.sellers ? <span className="neg">{r.sellers}{r.sold_out ? ` (${r.sold_out} komplett)` : ""}</span> : "–", sort: (r) => r.sellers },
            { key: "m", label: "Wer", render: (r) => r.managers.filter((m) => view === "held" ? m.action !== "sold_out" : view === "buys" ? ["new", "increased"].includes(m.action) : ["reduced", "sold_out"].includes(m.action))
                .slice(0, 6).map((m) => <Tag key={m.manager} tone={SI_TONE[m.action]}>{m.manager}{m.weight_pct >= 1 ? ` ${fmt.num(m.weight_pct, 1)} %` : ""}</Tag>) },
            { key: "w", label: "Wert gesamt", num: true, render: (r) => fmt.big(r.value, "USD"), sort: (r) => r.value },
          ]} />
        <p className="note">Termin-Hinweise: „Zahlen in X T.“ = nächste Quartalszahlen, „Ex-Div.“ = Dividendenabschlag. Mit der Maus darüber (am Handy antippen) stehen Datum, Uhrzeit und Quelle.</p>
      </Panel>

      <div className="grid-2">
        <Panel title="Großbeteiligungen über 5 % (13D/13G)" note="13D: aktive Beteiligung, Meldung binnen 5 Geschäftstagen. 13G: passive Beteiligung. „/A“ = Änderung einer bestehenden Meldung.">
          <DataTable rows={stakes} rowKey={(r) => r.id} initialSort={{ key: "d", dir: -1 }} limit={20} empty="Keine 13D/13G-Meldung der beobachteten Investoren im Zeitraum."
            cols={[
              { key: "d", label: "Gemeldet", render: (r) => fmt.date(r.filed_at), sort: (r) => r.filed_at },
              { key: "m", label: "Investor", render: (r) => r.manager },
              { key: "s", label: "Aktie", render: (r) => <CompanyLink symbol={r.symbol} /> },
              { key: "f", label: "Art", render: (r) => <Tag tone={r.activist ? "hi" : undefined}>{r.form}</Tag> },
              { key: "q", label: "Quelle", render: (r) => <Src url={r.url} label="SEC" /> },
            ]} />
        </Panel>
        <Panel title="Direktkäufe/-verkäufe von Superinvestoren (Form 4)" note="Gemeldet, wenn ein Investor über 10 % an einer Firma hält oder im Vorstand sitzt; Meldung binnen 2 Geschäftstagen.">
          <DataTable rows={trades} rowKey={(r) => r.id} initialSort={{ key: "d", dir: -1 }} limit={20} empty="Keine Form-4-Meldung der beobachteten Investoren im Zeitraum."
            cols={[
              { key: "d", label: "Datum", render: (r) => fmt.date(r.transaction_date), sort: (r) => r.transaction_date },
              { key: "m", label: "Investor", render: (r) => r.superinvestor },
              { key: "s", label: "Aktie", render: (r) => <CompanyLink symbol={r.symbol} /> },
              { key: "k", label: "Art", render: (r) => <Tag tone={r.open_market ? (r.transaction_kind === "buy" ? "ok" : "err") : undefined}>{r.transaction_label}</Tag> },
              { key: "v", label: "Volumen", num: true, render: (r) => fmt.big(r.value, r.currency), sort: (r) => r.value },
              { key: "q", label: "Quelle", render: (r) => <Src url={r.source_url} label="SEC" /> },
            ]} />
        </Panel>
      </div>

      <Panel title="Investoren" note="Klick auf einen Namen zeigt das komplette Depot. Die Liste lässt sich in backend/data/imports/superinvestors.csv erweitern.">
        <DataTable rows={d.managers} rowKey={(r) => String(r.cik)} initialSort={{ key: "q", dir: -1 }}
          cols={[
            { key: "n", label: "Investor", render: (r) => <><a href={`#/superinvestors/${r.cik}`}><strong>{r.manager}</strong></a>
              {r.stale ? <div><Tag tone="warn">veraltet, nicht in Ranglisten</Tag></div> : r.filed_at >= cutoff ? <div><Tag tone="ok">neu gemeldet</Tag></div> : null}</>, sort: (r) => r.manager },
            { key: "f", label: "Gesellschaft", render: (r) => r.fund },
            { key: "v", label: "Depotwert", num: true, render: (r) => fmt.big(r.portfolio_value, "USD"), sort: (r) => r.portfolio_value },
            { key: "h", label: "Positionen", num: true, render: (r) => r.holdings, sort: (r) => r.holdings },
            { key: "nw", label: "Neu / raus", num: true, render: (r) => `${r.new} / ${r.sold_out}`, sort: (r) => r.new },
            { key: "t", label: "Größte Positionen", render: (r) => r.positions.filter((p) => p.action !== "sold_out").slice(0, 4).map((p) => <Tag key={p.cusip}>{p.symbol ?? p.issuer} {fmt.num(p.weight_pct, 0)} %</Tag>) },
            { key: "q", label: "Stichtag / Meldung", render: (r) => <>{fmt.date(r.report_date)}<div className="small muted">gemeldet {fmt.date(r.filed_at)}</div></>, sort: (r) => r.filed_at },
            { key: "src", label: "Quelle", render: (r) => <Src url={r.filing_url} label="SEC 13F" /> },
          ]} />
        {d.errors.length ? <p className="note warn-text">Nicht geladen: {d.errors.map((e) => `${e.manager} (${e.error})`).join("; ")}</p> : null}
      </Panel>
    </Page>
  );
}

function ManagerView({ d, cik }: { d: SI; cik: string }) {
  const m = d.managers.find((x) => String(x.cik) === cik);
  const [onlyChanges, setOnlyChanges] = useState(false);
  const ev = useMemo(() => new Map(d.stocks.map((s) => [s.symbol ?? s.cusip, s.events] as const)), [d]);
  if (!m) return <Page title="Superinvestoren"><Empty>Investor nicht gefunden.</Empty><a href="#/superinvestors">Zur Übersicht</a></Page>;
  const rows = m.positions.filter((p) => !onlyChanges || !["unchanged", "unknown"].includes(p.action))
    .map((p) => ({ ...p, events: p.symbol ? ev.get(p.symbol) : undefined }));
  return (
    <Page title={`${m.manager}: ${m.fund}`} actions={<a className="back" href="#/superinvestors">Zur Übersicht</a>}
      intro={<>Depot laut 13F zum {fmt.date(m.report_date)}, gemeldet am {fmt.date(m.filed_at)}. Depotwert {fmt.big(m.portfolio_value, "USD")} in {m.holdings} Positionen. Quelle: <Src url={m.filing_url} label={`SEC (${m.sec_name})`} />
        {m.stale ? <> <Tag tone="warn">Letzte Meldung ist veraltet</Tag></> : null}</>}>
      <Panel>
        <label className="check filters inline"><input type="checkbox" checked={onlyChanges} onChange={(e) => setOnlyChanges(e.target.checked)} /> Nur Veränderungen zum Vorquartal</label>
        <DataTable rows={rows} rowKey={(r) => r.cusip} initialSort={{ key: "w", dir: -1 }} limit={100}
          cols={[
            { key: "s", label: "Aktie", render: (r) => <Stock s={r} /> },
            { key: "a", label: "Aktion", render: (r) => <Tag tone={SI_TONE[r.action]}>{SI_ACTION[r.action]}</Tag>, sort: (r) => r.action },
            { key: "c", label: "Stückzahl Δ", num: true, render: (r) => r.action === "new" ? "neu" : fmt.pct(r.shares_change_pct, 0), sort: (r) => r.shares_change_pct },
            { key: "w", label: "Depotanteil", num: true, render: (r) => `${fmt.num(r.weight_pct, 2)} %`, sort: (r) => r.weight_pct },
            { key: "v", label: "Wert", num: true, render: (r) => fmt.big(r.value, "USD"), sort: (r) => r.value },
            { key: "n", label: "Stück", num: true, render: (r) => fmt.num(r.shares, 0), sort: (r) => r.shares },
          ]} />
      </Panel>
    </Page>
  );
}
