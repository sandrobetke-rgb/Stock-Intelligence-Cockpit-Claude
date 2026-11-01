import { useMemo, useState } from "react";
import { fmt, useData } from "../data";
import type { Meta, PoliticalTrade } from "../types";
import { CompanyLink, DataTable, Gate, Page, Panel, Src, Tag } from "../ui";

type Pol = Meta & {
  trades: PoliticalTrade[];
  congress_status?: { chamber: string; status: string; new_reports?: number; new_trades?: number; errors?: number; message?: string }[];
  unparsed_reports?: { key: string; chamber: string; politician: string; filed: string | null; url: string }[];
};

const TX_LABEL: Record<string, string> = { purchase: "Kauf", sale: "Verkauf", sale_partial: "Teilverkauf", exchange: "Tausch" };
const TX_TONE: Record<string, string | undefined> = { purchase: "ok", sale: "err", sale_partial: "warn" };

function Sym({ t }: { t: PoliticalTrade }) {
  return t.in_universe ? <CompanyLink symbol={t.symbol} /> : <strong>{t.symbol}</strong>;
}

export function Politicians() {
  const s = useData<Pol>("politics.json");
  const [days, setDays] = useState(60);
  const [chamber, setChamber] = useState("");
  const [tx, setTx] = useState("");
  const [onlyUni, setOnlyUni] = useState(false);
  return (
    <Gate s={s}>
      {(d) => {
        const cutoff = new Date(Date.now() - days * 864e5).toISOString().slice(0, 10);
        const rows = d.trades.filter((t) => (t.disclosure_date ?? "") >= cutoff && (!chamber || t.chamber === chamber)
          && (!tx || (tx === "buy" ? t.transaction_type === "purchase" : t.transaction_type.startsWith("sale"))) && (!onlyUni || t.in_universe));
        return (
          <Page title="Politiker-Trades"
            intro="Aktiengeschäfte von Mitgliedern des US-Kongresses laut ihren Pflichtmeldungen (STOCK Act). Gemeldet wird bis zu 45 Tage nach dem Geschäft, Beträge nur als Bandbreite. Die Daten dürfen nur privat und nicht kommerziell genutzt werden.">
            <div className="filters">
              <label>Gemeldet in den letzten<select value={days} onChange={(e) => setDays(Number(e.target.value))}>
                {[14, 30, 60, 90].map((x) => <option key={x} value={x}>{x} Tagen</option>)}</select></label>
              <label>Kammer<select value={chamber} onChange={(e) => setChamber(e.target.value)}><option value="">Beide</option><option>Repräsentantenhaus</option><option>Senat</option></select></label>
              <label>Art<select value={tx} onChange={(e) => setTx(e.target.value)}><option value="">Käufe und Verkäufe</option><option value="buy">Nur Käufe</option><option value="sell">Nur Verkäufe</option></select></label>
              <label className="check"><input type="checkbox" checked={onlyUni} onChange={(e) => setOnlyUni(e.target.checked)} /> Nur Aktien im Universum</label>
            </div>
            <Ranking rows={rows} />
            <Panel title={`Alle Geschäfte (${rows.length})`}>
              <DataTable rows={rows} rowKey={(r) => r.id} initialSort={{ key: "disc", dir: -1 }} limit={60} empty="Keine Meldungen im gewählten Zeitraum."
                cols={[
                  { key: "pol", label: "Person", render: (r) => <><strong>{r.politician}</strong><div className="small muted">{r.chamber}{r.state ? `, ${r.state}` : ""}{r.party ? `, ${r.party}` : ""}</div></>, sort: (r) => r.politician },
                  { key: "s", label: "Aktie", render: (r) => <><Sym t={r} /><div className="small muted">{r.asset}</div></>, sort: (r) => r.symbol },
                  { key: "t", label: "Art", render: (r) => <><Tag tone={TX_TONE[r.transaction_type]}>{TX_LABEL[r.transaction_type] ?? r.transaction_type}</Tag>{r.asset_type === "Option" ? <Tag>Option</Tag> : null}</>, sort: (r) => r.transaction_type },
                  { key: "o", label: "Für", render: (r) => <span className="small">{r.owner}</span> },
                  { key: "amt", label: "Betrag", num: true, render: (r) => r.amount_range[1] ? `${fmt.big(r.amount_range[0])} bis ${fmt.big(r.amount_range[1])} $` : r.amount_range[0] ? `über ${fmt.big(r.amount_range[0])} $` : "–", sort: (r) => r.amount_range[0] },
                  { key: "tx", label: "Geschäft", render: (r) => fmt.date(r.transaction_date), sort: (r) => r.transaction_date },
                  { key: "disc", label: "Gemeldet", render: (r) => <>{fmt.date(r.disclosure_date)}<div className="small muted">{r.reporting_delay_days ?? "?"} Tage später</div></>, sort: (r) => r.disclosure_date },
                  { key: "src", label: "Quelle", render: (r) => <Src url={r.source_url} label="Offenlegung" /> },
                ]} />
            </Panel>
            <Panel title="Datenquellen">
              <ul className="plain small">
                {(d.congress_status ?? []).map((c) => <li key={c.chamber}>{c.chamber}: {c.status === "ok" ? <><Tag tone="ok">ok</Tag> {c.new_reports} neue Meldungen, {c.new_trades} Geschäfte erkannt{c.errors ? `, ${c.errors} Fehler` : ""}</> : <><Tag tone="err">Fehler</Tag> {c.message}</>}</li>)}
              </ul>
              {d.unparsed_reports?.length ? (
                <>
                  <h3>Nicht automatisch lesbar ({d.unparsed_reports.length})</h3>
                  <p className="small muted">Gescannte oder handschriftliche Meldungen. Bitte im Original prüfen.</p>
                  <ul className="plain small">{d.unparsed_reports.slice(0, 30).map((u) => <li key={u.key}>{fmt.date(u.filed)}: {u.politician} ({u.chamber}) <Src url={u.url} label="PDF/Meldung" /></li>)}</ul>
                </>
              ) : null}
            </Panel>
          </Page>
        );
      }}
    </Gate>
  );
}

