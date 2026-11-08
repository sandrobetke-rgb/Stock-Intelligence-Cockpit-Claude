import { useState } from "react";
import { MENTION_LABEL, fmt, useData } from "../data";
import type { Meta, TrumpMention } from "../types";
import { CompanyLink, DataTable, Direction, Empty, Gate, Page, Panel, Src, Tag, Verif } from "../ui";

type TM = Meta & { rule: { max_age_days: number; bonus_levels: Record<string, number>; text: string }; mentions: TrumpMention[] };

function Countdown({ m, maxDays }: { m: TrumpMention; maxDays: number }) {
  const age = m.bonus.age_days ?? maxDays;
  const left = Math.max(0, maxDays - age);
  return (
    <div className="countdown" aria-label={`${fmt.num(left, 1)} von ${maxDays} Tagen verbleibend`}>
      <span className="cd-track">{Array.from({ length: maxDays }, (_, i) => (
        <span key={i} className={`cd-day ${i < Math.floor(left) ? "on" : i < left ? "part" : ""}`} />
      ))}</span>
      <span className="small">Verfällt {fmt.dt(m.bonus.expires_at)}</span>
    </div>
  );
}

function MentionCard({ m, maxDays }: { m: TrumpMention; maxDays: number }) {
  return (
    <article className={`mention ${m.bonus.active ? "is-active" : ""} dirb-${m.direction}`}>
      <header>
        {m.symbol ? <CompanyLink symbol={m.symbol} /> : <span className="muted">{m.sectors.length ? `Branche: ${m.sectors.join(", ")}` : "Ohne Unternehmensbezug"}</span>}
        <Tag>{MENTION_LABEL[m.mention_type]}</Tag>
        <Direction d={m.direction} />
        <Verif v={m.verification} />
        {m.bonus.active ? <span className="bonus">Sonderbonus +{m.bonus.value}</span> : null}
      </header>
      <blockquote lang="en">{m.quote}{m.quote_de ? <span className="orig quote-de" lang="de"><span className="mt">maschinell übersetzt</span> {m.quote_de}</span> : null}</blockquote>
      <dl className="facts">
        <div><dt>Originalzeitpunkt</dt><dd>{fmt.dt(m.statement_at, m.date_only)}{m.date_only ? <span className="warn-text"> – Uhrzeit unsicher</span> : null}</dd></div>
        <div><dt>Quelle</dt><dd><Src url={m.source_url} label={m.source_name} /></dd></div>
        <div><dt>Zuordnung</dt><dd>{m.matched && m.matched !== "manuell" ? `„${m.matched}“, ` : ""}{m.mapping_rationale ?? (m.matched ? "" : "–")}{m.symbol && !m.mapping_verified ? <span className="warn-text"> – nicht geprüft</span> : null}</dd></div>
        <div><dt>Wirkungsrichtung</dt><dd>{m.direction_basis === "manual" ? "manuell eingeordnet" : "algorithmisch"}{m.direction_cues.length ? ` (${m.direction_cues.join(", ")})` : ""}</dd></div>
        <div><dt>Bonusstatus</dt><dd>{m.bonus.reason}</dd></div>
      </dl>
      {m.bonus.active ? <Countdown m={m} maxDays={maxDays} /> : null}
    </article>
  );
}

export function Trump() {
  const s = useData<TM>("trump-mentions.json");
  const [showGeneral, setShowGeneral] = useState(false);
  return (
    <Gate s={s}>
      {(d) => {
        const max = d.rule.max_age_days;
        const stocks = d.mentions.filter((m) => m.symbol && m.mapping_verified);
        const general = d.mentions.filter((m) => !m.symbol || !m.mapping_verified);
        const inWindow = stocks.filter((m) => m.bonus.age_days != null && m.bonus.age_days <= max).length;
        return (
          <Page title="Trump Mention Radar" intro={`Aktien, die Trump bzw. das Weiße Haus genannt hat. Sonderbonus nur bei verifizierter Nennung innerhalb von ${max} Kalendertagen ab Originalaussage (direkt +${d.rule.bonus_levels.direct ?? 30}, eindeutig indirekt +${d.rule.bonus_levels.indirect ?? 15}). Erhöht nie den Company Quality Score.`}>
            <Panel title={`Genannte Aktien (${stocks.length}, davon ${inWindow} in der ${max}-Tage-Frist)`}>
              <DataTable rows={stocks} rowKey={(m) => m.id} initialSort={{ key: "t", dir: -1 }}
                empty="In den letzten 90 Tagen wurde keine Aktie aus dem Universum gesichert genannt."
                cols={[
                  { key: "sym", label: "Aktie", render: (m) => <CompanyLink symbol={m.symbol!} />, sort: (m) => m.symbol },
                  { key: "t", label: "Aussage vom", render: (m) => fmt.dt(m.statement_at, m.date_only), sort: (m) => m.statement_at },
                  { key: "dir", label: "Richtung", render: (m) => <Direction d={m.direction} />, sort: (m) => m.direction },
                  { key: "typ", label: "Art", render: (m) => MENTION_LABEL[m.mention_type], sort: (m) => m.mention_type },
                  { key: "b", label: "Bonus", render: (m) => m.bonus.active
                      ? <span className="bonus">+{m.bonus.value} · noch {fmt.num(Math.max(0, max - (m.bonus.age_days ?? max)), 1)} T.</span>
                      : <span className="muted small">{m.bonus.age_days != null && m.bonus.age_days > max ? "verfallen" : "kein Bonus"}</span>,
                    sort: (m) => (m.bonus.active ? m.bonus.value : 0) },
                  { key: "v", label: "Prüfung", render: (m) => <><Verif v={m.verification} /></> },
                  { key: "q", label: "Quelle", render: (m) => <span title={m.quote_de ?? m.quote}><Src url={m.source_url} label={m.source_name} /></span> },
                ]} />
            </Panel>
            <Panel title={`Aussagen ohne gesicherten Aktienbezug (${general.length})`} note="Allgemeine und Branchen-Aussagen sowie ungeprüfte Wortzufälle (z. B. „news“, „gold“) – ausgeblendet.">
              {general.length ? (showGeneral
                ? <div className="mentions">{general.map((m) => <MentionCard key={m.id} m={m} maxDays={max} />)}</div>
                : <button className="more" onClick={() => setShowGeneral(true)}>Trotzdem anzeigen</button>)
                : <Empty>Keine.</Empty>}
            </Panel>
          </Page>
        );
      }}
    </Gate>
  );
}
