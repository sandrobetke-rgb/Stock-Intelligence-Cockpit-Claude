import { INDEX_NAMES, VERIFICATION_LABEL, fmt, useData } from "../data";
import type { Summary } from "../types";
import { Gate, Page, Panel, Tag } from "../ui";

export function Dashboard() {
  const s = useData<Summary>("summary.json");
  return (
    <Gate s={s}>
      {(d) => {
        const qd = d.quality_distribution;
        const qmax = Math.max(1, ...Object.values(qd));
        const vtotal = Object.values(d.verification_counts).reduce((a, b) => a + b, 0) || 1;
        return (
          <Page title="Dashboard" intro={<>Universum, Datenabdeckung und Zustand des letzten Laufs. {d.disclaimer}</>}>
            <div className="kpis">
              <div className="kpi"><b>{fmt.num(d.universe.active, 0)}</b><span>Aktien im aktiven Universum</span>
                <small>{fmt.num(d.universe.index_positions, 0)} Indexpositionen, {fmt.num(d.universe.archived, 0)} archiviert</small></div>
              <div className="kpi"><b>{d.coverage.prices_pct} %</b><span>mit Kursdaten</span><small>letzter Kurs {fmt.date(d.freshness.latest_price_date)}</small></div>
              <div className="kpi"><b>{d.coverage.quality_scored_pct} %</b><span>mit Quality Score</span><small>Ø Datenabdeckung {d.coverage.avg_quality_coverage_pct} %</small></div>
              <div className="kpi"><b>{d.freshness.signals_24h}</b><span>Signale in 24 Std.</span><small>{d.freshness.trump_bonus_active} aktive Trump-Boni, {d.freshness.upcoming_events} Termine</small></div>
              <div className={`kpi ${d.errors.length || d.coverage.data_errors ? "kpi-warn" : ""}`}><b>{d.errors.length}</b><span>Fehler im letzten Lauf</span>
                <small>{d.coverage.data_errors} Titel mit Datenfehler</small></div>
            </div>

            <div className="grid-2">
              <Panel title="Indizes" note="Mehrfach zugehörige Aktien werden einmal analysiert; alle Zugehörigkeiten bleiben gespeichert.">
                <table className="data compact">
                  <thead><tr><th>Index</th><th className="num">Mitglieder</th><th>Geprüft</th><th>Status</th></tr></thead>
                  <tbody>
                    {d.universe.indexes.map((i) => (
                      <tr key={i.code}>
                        <td><strong>{INDEX_NAMES[i.code] ?? i.name}</strong>{i.limitation ? <div className="muted small">{i.limitation}</div> : null}</td>
                        <td className="num">{fmt.num(i.members, 0)}</td>
                        <td>{fmt.dt(i.checked_at)}</td>
                        <td>{i.status === "ok" ? <Tag tone="ok">aktuell</Tag> : <><Tag tone="err">Fehler</Tag><div className="small">{i.message}</div></>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {d.universe.upcoming_changes.length ? (
                  <>
                    <h3>Angekündigte Indexänderungen</h3>
                    <ul className="plain">
                      {d.universe.upcoming_changes.map((c) => (
                        <li key={c.index + c.symbol}>{c.action === "add" ? "Aufnahme" : "Austritt"} <strong>{c.symbol}</strong> {c.name} in {INDEX_NAMES[c.index]} ab {fmt.date(c.effective_date)}</li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </Panel>

              <Panel title="Verteilung Company Quality" note="Nur Titel mit ausreichender Datenabdeckung. Fehlende Werte gelten als unbekannt, nicht als schlecht.">
                <div className="hbars">
                  {Object.entries(qd).map(([k, v]) => (
                    <div className="hbar" key={k}>
                      <span>{k}</span>
                      <span className="hbar-track"><span className="hbar-fill q" style={{ width: `${(v / qmax) * 100}%` }} /></span>
                      <b>{v}</b>
                    </div>
                  ))}
                </div>
                <h3>Verifizierung der Signale</h3>
                <div className="stack" aria-label="Verifizierungsstatus">
                  {Object.entries(d.verification_counts).filter(([, v]) => v > 0).map(([k, v]) => (
                    <span key={k} className={`stack-seg v-${k.replace(/\s/g, "")}`} style={{ flexGrow: v }} title={`${VERIFICATION_LABEL[k]}: ${v}`} />
                  ))}
                </div>
                <ul className="legend">
                  {Object.entries(d.verification_counts).map(([k, v]) => (
                    <li key={k}><i className={`v-${k.replace(/\s/g, "")}`} />{VERIFICATION_LABEL[k]} {v} ({Math.round((v / vtotal) * 100)} %)</li>
                  ))}
                </ul>
              </Panel>
            </div>

            <div className="grid-2">
              <Panel title="Letzter Pipeline-Lauf">
                <table className="data compact">
                  <thead><tr><th>Schritt</th><th>Status</th><th className="num">Dauer</th></tr></thead>
                  <tbody>
                    {d.steps.map((st, i) => (
                      <tr key={st.step + i}>
                        <td>{st.step}</td>
                        <td>{st.status === "ok" ? <Tag tone="ok">ok</Tag> : <><Tag tone="err">Fehler</Tag> <span className="small">{st.message}</span></>}</td>
                        <td className="num">{fmt.num(st.seconds, 1)} s</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
              <Panel title="Datenquellen und Einschränkungen" note="Ausschließlich kostenlose Quellen. Eingeschränkte Bereiche werden über CSV-Importe gepflegt.">
                <table className="data compact">
                  <thead><tr><th>Bereich</th><th>Quelle</th><th>Status</th></tr></thead>
                  <tbody>
                    {d.sources.map((x) => (
                      <tr key={x.area}>
                        <td><strong>{x.area}</strong><div className="muted small">{x.limitation}</div></td>
                        <td>{x.source}</td>
                        <td>{x.status === "connected" ? <Tag tone="ok">verbunden</Tag> : <Tag tone="warn">eingeschränkt</Tag>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            </div>
          </Page>
        );
      }}
    </Gate>
  );
}
