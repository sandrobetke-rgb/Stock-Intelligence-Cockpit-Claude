import { useState } from "react";
import { VERIFICATION_LABEL, fmt, useData } from "../data";
import type { Meta, Signal } from "../types";
import { CompanyLink, DataTable, Gate, Page, Panel, Src, Tag, Verif } from "../ui";

type FC = Meta & { status_counts: Record<string, number>; rules: string[];
  checks: (Pick<Signal, "id" | "symbols" | "title" | "url" | "source" | "published_at" | "verification" | "independence" | "primary_source" | "cluster_id" | "fact_check">)[] };

export function FactCheck() {
  const s = useData<FC>("fact-checks.json");
  const [status, setStatus] = useState("");
  return (
    <Gate s={s}>
      {(d) => (
        <Page title="Fact-Checking" intro="Primärquellen haben Vorrang. Mehrere Seiten mit demselben Agenturtext gelten nicht als unabhängige Bestätigung.">
          <div className="vcounts">
            {Object.entries(d.status_counts).map(([k, v]) => (
              <button key={k} className={`vcount v-${k.replace(/\s/g, "")} ${status === k ? "sel" : ""}`} aria-pressed={status === k} onClick={() => setStatus(status === k ? "" : k)}>
                <b>{v}</b><span>{VERIFICATION_LABEL[k]}</span>
              </button>
            ))}
          </div>
          <Panel title="Regeln">
            <ul className="plain small">{d.rules.map((r) => <li key={r}>{r}</li>)}</ul>
          </Panel>
          <Panel title={status ? `Signale: ${VERIFICATION_LABEL[status]}` : "Alle geprüften Signale"}>
            <DataTable rows={d.checks.filter((c) => !status || c.verification === status)} rowKey={(r) => r.id} initialSort={{ key: "d", dir: -1 }} limit={60}
              cols={[
                { key: "d", label: "Datum", render: (r) => fmt.dt(r.published_at), sort: (r) => r.published_at },
                { key: "s", label: "Aktie", render: (r) => r.symbols.map((x) => <CompanyLink key={x} symbol={x} />) },
                { key: "t", label: "Meldung", render: (r) => <><a href={r.url} target="_blank" rel="noopener noreferrer">{r.title}</a>
                  {r.fact_check ? <div className="small">Prüfung: {r.fact_check.note} (<Src url={r.fact_check.source} />)</div> : null}</> },
                { key: "v", label: "Status", render: (r) => <Verif v={r.verification} />, sort: (r) => r.verification },
                { key: "i", label: "Herkunft", render: (r) => <>{r.primary_source ? <Tag tone="ok">Primärquelle</Tag> : null}
                  <Tag tone={r.independence === "original" ? undefined : "warn"}>{r.independence === "original" ? "Original" : r.independence === "syndicated" ? "Syndizierung" : "Kopie"}</Tag></> },
                { key: "q", label: "Quelle", render: (r) => <Src url={r.url} label={r.source} /> },
              ]} />
          </Panel>
        </Page>
      )}
    </Gate>
  );
}