function Ranking({ rows }: { rows: PoliticalTrade[] }) {
  const rank = useMemo(() => {
    const m = new Map<string, { symbol: string; in_universe: boolean; buyers: Set<string>; sellers: Set<string>; asset: string }>();
    for (const t of rows) {
      const a = m.get(t.symbol) ?? { symbol: t.symbol, in_universe: !!t.in_universe, buyers: new Set(), sellers: new Set(), asset: t.asset ?? "" };
      if (t.transaction_type === "purchase") a.buyers.add(t.politician);
      else if (t.transaction_type.startsWith("sale")) a.sellers.add(t.politician);
      m.set(t.symbol, a);
    }
    return [...m.values()].filter((a) => a.buyers.size + a.sellers.size > 0);
  }, [rows]);
  return (
    <Panel title="Meistgehandelt" note="Anzahl verschiedener Personen, die gekauft bzw. verkauft haben.">
      <DataTable rows={rank} rowKey={(r) => r.symbol} initialSort={{ key: "b", dir: -1 }} limit={15} empty="Keine Geschäfte im Zeitraum."
        cols={[
          { key: "s", label: "Aktie", render: (r) => <>{r.in_universe ? <CompanyLink symbol={r.symbol} /> : <strong>{r.symbol}</strong>}<div className="small muted">{r.asset}</div></>, sort: (r) => r.symbol },
          { key: "b", label: "Käufer", num: true, render: (r) => r.buyers.size ? <span className="pos">{r.buyers.size}</span> : "–", sort: (r) => r.buyers.size },
          { key: "v", label: "Verkäufer", num: true, render: (r) => r.sellers.size ? <span className="neg">{r.sellers.size}</span> : "–", sort: (r) => r.sellers.size },
          { key: "w", label: "Wer kauft", render: (r) => [...r.buyers].slice(0, 5).map((x) => <Tag key={x} tone="ok">{x}</Tag>) },
        ]} />
    </Panel>
  );
}
