import { useState } from "react";
import { fmt, useData } from "../data";
import type { Insider, Institution, Meta, PoliticalTrade } from "../types";
import { CompanyLink, DataTable, Gate, Page, Panel, Src, Tag } from "../ui";

type Ins = Meta & { insiders: Insider[]; institutions: Institution[]; political_trades: PoliticalTrade[]; notes: string[] };

export function InsiderPage() {
  const s = useData<Ins>("insider.json");
  const [onlyOpen, setOnlyOpen] = useState(true);
  return (
    <Gate s={s}>
      {(d) => (
        <Page title="Insider & Institutionen" intro="Drei getrennte Datenarten mit unterschiedlicher Aussagekraft und Meldeverzug: Unternehmensinsider, institutionelle Quartalsmeldungen und Aktiengeschäfte von Politikern.">
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
          <Panel title="Institutionelle Beteiligungen" note="Quartalsmeldungen (z. B. 13F) zum Stichtag, mit bis zu 45 Tagen Veröffentlichungsverzug. Keine Echtzeitkäufe oder -verkäufe.">
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
          <Panel title="Politische Aktiengeschäfte" note="Getrennt von Unternehmensinsidern. Beträge sind gemeldete Wertbandbreiten; Meldeverzug laut Offenlegung.">
            <DataTable rows={d.political_trades} rowKey={(r) => r.id} initialSort={{ key: "disc", dir: -1 }} empty="Keine politischen Offenlegungen importiert."
              cols={[
                { key: "sym", label: "Aktie", render: (r) => <CompanyLink symbol={r.symbol} />, sort: (r) => r.symbol },
                { key: "pol", label: "Person", render: (r) => <>{r.politician}<div className="small muted">{r.chamber} {r.party}</div></> },
                { key: "t", label: "Art", render: (r) => r.transaction_type },
                { key: "tx", label: "Transaktion", render: (r) => fmt.date(r.transaction_date), sort: (r) => r.transaction_date },
                { key: "disc", label: "Offenlegung", render: (r) => <>{fmt.date(r.disclosure_date)}<div className="small muted">{r.reporting_delay_days ?? "?"} Tage Verzug</div></>, sort: (r) => r.disclosure_date },
                { key: "amt", label: "Wertband", num: true, render: (r) => `${fmt.big(r.amount_range[0])} bis ${fmt.big(r.amount_range[1])} USD` },
                { key: "src", label: "Quelle", render: (r) => <Src url={r.source_url} /> },
              ]} />
          </Panel>
        </Page>
      )}
    </Gate>
  );
}
