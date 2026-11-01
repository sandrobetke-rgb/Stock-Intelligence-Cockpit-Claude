import { STATUS_LABEL, fmt, useData } from "../data";
import type { Report } from "../types";
import { CompanyLink, Direction, Empty, Gate, Page, Panel, Tag } from "../ui";

export function ReportPage() {
  const s = useData<Report>("report.json");
  return (
    <Gate s={s}>
      {(r) => (
        <Page title={`Tagesbericht ${r.weekday}, ${fmt.date(r.report_date)}`}
          intro={<>Erstellt {fmt.dt(r.created_at)}. Alles Wichtige für den Handelstag auf einen Blick. Hinweise, keine Anlageberatung.</>}>
          {r.rule_note ? <p className="state state-warn">{r.rule_note}</p> : null}
          <div className="grid-2">
            <Panel title="Insiderkäufe (letzte 3 Tage)" note="Käufe am offenen Markt laut SEC Form 4, größte zuerst. Cluster = mehrere Insider derselben Firma.">
              <ul className="plain small">
                {r.clusters.map((c) => <li key={"c" + c.symbol}><Tag tone="ok">Cluster</Tag> <CompanyLink symbol={c.symbol} />: {c.insiders} Insider, {fmt.big(c.value, "USD")}</li>)}
                {(r.insider_buys ?? []).map((x) => <li key={x.id}><CompanyLink symbol={x.symbol} />: {x.insider} <span className="muted">({x.role})</span> kauft für <strong>{fmt.big(x.value, x.currency)}</strong>{x.superinvestor ? <Tag tone="hi">{x.superinvestor}</Tag> : null} <a href={x.source_url} target="_blank" rel="noopener noreferrer">SEC</a></li>)}
                {!r.clusters.length && !(r.insider_buys ?? []).length ? <li className="muted">Keine neuen Insiderkäufe.</li> : null}
              </ul>
            </Panel>
            <Panel title="Politiker-Trades" note="Neu gemeldet (2 Tage) und meistgekauft der letzten 30 Tage.">
              <ul className="plain small">
                {r.politician_trades.slice(0, 10).map((t) => <li key={t.id}><Tag tone={t.transaction_type === "purchase" ? "ok" : "err"}>{t.transaction_type === "purchase" ? "Kauf" : "Verkauf"}</Tag> {t.politician}: {t.in_universe ? <CompanyLink symbol={t.symbol} /> : <strong>{t.symbol}</strong>} <span className="muted">({fmt.date(t.transaction_date)})</span></li>)}
                {!r.politician_trades.length ? <li className="muted">Keine neuen Meldungen in den letzten 2 Tagen.</li> : null}
              </ul>
              {(r.politician_most_bought ?? []).length ? <>
                <h3>Meistgekauft (30 Tage)</h3>
                <ul className="plain small">{r.politician_most_bought!.map((p) => <li key={p.symbol}>{p.in_universe ? <CompanyLink symbol={p.symbol} /> : <strong>{p.symbol}</strong>}: {p.buyers.length} Käufer <span className="muted">({p.buyers.slice(0, 3).join(", ")})</span></li>)}</ul>
              </> : null}
            </Panel>
          </div>
          <div className="grid-2">
            <Panel title="Trump-Aussagen (5 Tage)" note="Aus Truth Social und vom Weißen Haus. Sonderbonus nur bei verifizierter, direkter Unternehmensnennung.">
              <ul className="plain small">
                {(r.trump_recent ?? []).map((t) => <li key={t.id}>
                  <span className="muted">{fmt.dt(t.statement_at)}</span> {t.symbol ? <CompanyLink symbol={t.symbol} /> : t.sectors.length ? <Tag>{t.sectors.join(", ")}</Tag> : null} <Direction d={t.direction} />{t.bonus ? <Tag tone="hi">Bonus</Tag> : null}
                  <div>„{(t.quote_de || t.quote).slice(0, 220)}“ <a href={t.source_url} target="_blank" rel="noopener noreferrer">{t.source_name}</a></div>
                </li>)}
                {!(r.trump_recent ?? []).length ? <li className="muted">Keine Aussagen in den letzten 5 Tagen erfasst.</li> : null}
              </ul>
            </Panel>
            <Panel title="Social Media" note="Meistdiskutiert in 24 Std. (StockTwits, Mastodon, Reddit bis 13.11.), Wikipedia-Aufrufspitzen und StockTwits-Trends.">
              <ul className="plain small">
                {(r.social_top ?? []).map((m) => <li key={m.symbol}><CompanyLink symbol={m.symbol} />: {m.mentions_24h} Beiträge{m.bullish || m.bearish ? <> (<span className="pos">{m.bullish} bullish</span> / <span className="neg">{m.bearish} bearish</span>, 7 T.)</> : null}{m.manipulation_risk === "hoch" ? <Tag tone="err">Hype-Verdacht</Tag> : null}</li>)}
              </ul>
              {r.social_movers.length ? <><h3>Stärkste Anstiege</h3><ul className="plain small">{r.social_movers.map((m) => <li key={m.symbol}><CompanyLink symbol={m.symbol} />: {m.mentions_24h}{m.change != null ? ` (${m.change > 0 ? "+" : ""}${m.change} %)` : ""}</li>)}</ul></> : null}
              {(r.attention_spikes ?? []).length ? <><h3>Wikipedia-Spitzen</h3><ul className="plain small">{r.attention_spikes!.map((a) => <li key={a.symbol}><CompanyLink symbol={a.symbol} />: {fmt.num(a.views_1d, 0)} Aufrufe, {fmt.num(a.ratio, 1)}× Schnitt <a href={a.url} target="_blank" rel="noopener noreferrer">Artikel</a></li>)}</ul></> : null}
              {(r.stocktwits_trending ?? []).length ? <p className="small"><strong>Trend auf StockTwits:</strong> {r.stocktwits_trending!.map((t) => t.symbol).join(", ")}</p> : null}
            </Panel>
          </div>
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
          <Panel title="Signal-Zusammenfluss (Top 10)">
            {r.confluence_top.length ? (
              <ul className="plain">{r.confluence_top.map((c) => (
                <li key={c.symbol}><CompanyLink symbol={c.symbol} name={c.name} /> <span className="conf-n">{c.count}</span> {c.positives.map((x) => <Tag key={x} tone="ok">{x}</Tag>)}{c.warnings.map((x) => <Tag key={x} tone="warn">{x}</Tag>)}</li>
              ))}</ul>
            ) : <Empty>Keine Aktie mit mehreren gleichzeitigen Signalen.</Empty>}
          </Panel>
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
          <Panel title="Superinvestoren: neue Quartalsmeldungen">
            {r.superinvestor_filings.length ? (
              <ul className="plain small">{r.superinvestor_filings.map((m) => <li key={m.manager}><Tag tone="hi">13F</Tag> {m.manager} (Stichtag {fmt.date(m.report_date)}): {m.new} neu{m.top_new.length ? ` (${m.top_new.join(", ")})` : ""}, {m.sold_out} komplett verkauft</li>)}</ul>
            ) : <Empty>Keine neuen 13F-Meldungen seit gestern.</Empty>}
          </Panel>
        </Page>
      )}
    </Gate>
  );
}
