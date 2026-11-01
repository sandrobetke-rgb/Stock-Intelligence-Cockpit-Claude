import { useState } from "react";
import { fmt, useData } from "../data";
import type { Attention, Meta, SocialStat } from "../types";
import { CompanyLink, DataTable, Empty, Gate, Page, Panel, QualitySelect, Src, Tag, useQualityFilter } from "../ui";

type So = Meta & { stocks: Record<string, SocialStat>; note: string;
  sources?: { source: string; mode: string; posts: number; status: string; errors?: string[] }[];
  stocktwits_trending?: { rank: number; symbol: string; title?: string; in_universe: boolean }[];
  attention?: Record<string, Attention> };

export function SocialPage() {
  const s = useData<So>("social.json");
  const [minQ, setMinQ] = useState(0);
  const passQ = useQualityFilter(minQ);
  return (
    <Gate s={s}>
      {(d) => {
        const rows = Object.entries(d.stocks).map(([symbol, v]) => ({ symbol, ...v })).filter((r) => passQ(r.symbol));
        const flagged = rows.filter((r) => r.manipulation_flags.length);
        const att = Object.entries(d.attention ?? {}).map(([symbol, v]) => ({ symbol, ...v }))
          .filter((r) => passQ(r.symbol) && (r.ratio_1d ?? 0) >= 1.5 && r.views_1d >= 1000);
        return (
          <Page title="Social Media" intro={<>Erwähnungen auf rechtlich zugänglichen Plattformen. {d.note} Social Media erhöht nie den Quality Score.</>}>
            {d.stocktwits_trending?.length ? (
              <Panel title="Gerade im Trend auf StockTwits">
                <div className="trend">{d.stocktwits_trending.slice(0, 30).map((t) => (
                  <span key={t.symbol}>{t.in_universe ? <CompanyLink symbol={t.symbol} /> : <strong>{t.symbol}</strong>}<span className="muted small"> {t.title}</span></span>
                ))}</div>
              </Panel>
            ) : null}
            <Panel>
              <div className="filters inline"><QualitySelect value={minQ} onChange={setMinQ} /></div>
              <DataTable rows={rows} rowKey={(r) => r.symbol} initialSort={{ key: "m7", dir: -1 }}
                empty="Keine Social-Media-Daten. Erwähnungen werden über social_mentions.csv importiert."
                cols={[
                  { key: "sym", label: "Aktie", render: (r) => <CompanyLink symbol={r.symbol} />, sort: (r) => r.symbol },
                  { key: "m24", label: "24 Std.", num: true, render: (r) => r.mentions_24h, sort: (r) => r.mentions_24h },
                  { key: "m7", label: "7 Tage", num: true, render: (r) => r.mentions_7d, sort: (r) => r.mentions_7d },
                  { key: "chg", label: "vs. Basis", num: true, render: (r) => fmt.pct(r.change_vs_baseline_pct, 0), sort: (r) => r.change_vs_baseline_pct },
                  { key: "eng", label: "Interaktionen 7 T.", num: true, render: (r) => fmt.num(r.engagement_7d, 0), sort: (r) => r.engagement_7d },
                  { key: "sent", label: "Stimmung", num: true, render: (r) => <span className={(r.sentiment_7d ?? 0) > 0.15 ? "pos" : (r.sentiment_7d ?? 0) < -0.15 ? "neg" : ""}>{fmt.num(r.sentiment_7d, 2)}</span>, sort: (r) => r.sentiment_7d },
                  { key: "bb", label: "Bullish / Bearish", num: true, render: (r) => r.bullish_7d || r.bearish_7d ? <><span className="pos">{r.bullish_7d}</span> / <span className="neg">{r.bearish_7d}</span></> : "–", sort: (r) => (r.bullish_7d ?? 0) - (r.bearish_7d ?? 0) },
                  { key: "pl", label: "Wo", render: (r) => Object.entries(r.communities_7d ?? {}).slice(0, 3).map(([k, v]) => <Tag key={k}>{k} {v}</Tag>) },
                  { key: "man", label: "Manipulation", render: (r) => <Tag tone={r.manipulation_risk === "hoch" ? "err" : r.manipulation_risk === "auffaellig" ? "warn" : "ok"}>{r.manipulation_risk === "auffaellig" ? "auffällig" : r.manipulation_risk}</Tag>, sort: (r) => r.manipulation_flags.length },
                ]} />
            </Panel>
            <Panel title="Wikipedia-Aufmerksamkeit" note="Tägliche Aufrufe des Unternehmensartikels (englische Wikipedia) gegenüber dem 30-Tage-Schnitt. Zeigt breites öffentliches Interesse – die Ursache kann positiv oder negativ sein. Gezeigt: mindestens 1,5-fach und 1.000 Aufrufe.">
              <DataTable rows={att} rowKey={(r) => r.symbol} initialSort={{ key: "r1", dir: -1 }}
                empty="Keine auffälligen Anstiege (oder noch keine Daten – werden beim nächsten vollständigen Lauf geladen)."
                cols={[
                  { key: "sym", label: "Aktie", render: (r) => <CompanyLink symbol={r.symbol} />, sort: (r) => r.symbol },
                  { key: "v1", label: "Aufrufe", num: true, render: (r) => fmt.num(r.views_1d, 0), sort: (r) => r.views_1d },
                  { key: "b", label: "Schnitt 30 T.", num: true, render: (r) => fmt.num(r.avg_30d, 0), sort: (r) => r.avg_30d },
                  { key: "r1", label: "Faktor Tag", num: true, render: (r) => <span className={r.spike ? "pos" : ""}>{fmt.num(r.ratio_1d, 1)}×</span>, sort: (r) => r.ratio_1d },
                  { key: "r7", label: "Faktor 7 T.", num: true, render: (r) => `${fmt.num(r.ratio_7d, 1)}×`, sort: (r) => r.ratio_7d },
                  { key: "d", label: "Tag", render: (r) => r.date, sort: (r) => r.date },
                  { key: "a", label: "Artikel", render: (r) => <Src url={r.url} label={r.title} /> },
                ]} />
            </Panel>
            <Panel title="Quellen">
              <ul className="plain small">{(d.sources ?? []).map((x) => <li key={x.source}>{x.source} ({x.mode}): {x.status === "ok" ? <Tag tone="ok">ok</Tag> : x.status === "off" ? <Tag tone="warn">abgeschaltet</Tag> : <Tag tone="err">Fehler</Tag>} {x.posts} {x.source.startsWith("Wikipedia") ? "Unternehmensartikel" : "neue Beiträge mit Aktienbezug"}{x.errors?.length ? <span className="muted"> – {x.errors.slice(0, 2).join("; ")}</span> : null}</li>)}</ul>
              <p className="note">Stimmung: −1 = durchweg negativ, +1 = durchweg positiv. Bei StockTwits zählt die Bullish/Bearish-Angabe der Verfasser, sonst eine Wortliste. X (Twitter) ist nicht angebunden, weil die Schnittstelle kostenpflichtig ist. Reddit stellt seine freien Zugänge im November 2026 ein.</p>
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
