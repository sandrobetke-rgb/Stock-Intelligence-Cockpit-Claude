import { fmt, useData } from "../data";
import type { Meta, SocialStat } from "../types";
import { CompanyLink, DataTable, Empty, Gate, Page, Panel, Src, Tag } from "../ui";

type So = Meta & { stocks: Record<string, SocialStat>; note: string };

export function SocialPage() {
  const s = useData<So>("social.json");
  return (
    <Gate s={s}>
      {(d) => {
        const rows = Object.entries(d.stocks).map(([symbol, v]) => ({ symbol, ...v }));
        const flagged = rows.filter((r) => r.manipulation_flags.length);
        return (
          <Page title="Social Media" intro={<>Erwähnungen auf rechtlich zugänglichen Plattformen. {d.note} Social Media erhöht nie den Quality Score.</>}>
            <Panel>
              <DataTable rows={rows} rowKey={(r) => r.symbol} initialSort={{ key: "m7", dir: -1 }}
                empty="Keine Social-Media-Daten. Erwähnungen werden über social_mentions.csv importiert."
                cols={[
                  { key: "sym", label: "Aktie", render: (r) => <CompanyLink symbol={r.symbol} />, sort: (r) => r.symbol },
                  { key: "m24", label: "24 Std.", num: true, render: (r) => r.mentions_24h, sort: (r) => r.mentions_24h },
                  { key: "m7", label: "7 Tage", num: true, render: (r) => r.mentions_7d, sort: (r) => r.mentions_7d },
                  { key: "chg", label: "vs. Basis", num: true, render: (r) => fmt.pct(r.change_vs_baseline_pct, 0), sort: (r) => r.change_vs_baseline_pct },
                  { key: "eng", label: "Interaktionen 7 T.", num: true, render: (r) => fmt.num(r.engagement_7d, 0), sort: (r) => r.engagement_7d },
                  { key: "sent", label: "Sentiment (algorithmisch)", num: true, render: (r) => fmt.num(r.sentiment_7d, 2), sort: (r) => r.sentiment_7d },
                  { key: "pl", label: "Plattformen", render: (r) => r.platforms.join(", ") },
                  { key: "man", label: "Manipulation", render: (r) => <Tag tone={r.manipulation_risk === "hoch" ? "err" : r.manipulation_risk === "auffaellig" ? "warn" : "ok"}>{r.manipulation_risk === "auffaellig" ? "auffällig" : r.manipulation_risk}</Tag>, sort: (r) => r.manipulation_flags.length },
                ]} />
            </Panel>
            <Panel title="Manipulationshinweise" note="Verdachtsmuster, keine Feststellung. Koordinierte Wiederholungen, Konzentration auf wenige Accounts, Pump-Sprache und plötzliche Spitzen.">
              {flagged.length ? (
                <ul className="plain">{flagged.map((r) => (
                  <li key={r.symbol}><CompanyLink symbol={r.symbol} />: {r.manipulation_flags.join("; ")}
                    {r.top_posts[0] ? <div className="small muted">Beispiel: „{r.top_posts[0].text.slice(0, 140)}“ (<Src url={r.top_posts[0].url} label={r.top_posts[0].platform} />)</div> : null}</li>
                ))}</ul>
              ) : <Empty>Keine auffälligen Muster.</Empty>}
            </Panel>
          </Page>
        );
      }}
    </Gate>
  );
}
