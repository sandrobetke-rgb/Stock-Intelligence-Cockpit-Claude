import { useMemo, useState } from "react";
import { fmt, useData } from "../data";
import type { Meta, StockRow } from "../types";
import { CompanyLink, DataTable, Gate, IndexTags, Page, Panel, StockFilters, Tag, applyFilter, emptyFilter, riskLabel } from "../ui";

export type Stocks = Meta & { stocks: StockRow[] };

const DIMS: [string, string][] = [
  ["revenue_growth", "Wachstum"], ["profitability", "Marge"], ["financial_stability", "Stabilität"], ["cashflow", "Cashflow"],
  ["market_position", "Position"], ["growth_potential", "Potenzial"], ["management", "Mgmt."],
];

export function QualityStocks() {
  const s = useData<Stocks>("stocks.json");
  const [f, setF] = useState(emptyFilter);
  return (
    <Gate s={s}>
      {(d) => <QualityView rows={d.stocks} f={f} setF={setF} />}
    </Gate>
  );
}

function QualityView({ rows, f, setF }: { rows: StockRow[]; f: typeof emptyFilter; setF: (f: typeof emptyFilter) => void }) {
  const filtered = useMemo(() => applyFilter(rows, f), [rows, f]);
  return (
    <Page title="Quality Stocks"
      intro="Fundamentale Unternehmensqualität aus Umsatz, Margen, Stabilität, Cashflow, Marktposition, Wachstumspotenzial und Management. News, Social Media, Politik und Kursindikatoren fließen nicht ein.">
      <StockFilters rows={rows} f={f} set={setF} />
      <Panel>
        <p className="muted small">{filtered.length} von {rows.length} Titeln</p>
        <DataTable rows={filtered} rowKey={(r) => r.symbol} initialSort={{ key: "q", dir: -1 }} limit={100}
          cols={[
            { key: "sym", label: "Aktie", render: (r) => <><CompanyLink symbol={r.symbol} name={r.name} /><div><IndexTags idx={r.indexes} /> {r.status === "archived" ? <Tag tone="warn">archiviert</Tag> : null}</div></>, sort: (r) => r.symbol },
            { key: "sector", label: "Branche", render: (r) => <span className="small">{r.sector ?? "–"}</span>, sort: (r) => r.sector },
            { key: "q", label: "Quality", num: true, render: (r) => <span className="score-q">{fmt.num(r.quality.score, 0)}</span>, sort: (r) => r.quality.score },
            { key: "cov", label: "Abdeckung", num: true, render: (r) => <span className={r.quality.coverage_pct < 60 ? "warn-text" : ""}>{r.quality.coverage_pct} %</span>, sort: (r) => r.quality.coverage_pct },
            ...DIMS.map(([k, l]) => ({ key: k, label: l, num: true, className: "col-dim",
              render: (r: StockRow) => <span className="dimcell" style={{ ["--v" as string]: `${r.quality.dimensions[k] ?? 0}%` }}>{fmt.num(r.quality.dimensions[k], 0)}</span>,
              sort: (r: StockRow) => r.quality.dimensions[k] })),
            { key: "risk", label: "Risiko", render: (r) => <span className={`risk-${r.risk.level}`}>{riskLabel(r.risk.level)}</span>, sort: (r) => r.risk.score },
            { key: "mcap", label: "Marktkap.", num: true, render: (r) => fmt.big(r.market_cap, r.market_cap_currency), sort: (r) => r.market_cap },
          ]} />
        <p className="note">Modell „financial“: angepasste Kennzahlen für Banken und Versicherer. Marktposition, Wachstumspotenzial und Management basieren auf gekennzeichneten Proxys, sofern keine belegte manuelle Einschätzung vorliegt.</p>
      </Panel>
    </Page>
  );
}
