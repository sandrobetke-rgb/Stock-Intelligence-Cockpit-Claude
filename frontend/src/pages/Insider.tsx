import { useState } from "react";
import { fmt, useData } from "../data";
import type { ClusterBuy, Insider, Institution, Meta, PoliticalTrade } from "../types";
import { CompanyLink, DataTable, Gate, Page, Panel, Src, Tag } from "../ui";

type Ins = Meta & { cluster_buys: ClusterBuy[]; insiders: Insider[]; institutions: Institution[]; political_trades: PoliticalTrade[]; notes: string[] };

export function InsiderPage() {
  const s = useData<Ins>("insider.json");
  const [onlyOpen, setOnlyOpen] = useState(true);
  return (
    <Gate s={s}>
      {(d) => (
        <Page title="Insider & Institutionen" intro="Drei getrennte Datenarten mit unterschiedlicher Aussagekraft und Meldeverzug: Unternehmensinsider, institutionelle Quartalsmeldungen und Aktiengeschäfte von Politikern.">
          <Panel title="Cluster-Käufe (14 Tage)" note="Mindestens zwei verschiedene Insider derselben Firma haben am offenen Markt gekauft. Gilt als aussagekräftiger als Einzelkäufe, ist aber keine Kaufempfehlung.">
            <DataTable rows={d.cluster_buys ?? []} rowKey={(r) => r.symbol} initialSort={{ key: "n", dir: -1 }} limit={30} empty="Derzeit keine Cluster-Käufe."
              cols={[
                { key: "s", label: "Aktie", render: (r) => <CompanyLink symbol={r.symbol} />, sort: (r) => r.symbol },
                { key: "n", label: "Insider", num: true, render: (r) => r.insiders, sort: (r) => r.insiders },
                { key: "t", label: "Käufe", num: true, render: (r) => r.transactions, sort: (r) => r.transactions },
                { key: "v", label: "Volumen", num: true, render: (r) => fmt.big(r.value, "USD"), sort: (r) => r.value },
                { key: "r", label: "Funktionen", render: (r) => r.roles.map((x) => <Tag key={x}>{x}</Tag>) },
                { key: "z", label: "Zeitraum", render: (r) => `${fmt.date(r.first)} bis ${fmt.date(r.last)}`, sort: (r) => r.last },
              ]} />
          </Panel>
          <Panel title="Unternehmensinsider" note="Käufe und Verkäufe am offenen Markt sind von Optionsausübungen, Vergütung und Steuereinbehalt getrennt.">
            <label className="check filters inline"><input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> Nur Käufe/Verkäufe am offenen Markt</label>
            <DataTable rows={d.insiders.filter((x) => !onlyOpen || x.open_market)} rowKey={(r) => r.id} initialSort={{ key: "filed", dir: -1 }} limit={50}
              empty="Keine Insidermeldungen im Zeitraum."
              cols={[
                { key: "sym", label: "Aktie", render: (r) => <CompanyLink symbol={r.symbol} />, sort: (r) => r.symbol },
                { key: "who", label: "Person / Funktion", render: (r) => <>{r.insider}<div className="small muted">{r.role}</div></> },
                { key: "kind", label: "Art", render: (r) => <><Tag tone={r.open_market ? (r.transaction_kind === "buy" ? "ok" : "err") : undefined}>{r.transaction_label}</Tag>{r.rule_10b5_1_plan ? <div className="small muted">10b5-1-Plan</div> : null}</> },
                { key: "tx", label: "Transaktion", render: (r) => fmt.date(r.transaction_date), sort: (r) => r.transaction_date },
                { key: "filed", label: "Meldung", render: (r) => <>{fmt.date(r.filed_at)}<div className="small muted">{r.reporting_delay_days ?? "?"} Tage Verzug</div></>, sort: (r) => r.filed_at },
                { key: "sh", label: "Stück", num: true, render: (r) => fmt.num(r.shares, 0), sort: (r) => r.shares },
                { key: "val", label: "Volumen", num: true, render: (r) => fmt.big(r.value, r.currency), sort: (r) => r.value },
                { key: "src", label: "Offenlegung", render: (r) => <Src url={r.source_url} /> },
              ]} />
          </Panel>
          <Panel title="Institutionelle Beteiligungen" note="Manuell importierte Quartalsmeldungen. Die automatisch geladenen Depots großer Investoren stehen unter Superinvestoren.">
            <DataTable rows={d.institutions} rowKey={(r) => r.id} initialSort={{ key: "val", dir: -1 }} limit={50} empty="Keine institutionellen Meldungen importiert."
              cols={[
                { key: "sym", label: "Aktie", render: (r) => <CompanyLink symbol={r.symbol} />, sort: (r) => r.symbol },
                { key: "inst", label: "Institution", render: (r) => r.institution, sort: (r) => r.institution },
                { key: "st", label: "Position", render: (r) => <Tag>{({ new: "neu", increased: "erhöht", reduced: "reduziert", closed: "aufgegeben", unchanged: "unverändert" } as Record<string, string>)[r.position_status] ?? r.position_status}</Tag> },
                { key: "per", label: "Stichtag / Meldung", render: (r) => <>{fmt.date(r.report_period)}<div className="small muted">gemeldet {fmt.date(r.filed_at)}, {r.publication_delay_days ?? "?"} Tage später</div></>, sort: (r) => r.report_period },
                { key: "chg", label: "Veränderung Stück", num: true, render: (r) => fmt.num(r.shares_change, 0), sort: (r) => r.shares_change },
                { key: "val", label: "Wert (USD)", num: true, render: (r) => fmt.big(r.value_usd), sort: (r) => r.value_usd },
                { key: "pct", label: "Anteil", num: true, render: (r) => r.pct_outstanding == null ? "–" : `${fmt.num(r.pct_outstanding, 2)} %`, sort: (r) => r.pct_outstanding },
                { key: "src", label: "Quelle", render: (r) => <Src url={r.source_url} /> },
              ]} />
          </Panel>
          <Panel title="Politische Aktiengeschäfte">
            <p>Die Geschäfte von US-Kongressmitgliedern stehen auf einer eigenen Seite: <a href="#/politicians">Politiker-Trades</a>.</p>
          </Panel>
        </Page>
      )}
    </Gate>
  );
}
