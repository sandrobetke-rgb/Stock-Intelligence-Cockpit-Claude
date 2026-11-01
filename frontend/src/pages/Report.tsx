import { STATUS_LABEL, fmt, useData } from "../data";
import type { Report } from "../types";
import { CompanyLink, Empty, Gate, Page, Panel, Tag } from "../ui";

export function ReportPage() {
  const s = useData<Report>("report.json");
  return (
    <Gate s={s}>
      {(r) => (
        <Page title={`Tagesbericht ${r.weekday}, ${fmt.date(r.report_date)}`}
          intro={<>Erstellt {fmt.dt(r.created_at)}. Alles Wichtige für den Handelstag auf einen Blick. Hinweise, keine Anlageberatung.</>}>
          {r.rule_note ? <p className="state state-warn">{r.rule_note}</p> : null}
          <div className="grid-2">
            <Panel title="Termine">
              {r.macro.length || r.earnings.length ? (
                <ul className="plain">
                  {r.macro.map((e) => <li key={e.id}><Tag tone="hi">{STATUS_LABEL[e.status]}</Tag> {fmt.dt(e.time, e.date_only)}: <strong>{e.title}</strong></li>)}
                  {r.earnings.length ? <li><strong>Quartalszahlen:</strong> {r.earnings.map((e) => (
                    <span key={e.symbol} className="rep-earn"><CompanyLink symbol={e.symbol} />{e.time ? <span className="small muted"> {e.time}</span> : null}</span>
                  ))}</li> : null}
                </ul>
              ) : <Empty>Keine wichtigen Termine.</Empty>}
            </Panel>
            <Panel title={`Watchlist (${r.watchlist_alerts.length} neue Ereignisse)`}>
              {r.watchlist_alerts.length ? (
                <ul className="plain small">{r.watchlist_alerts.map((a) => <li key={a.key}><Tag>{a.kind_label}</Tag> <strong>{a.title}</strong> – {a.text}</li>)}</ul>
              ) : <Empty>Nichts Neues zu deinen Aktien.</Empty>}
            </Panel>
          </div>
          <Panel title={`Swing-Kandidaten (${r.candidates.length})`} note="Setup + Abendfilter erfüllt, keine Zahlen in den nächsten 5 Tagen. Einstieg nur nach deiner 1H-Regel ab 16:00 MEZ.">
            {r.candidates.length ? (
              <div className="table-wrap"><table className="data compact">
                <thead><tr><th>Aktie</th><th>Setup</th><th className="num">Auslöser</th><th className="num">max.</th><th className="num">Stopp</th><th className="num">Ziel 1</th><th className="num">RelVol</th></tr></thead>
                <tbody>{r.candidates.map((c) => (
                  <tr key={c.symbol}><td><CompanyLink symbol={c.symbol} name={c.name} /></td><td>{c.hits.map((h) => <Tag key={h} tone="hi">{h}</Tag>)}</td>
                    <td className="num">{fmt.num(c.trigger, 2)}</td><td className="num">{fmt.num(c.entry_max, 2)}</td>
                    <td className="num neg">{fmt.num(c.stop, 2)}</td><td className="num pos">{fmt.num(c.target_1, 2)}</td><td className="num">{fmt.num(c.rvol, 2)}</td></tr>
                ))}</tbody>
              </table></div>
            ) : <Empty>Heute kein Kandidat. Das ist ein gültiges Ergebnis.</Empty>}
          </Panel>
          <Panel title="Signal-Zusammenfluss (Top 10)">
            {r.confluence_top.length ? (
              <ul className="plain">{r.confluence_top.map((c) => (
                <li key={c.symbol}><CompanyLink symbol={c.symbol} name={c.name} /> <span className="conf-n">{c.count}</span> {c.positives.map((x) => <Tag key={x} tone="ok">{x}</Tag>)}{c.warnings.map((x) => <Tag key={x} tone="warn">{x}</Tag>)}</li>
              ))}</ul>
            ) : <Empty>Keine Aktie mit mehreren gleichzeitigen Signalen.</Empty>}
          </Panel>
          <div className="grid-2">
            <Panel title="Neu seit gestern">
              <ul className="plain small">
                {r.clusters.map((c) => <li key={c.symbol}><Tag tone="ok">Cluster-Kauf</Tag> <CompanyLink symbol={c.symbol} />: {c.insiders} Insider, {fmt.big(c.value, "USD")}</li>)}
                {r.superinvestor_filings.map((m) => <li key={m.manager}><Tag tone="hi">13F</Tag> {m.manager} (Stichtag {fmt.date(m.report_date)}): {m.new} neu{m.top_new.length ? ` (${m.top_new.join(", ")})` : ""}, {m.sold_out} komplett verkauft</li>)}
                {r.politician_trades.slice(0, 12).map((t) => <li key={t.id}><Tag tone={t.transaction_type === "purchase" ? "ok" : "err"}>Politiker</Tag> {t.politician}: {t.transaction_type === "purchase" ? "Kauf" : "Verkauf"} {t.symbol}</li>)}
                {r.trump.map((t) => <li key={t.id}><Tag tone="hi">Trump</Tag> {t.symbol}: „{(t.quote_de || t.quote).slice(0, 120)}“</li>)}
                {!r.clusters.length && !r.superinvestor_filings.length && !r.politician_trades.length && !r.trump.length ? <li className="muted">Keine neuen Meldungen.</li> : null}
              </ul>
            </Panel>
            <Panel title="Social Media: stärkste Anstiege (24 Std.)">
              {r.social_movers.length ? (
                <ul className="plain small">{r.social_movers.map((m) => <li key={m.symbol}><CompanyLink symbol={m.symbol} />: {m.mentions_24h} Beiträge{m.change != null ? ` (${m.change > 0 ? "+" : ""}${m.change} %)` : ""}, Stimmung {fmt.num(m.sentiment, 2)}</li>)}</ul>
              ) : <Empty>Keine auffälligen Bewegungen.</Empty>}
            </Panel>
          </div>
        </Page>
      )}
    </Gate>
  );
}
