import { DRIVER_LABEL, INDEX_NAMES, MENTION_LABEL, fmt, useData } from "../data";
import type { CompanyDetail } from "../types";
import { Axes, DataTable, Direction, Empty, Gate, IndexTags, Page, Panel, Src, Tag, Verif, riskLabel, stockAxes } from "../ui";

const BASIS: Record<string, string> = { data: "Daten", proxy: "Proxy", manual: "Manuell belegt", unknown: "unbekannt", not_applicable: "nicht anwendbar" };

export function Company({ symbol }: { symbol: string }) {
  const s = useData<CompanyDetail>(symbol ? `company/${symbol}.json` : null);
  return <Gate s={s}>{(d) => <CompanyView d={d} />}</Gate>;
}

function CompanyView({ d }: { d: CompanyDetail }) {
  const p = d.profile;
  const m = d.market_detail;
  return (
    <Page title={`${p.symbol} ${p.name}`}
      intro={<>{p.sector ?? "Branche unbekannt"}{p.industry ? `, ${p.industry}` : ""}, {p.region}, {p.currency}. <IndexTags idx={p.indexes} />
        {p.status === "archived" ? <> <Tag tone="warn">archiviert seit {fmt.date(p.archived_at)} ({p.status_reason})</Tag></> : null}</>}
      actions={<a className="back" href="#/quality">Zur Übersicht</a>}>
      {p.data_flags.length ? <p className="state state-warn">Datenhinweise: {p.data_flags.join(", ")}</p> : null}
      <Panel className="axes-panel">
        <Axes {...stockAxes(p)} />
        <p className="note">Vier getrennte Dimensionen. Sie werden bewusst nicht zu einem Gesamtwert verrechnet; ein hoher Market- oder Political-Wert ist keine Kaufempfehlung.</p>
      </Panel>

      <div className="grid-2">
        <Panel title={`Company Quality ${fmt.num(d.quality_detail.score, 0)}`}
          note={<>Datenabdeckung {d.quality_detail.coverage_pct} %, Modell {d.quality_detail.model}. Quelle: <Src url={d.quality_detail.source_url} label={d.quality_detail.source} />, Stand {fmt.dt(d.quality_detail.as_of)}, Geschäftsjahr bis {fmt.date(d.quality_detail.fiscal_year_end)}{d.quality_detail.currency ? `, Währung ${d.quality_detail.currency}` : ""}. {d.quality_detail.note}</>}>
          <div className="dims">
            {d.quality_detail.dimensions.map((dim) => (
              <details key={dim.key} className="dim">
                <summary>
                  <span className="dim-name">{dim.label} <span className="muted small">{Math.round(dim.weight * 100)} %</span></span>
                  <span className="axis-track"><span className={dim.score == null ? "axis-unknown" : "axis-fill q"} style={dim.score == null ? undefined : { width: `${dim.score}%` }} /></span>
                  <span className="dim-val">{fmt.num(dim.score, 0)}</span>
                  <span className={`basis b-${dim.basis}`}>{BASIS[dim.basis]}</span>
                </summary>
                {dim.metrics.length ? (
                  <table className="data compact">
                    <tbody>{dim.metrics.map((mt) => (
                      <tr key={mt.key}><td>{mt.label}</td><td className="num">{mt.value == null ? "unbekannt" : `${fmt.num(mt.value, mt.unit === "x" ? 2 : 1)} ${mt.unit === "bool" ? "" : mt.unit}`}</td><td className="num muted">{mt.points == null ? "–" : `${fmt.num(mt.points, 0)} P.`}</td></tr>
                    ))}</tbody>
                  </table>
                ) : <p className="small muted">Für dieses Branchenmodell nicht vorgesehen.</p>}
              </details>
            ))}
          </div>
        </Panel>

        <Panel title={`Risk Score ${fmt.num(d.risk_detail.score, 0)} (${riskLabel(d.risk_detail.level)})`}
          note={<>Abdeckung {d.risk_detail.coverage_pct} %. Hohe Aufmerksamkeit senkt das Risiko nicht.{d.risk_detail.unknown_factors.length ? ` Nicht kostenlos erfasst: ${d.risk_detail.unknown_factors.join(", ")}.` : ""}</>}>
          <table className="data compact">
            <tbody>
              {d.risk_detail.factors.map((f) => (
                <tr key={f.key}>
                  <td>{f.label}{f.description ? <div className="small muted">{f.description} (<Src url={f.source} />)</div> : null}</td>
                  <td className="num">{f.value == null ? "" : f.unit === "Whg" ? fmt.big(f.value, p.currency) : `${fmt.num(f.value, 2)} ${f.unit}`}</td>
                  <td className="col-axes"><span className="axis-track"><span className={f.severity == null ? "axis-unknown" : "axis-fill r"} style={f.severity == null ? undefined : { width: `${f.severity}%` }} /></span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      <div className="grid-2">
        <Panel title="Kurs- und Marktdaten" note="Markt-Kontext; fließt nicht in Company Quality ein.">
          {m ? (
            <dl className="facts cols">
              <div><dt>Letzter Kurs</dt><dd>{fmt.num(m.last_close, 2)} {p.currency} am {fmt.date(m.price_date)}</dd></div>
              <div><dt>Marktkapitalisierung</dt><dd>{fmt.big(p.market_cap, p.market_cap_currency)}</dd></div>
              <div><dt>Performance 20 T.</dt><dd>{fmt.pct(m.perf_20d)}</dd></div>
              <div><dt>Performance 63 T.</dt><dd>{fmt.pct(m.perf_63d)}</dd></div>
              <div><dt>ADR20</dt><dd>{fmt.num(m.adr20, 2)} %</dd></div>
              <div><dt>Relative Volume</dt><dd>{fmt.num(m.rvol, 2)}</dd></div>
              <div><dt>EMA 10 / 21</dt><dd>{fmt.num(m.ema10, 2)} / {fmt.num(m.ema21, 2)}</dd></div>
              <div><dt>SMA 50 / 200</dt><dd>{fmt.num(m.sma50, 2)} / {fmt.num(m.sma200, 2)}</dd></div>
              <div><dt>Volatilität 63 T.</dt><dd>{fmt.num(m.volatility_ann, 1)} %</dd></div>
              {m.flags.length ? <div><dt>Hinweise</dt><dd className="warn-text">{m.flags.join(", ")}</dd></div> : null}
            </dl>
          ) : <Empty>Keine Kursdaten verfügbar.</Empty>}
        </Panel>
        <Panel title={`Market Intelligence ${fmt.num(d.intelligence_detail.score, 0)}`} note={d.intelligence_detail.note}>
          <table className="data compact">
            <thead><tr><th>Zeitraum</th><th className="num">Unabhängig</th><th className="num">Duplikate</th><th className="num">Quellen</th><th className="num">Primär</th></tr></thead>
            <tbody>{Object.entries(d.intelligence_detail.windows).map(([k, w]) => (
              <tr key={k}><td>{k}</td><td className="num">{w.independent}</td><td className="num">{w.duplicates}</td><td className="num">{w.sources}</td><td className="num">{w.primary}</td></tr>
            ))}</tbody>
          </table>
          <div className="hbars">
            {Object.entries(d.intelligence_detail.components).map(([k, v]) => (
              <div className="hbar" key={k}><span>{DRIVER_LABEL[k] ?? k}</span>
                <span className="hbar-track">{v == null ? <span className="axis-unknown" /> : <span className="hbar-fill m" style={{ width: `${v}%` }} />}</span><b>{v == null ? "?" : fmt.num(v, 0)}</b></div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Political Intelligence">
        <p>Relevanz {d.political_detail.relevance}, Wirkungsrichtung <Direction d={d.political_detail.direction} />,
          {d.political_detail.trump_bonus_active ? <> aktiver Trump-Bonus +{d.political_detail.trump_bonus} bis {fmt.dt(d.political_detail.next_expiry)}.</> : " kein aktiver Trump-Bonus."}</p>
        {d.trump_mentions.length ? (
          <ul className="plain">{d.trump_mentions.map((t) => (
            <li key={t.id}><Tag>{MENTION_LABEL[t.mention_type]}</Tag> <Direction d={t.direction} /> <Verif v={t.verification} /> {fmt.dt(t.statement_at, t.date_only)}:
              „{t.quote}“ (<Src url={t.source_url} label={t.source_name} />) <span className="small muted">{t.bonus.reason}</span></li>
          ))}</ul>
        ) : null}
        {d.political_events.length ? (
          <ul className="plain">{d.political_events.map((e) => (
            <li key={e.id}><Tag>{e.category}</Tag> <Direction d={e.direction} /> {fmt.dt(e.event_at, e.date_only)}: {e.title} (<Src url={e.source_url} />)</li>
          ))}</ul>
        ) : null}
        {!d.trump_mentions.length && !d.political_events.length ? <Empty>Keine belegten politischen Signale.</Empty> : null}
      </Panel>

      <Panel title="Quellen und Signale">
        {d.signals.length ? (
          <ul className="signals">{[...d.signals].sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? "")).map((x) => (
            <li key={x.id}>
              <div className="sig-head"><span className="muted">{fmt.dt(x.published_at, x.date_only)}</span><Verif v={x.verification} />
                {x.independence !== "original" ? <Tag tone="warn">{x.independence === "syndicated" ? "Syndizierung" : "Kopie"}</Tag> : null}
                {x.primary_source ? <Tag tone="ok">Primärquelle</Tag> : null}</div>
              <a href={x.url} target="_blank" rel="noopener noreferrer" className="sig-title">{x.title}</a>
              <div className="small muted"><Src url={x.url} label={x.source_domain} /></div>
            </li>
          ))}</ul>
        ) : <Empty>Keine Signale erfasst.</Empty>}
      </Panel>

      <div className="grid-2">
        <Panel title="Insider">
          <DataTable rows={d.insiders} rowKey={(r) => r.id} empty="Keine Insidermeldungen." limit={20}
            cols={[
              { key: "d", label: "Datum", render: (r) => fmt.date(r.transaction_date), sort: (r) => r.transaction_date },
              { key: "w", label: "Person", render: (r) => <>{r.insider}<div className="small muted">{r.role}</div></> },
              { key: "k", label: "Art", render: (r) => <Tag tone={r.open_market ? (r.transaction_kind === "buy" ? "ok" : "err") : undefined}>{r.transaction_label}</Tag> },
              { key: "v", label: "Volumen", num: true, render: (r) => fmt.big(r.value, r.currency), sort: (r) => r.value },
              { key: "s", label: "Quelle", render: (r) => <Src url={r.source_url} /> },
            ]} />
        </Panel>
        <Panel title="Indexzugehörigkeit und Historie">
          <table className="data compact">
            <thead><tr><th>Index</th><th>Seit</th><th>Bis</th><th>Datumsbasis</th></tr></thead>
            <tbody>{d.memberships.map((x, i) => (
              <tr key={i}><td>{INDEX_NAMES[x.index] ?? x.index}</td><td>{fmt.date(x.since)}</td><td>{x.until ? fmt.date(x.until) : "aktiv"}</td>
                <td className="small">{x.until ? (x.exit_basis === "official" ? "offiziell" : "erkannt") : x.date_basis === "official" ? "offiziell" : x.date_basis === "initial_load" ? "Erstladung" : "erkannt"}</td></tr>
            ))}</tbody>
          </table>
          {d.history.length ? <ul className="plain small">{d.history.map((h, i) => <li key={i}>{fmt.date(h.date)}: {h.from} zu {h.to} ({h.reason ?? "–"})</li>)}</ul> : null}
        </Panel>
      </div>
    </Page>
  );
}
