import { useState } from "react";
import { fmt, useData } from "../data";
import type { ConfluenceRow, Meta } from "../types";
import { CompanyLink, DataTable, EventBadges, Gate, IndexTags, Page, Panel, Tag, riskLabel } from "../ui";

const KIND: Record<string, string> = {
  insider: "Insider", superinvestors: "Superinvestoren", politicians: "Politiker", quality: "Quality", setup: "Swing-Setup",
  social: "Social", political: "Politik",
};

export function Confluence() {
  const s = useData<Meta & { rows: ConfluenceRow[] }>("confluence.json");
  const [min, setMin] = useState(2);
  const [need, setNeed] = useState<string[]>([]);
  const [noWarn, setNoWarn] = useState(false);
  return (
    <Gate s={s}>
      {(d) => {
        const rows = d.rows.filter((r) => r.count >= min && need.every((k) => r.kinds.includes(k)) && (!noWarn || !r.warnings.length));
        return (
          <Page title="Signal-Zusammenfluss"
            intro="Aktien, bei denen mehrere voneinander unabhängige Signale gleichzeitig positiv sind. Die Signale werden nicht zu einem Score verrechnet, gezählt wird nur, wie viele Arten zusammenkommen. Warnsignale stehen getrennt daneben.">
            <div className="filters">
              <label>Mindestens<select value={min} onChange={(e) => setMin(Number(e.target.value))}>{[2, 3, 4, 5].map((x) => <option key={x} value={x}>{x} Signale</option>)}</select></label>
              <div className="tabs" aria-label="Muss enthalten">
                {Object.entries(KIND).map(([k, l]) => (
                  <button key={k} aria-pressed={need.includes(k)} className={`tab ${need.includes(k) ? "sel" : ""}`}
                    onClick={() => setNeed(need.includes(k) ? need.filter((x) => x !== k) : [...need, k])}>{l}</button>
                ))}
              </div>
              <label className="check"><input type="checkbox" checked={noWarn} onChange={(e) => setNoWarn(e.target.checked)} /> Ohne Warnsignale</label>
            </div>
            <Panel title={`${rows.length} Aktien`} note="Signalarten: Insiderkäufe (90 T.), Superinvestoren kaufen (letztes Quartal), Politiker kaufen (90 T.), Quality ≥ 70, Swing-Setup heute, Social-Media positiv ohne Hype, politisch positiv. Keine Kaufempfehlung.">
              <DataTable rows={rows} rowKey={(r) => r.symbol} initialSort={{ key: "n", dir: -1 }} limit={60} empty="Keine Aktie erfüllt die gewählten Bedingungen."
                cols={[
                  { key: "s", label: "Aktie", render: (r) => <><CompanyLink symbol={r.symbol} name={r.name} /><div><IndexTags idx={r.indexes} /><EventBadges events={r.events} /></div></>, sort: (r) => r.symbol },
                  { key: "n", label: "Signale", num: true, render: (r) => <span className="conf-n">{r.count}</span>, sort: (r) => r.count * 1000 + (r.quality ?? 0) },
                  { key: "p", label: "Positiv", render: (r) => r.positives.map((x) => <Tag key={x} tone="ok">{x}</Tag>) },
                  { key: "w", label: "Warnungen", render: (r) => r.warnings.length ? r.warnings.map((x) => <Tag key={x} tone="warn">{x}</Tag>) : <span className="muted">–</span>, sort: (r) => -r.warnings.length },
                  { key: "k", label: "Kurs / 20 T.", num: true, render: (r) => <>{fmt.num(r.close, 2)}<div className="small muted">{fmt.pct(r.perf_20d, 1)}</div></>, sort: (r) => r.perf_20d },
                  { key: "r", label: "Risiko", render: (r) => <span className={`risk-${r.risk_level}`}>{riskLabel(r.risk_level)}</span> },
                ]} />
            </Panel>
          </Page>
        );
      }}
    </Gate>
  );
}
