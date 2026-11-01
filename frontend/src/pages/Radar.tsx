import { useMemo, useState } from "react";
import { DRIVER_LABEL, fmt, useData } from "../data";
import type { Meta, RadarRow, Signal } from "../types";
import { QualitySelect, Axes, CompanyLink, Translated, DataTable, Gate, IndexTags, Page, Panel, Src, Tag, Verif, riskLabel } from "../ui";

type Intel = Meta & { signals: Signal[]; radar: RadarRow[] };

const WINDOWS: Record<string, number> = { "24 Std.": 24, "7 Tage": 168, "30 Tage": 720 };
const TYPES: Record<string, string> = { "": "Alle Signalarten", news: "Nachricht", company_news: "Unternehmensmeldung", analyst_change: "Analystenänderung" };

export function Radar() {
  const s = useData<Intel>("intelligence.json");
  const [win, setWin] = useState("7 Tage");
  const [type, setType] = useState("");
  const [onlyOriginal, setOnlyOriginal] = useState(true);
  const [minQ, setMinQ] = useState(0);
  return (
    <Gate s={s}>
      {(d) => <RadarView d={{ ...d, radar: d.radar.filter((r) => !minQ || (r.quality ?? -1) >= minQ) }} minQ={minQ} setMinQ={setMinQ} win={win} setWin={setWin} type={type} setType={setType} onlyOriginal={onlyOriginal} setOnlyOriginal={setOnlyOriginal} />}
    </Gate>
  );
}

function RadarView({ d, minQ, setMinQ, win, setWin, type, setType, onlyOriginal, setOnlyOriginal }: {
  minQ: number; setMinQ: (v: number) => void;
  d: Intel; win: string; setWin: (w: string) => void; type: string; setType: (t: string) => void; onlyOriginal: boolean; setOnlyOriginal: (b: boolean) => void;
}) {
  const sigs = useMemo(() => {
    const cutoff = Date.now() - WINDOWS[win] * 36e5;
    return d.signals.filter((x) => x.published_at && new Date(x.published_at).getTime() >= cutoff &&
      (!type || x.signal_type === type) && (!onlyOriginal || x.independence === "original"));
  }, [d, win, type, onlyOriginal]);
  return (
    <Page title="Opportunity Radar"
      intro="Aktien mit auffälliger, quellenübergreifender Informationsaktivität. Gezählt werden unabhängige Meldungen; Kopien und Agentursyndizierungen zählen nicht doppelt. Aufmerksamkeit ist kein Qualitäts- oder Kurssignal.">
      <Panel>
        <div className="filters inline"><QualitySelect value={minQ} onChange={setMinQ} /></div>
        <DataTable rows={d.radar} rowKey={(r) => r.symbol} initialSort={{ key: "mi", dir: -1 }} limit={50}
          empty="Aktuell zeigt keine Aktie auffällige Aktivität aus unabhängigen Quellen."
          cols={[
            { key: "sym", label: "Aktie", render: (r) => <><CompanyLink symbol={r.symbol} name={r.name} /><div><IndexTags idx={r.indexes} /></div></>, sort: (r) => r.symbol },
            { key: "axes", label: "Bewertungsachsen", className: "col-axes", render: (r) => <Axes compact q={r.quality} m={r.score} p={r.political} r={r.risk} pDir={r.political_direction} /> },
            { key: "mi", label: "Market Int.", num: true, render: (r) => fmt.num(r.score, 0), sort: (r) => r.score },
            { key: "ind", label: "Unabh. 24 Std. / 7 T.", num: true, render: (r) => `${r.independent_24h} / ${r.independent_7d}`, sort: (r) => r.independent_7d },
            { key: "drv", label: "Treiber", render: (r) => r.drivers.map((x) => <Tag key={x}>{DRIVER_LABEL[x] ?? x}</Tag>) },
            { key: "risk", label: "Risiko", render: (r) => <span className={`risk-${r.risk_level}`}>{riskLabel(r.risk_level)}</span>, sort: (r) => r.risk },
          ]} />
      </Panel>

      <Panel title="Signale">
        <div className="filters inline">
          <label>Zeitraum<select value={win} onChange={(e) => setWin(e.target.value)}>{Object.keys(WINDOWS).map((w) => <option key={w}>{w}</option>)}</select></label>
          <label>Signalart<select value={type} onChange={(e) => setType(e.target.value)}>{Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className="check"><input type="checkbox" checked={onlyOriginal} onChange={(e) => setOnlyOriginal(e.target.checked)} /> Nur Originalmeldungen</label>
          <span className="muted">{sigs.length} Signale</span>
        </div>
        <ul className="signals">
          {sigs.slice(0, 150).map((x) => (
            <li key={x.id}>
              <div className="sig-head">
                {x.symbols.map((sy) => <CompanyLink key={sy} symbol={sy} />)}
                <span className="muted">{fmt.dt(x.published_at, x.date_only)}</span>
                <Verif v={x.verification} />
                {x.independence !== "original" ? <Tag tone="warn">{x.independence === "syndicated" ? "Syndizierung" : "Kopie"}</Tag> : null}
                {x.primary_source ? <Tag tone="ok">Primärquelle</Tag> : null}
              </div>
              <Translated de={x.title_de} orig={x.title} href={x.url} className="sig-title" />
              <div className="small muted">Quelle: <Src url={x.url} label={x.source_domain} />, erfasst {fmt.rel(x.captured_at)}</div>
            </li>
          ))}
        </ul>
      </Panel>
    </Page>
  );
}
