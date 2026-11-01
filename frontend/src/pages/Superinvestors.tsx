import { useMemo, useState } from "react";
import { SI_ACTION, SI_TONE, fmt, useData } from "../data";
import type { Meta, SiManager, SiStock } from "../types";
import { CompanyLink, DataTable, Empty, Gate, Page, Panel, Src, Tag } from "../ui";

type SI = Meta & { managers: SiManager[]; stocks: SiStock[]; errors: { manager: string; error: string }[]; note: string };

function Stock({ s }: { s: { symbol: string | null; issuer: string; in_universe: boolean } }) {
  return s.symbol && s.in_universe ? <CompanyLink symbol={s.symbol} name={s.issuer} />
    : <span><strong>{s.symbol ?? "–"}</strong> <span className="co-name">{s.issuer}</span></span>;
}

export function Superinvestors({ manager }: { manager?: string }) {
  const s = useData<SI>("superinvestors.json");
  return <Gate s={s}>{(d) => (manager ? <ManagerView d={d} cik={manager} /> : <Overview d={d} />)}</Gate>;
}

function Overview({ d }: { d: SI }) {
  const [view, setView] = useState<"buys" | "sells" | "held">("buys");
  const rows = useMemo(() => {
    const st = d.stocks.filter((x) => x.symbol || x.issuer);
    if (view === "buys") return st.filter((x) => x.buyers > 0).sort((a, b) => b.buyers - a.buyers || b.new_buyers - a.new_buyers || b.value - a.value);
    if (view === "sells") return st.filter((x) => x.sellers > 0).sort((a, b) => b.sellers - a.sellers || b.sold_out - a.sold_out);
    return [...st].sort((a, b) => b.holders - a.holders || b.value - a.value);
  }, [d, view]);
  const quarter = d.managers.map((m) => m.report_date).sort().pop();
  return (
    <Page title="Superinvestoren"
      intro={<>Was große Investoren laut ihrer Pflichtmeldung bei der SEC (13F) halten, gekauft und verkauft haben. Stand: Quartalsende {fmt.date(quarter)}, Veränderung gegenüber dem Vorquartal. {d.note}</>}>
      <Panel>
        <div className="filters inline" role="tablist">
          {([["buys", "Meistgekauft"], ["sells", "Meistverkauft"], ["held", "Am häufigsten gehalten"]] as const).map(([k, l]) => (
            <button key={k} role="tab" aria-selected={view === k} className={`tab ${view === k ? "sel" : ""}`} onClick={() => setView(k)}>{l}</button>
          ))}
        </div>
        <DataTable rows={rows} rowKey={(r) => r.cusip} limit={50} empty="Noch keine 13F-Daten. Sie erscheinen nach dem nächsten Pipeline-Lauf."
          cols={[
            { key: "s", label: "Aktie", render: (r) => <Stock s={r} /> },
            { key: "h", label: "Halter", num: true, render: (r) => r.holders, sort: (r) => r.holders },
            { key: "b", label: "Käufer", num: true, render: (r) => r.buyers ? <span className="pos">{r.buyers}{r.new_buyers ? ` (${r.new_buyers} neu)` : ""}</span> : "–", sort: (r) => r.buyers },
            { key: "v", label: "Verkäufer", num: true, render: (r) => r.sellers ? <span className="neg">{r.sellers}{r.sold_out ? ` (${r.sold_out} komplett)` : ""}</span> : "–", sort: (r) => r.sellers },
            { key: "m", label: "Wer", render: (r) => r.managers.filter((m) => view === "held" ? m.action !== "sold_out" : view === "buys" ? ["new", "increased"].includes(m.action) : ["reduced", "sold_out"].includes(m.action))
                .slice(0, 6).map((m) => <Tag key={m.manager} tone={SI_TONE[m.action]}>{m.manager}{m.weight_pct >= 1 ? ` ${fmt.num(m.weight_pct, 1)} %` : ""}</Tag>) },
            { key: "w", label: "Wert gesamt", num: true, render: (r) => fmt.big(r.value, "USD"), sort: (r) => r.value },
          ]} />
      </Panel>
      <Panel title="Investoren" note="Klick auf einen Namen zeigt das komplette Depot. Die Liste lässt sich in backend/data/imports/superinvestors.csv erweitern.">
        <DataTable rows={d.managers} rowKey={(r) => String(r.cik)} initialSort={{ key: "v", dir: -1 }}
          cols={[
            { key: "n", label: "Investor", render: (r) => <a href={`#/superinvestors/${r.cik}`}><strong>{r.manager}</strong></a>, sort: (r) => r.manager },
            { key: "f", label: "Gesellschaft", render: (r) => r.fund },
            { key: "v", label: "Depotwert", num: true, render: (r) => fmt.big(r.portfolio_value, "USD"), sort: (r) => r.portfolio_value },
            { key: "h", label: "Positionen", num: true, render: (r) => r.holdings, sort: (r) => r.holdings },
            { key: "nw", label: "Neu / raus", num: true, render: (r) => `${r.new} / ${r.sold_out}`, sort: (r) => r.new },
            { key: "t", label: "Größte Positionen", render: (r) => r.positions.filter((p) => p.action !== "sold_out").slice(0, 4).map((p) => <Tag key={p.cusip}>{p.symbol ?? p.issuer} {fmt.num(p.weight_pct, 0)} %</Tag>) },
            { key: "q", label: "Stichtag / Meldung", render: (r) => <>{fmt.date(r.report_date)}<div className="small muted">gemeldet {fmt.date(r.filed_at)}</div></>, sort: (r) => r.report_date },
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
  if (!m) return <Page title="Superinvestoren"><Empty>Investor nicht gefunden.</Empty><a href="#/superinvestors">Zur Übersicht</a></Page>;
  const rows = m.positions.filter((p) => !onlyChanges || !["unchanged", "unknown"].includes(p.action));
  return (
    <Page title={`${m.manager}: ${m.fund}`} actions={<a className="back" href="#/superinvestors">Zur Übersicht</a>}
      intro={<>Depot laut 13F zum {fmt.date(m.report_date)}, gemeldet am {fmt.date(m.filed_at)}. Depotwert {fmt.big(m.portfolio_value, "USD")} in {m.holdings} Positionen. Quelle: <Src url={m.filing_url} label={`SEC (${m.sec_name})`} /></>}>
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
