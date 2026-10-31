import { useMemo, useState } from "react";
import { fmt, useData } from "../data";
import type { StockRow } from "../types";
import { Axes, CompanyLink, DataTable, Gate, IndexTags, Page, Panel, StockFilters, Tag, applyFilter, emptyFilter, riskLabel, stockAxes } from "../ui";
import type { Stocks } from "./QualityStocks";

const LEVELS = ["niedrig", "moderat", "erhoeht", "hoch", "unbekannt"];

export function RiskOverview() {
  const s = useData<Stocks>("stocks.json");
  const [f, setF] = useState(emptyFilter);
  return <Gate s={s}>{(d) => <RiskView rows={d.stocks} f={f} setF={setF} />}</Gate>;
}

function RiskView({ rows, f, setF }: { rows: StockRow[]; f: typeof emptyFilter; setF: (f: typeof emptyFilter) => void }) {
  const filtered = useMemo(() => applyFilter(rows, f), [rows, f]);
  const counts = LEVELS.map((l) => [l, filtered.filter((r) => r.risk.level === l).length] as const);
  const masked = filtered.filter((r) => (r.risk.score ?? 0) >= 55 && ((r.market_intelligence.score ?? 0) >= 40 || r.political.relevance >= 40));
  return (
    <Page title="Risk Overview" intro="Finanzielle, wirtschaftliche, politische und Marktrisiken, separat ausgewiesen. Hohe Aufmerksamkeit senkt das Risiko nicht.">
      <StockFilters rows={rows} f={f} set={setF} />
      <div className="risk-levels">
        {counts.map(([l, n]) => <div key={l} className={`rl risk-${l}`}><b>{n}</b><span>{riskLabel(l)}</span></div>)}
      </div>
      {masked.length ? (
        <Panel title="Hohe Aufmerksamkeit bei erhöhtem Risiko" note="Diese Titel stehen im Fokus, tragen aber ein erhöhtes Risiko. Aufmerksamkeit verdeckt das Risiko nicht.">
          <ul className="plain">{masked.slice(0, 12).map((r) => <li key={r.symbol}><CompanyLink symbol={r.symbol} name={r.name} />: Risiko {fmt.num(r.risk.score, 0)}, {r.risk.top_factors.join(", ") || "mehrere Faktoren"}</li>)}</ul>
        </Panel>
      ) : null}
      <Panel>
        <DataTable rows={filtered} rowKey={(r) => r.symbol} initialSort={{ key: "r", dir: -1 }} limit={100}
          cols={[
            { key: "sym", label: "Aktie", render: (r) => <><CompanyLink symbol={r.symbol} name={r.name} /><div><IndexTags idx={r.indexes} /></div></>, sort: (r) => r.symbol },
            { key: "r", label: "Risk", num: true, render: (r) => <span className="score-r">{fmt.num(r.risk.score, 0)}</span>, sort: (r) => r.risk.score },
            { key: "lvl", label: "Stufe", render: (r) => <span className={`risk-${r.risk.level}`}>{riskLabel(r.risk.level)}</span>, sort: (r) => LEVELS.indexOf(r.risk.level) },
            { key: "cov", label: "Abdeckung", num: true, render: (r) => `${r.risk.coverage_pct} %`, sort: (r) => r.risk.coverage_pct },
            { key: "top", label: "Haupttreiber", render: (r) => r.risk.top_factors.map((x) => <Tag key={x}>{x}</Tag>) },
            { key: "pol", label: "Politik", render: (r) => r.political.negative_signals_30d ? <Tag tone="err">{r.political.negative_signals_30d} negativ (30 T.)</Tag> : null, sort: (r) => r.political.negative_signals_30d },
            { key: "axes", label: "Achsen", className: "col-axes", render: (r) => <Axes compact {...stockAxes(r)} /> },
          ]} />
      </Panel>
    </Page>
  );
}
