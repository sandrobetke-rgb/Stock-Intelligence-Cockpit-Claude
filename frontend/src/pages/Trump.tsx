import { useState } from "react";
import { MENTION_LABEL, fmt, useData } from "../data";
import type { Meta, TrumpMention } from "../types";
import { CompanyLink, Direction, Empty, Gate, Page, Panel, Src, Tag, Verif } from "../ui";

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
      <blockquote>{m.quote}</blockquote>
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
  const [showHistory, setShowHistory] = useState(false);
  return (
    <Gate s={s}>
      {(d) => {
        const active = d.mentions.filter((m) => m.bonus.active);
        const watch = d.mentions.filter((m) => !m.bonus.active && m.bonus.age_days != null && m.bonus.age_days <= d.rule.max_age_days);
        const history = d.mentions.filter((m) => !active.includes(m) && !watch.includes(m));
        return (
          <Page title="Trump Mention Radar" intro={d.rule.text}>
            <div className="rule">
              <div><b>{d.rule.max_age_days}</b><span>Kalendertage ab Originalaussage</span></div>
              {Object.entries(d.rule.bonus_levels).map(([k, v]) => (
                <div key={k}><b>{v ? `+${v}` : "0"}</b><span>{MENTION_LABEL[k]}</span></div>
              ))}
            </div>
            <Panel title={`Aktiver Sonderbonus (${active.length})`}>
              {active.length ? <div className="mentions">{active.map((m) => <MentionCard key={m.id} m={m} maxDays={d.rule.max_age_days} />)}</div>
                : <Empty>Keine verifizierte Unternehmensnennung der letzten {d.rule.max_age_days} Tage.</Empty>}
            </Panel>
            <Panel title={`Innerhalb der Frist, ohne Bonus (${watch.length})`} note="Branchen- und allgemeine Aussagen, unbestätigte Quellen oder ungeprüfte Zuordnungen erhalten keinen Unternehmensbonus.">
              {watch.length ? <div className="mentions">{watch.map((m) => <MentionCard key={m.id} m={m} maxDays={d.rule.max_age_days} />)}</div> : <Empty>Keine weiteren Aussagen in der Frist.</Empty>}
            </Panel>
            <Panel title={`Historie (${history.length})`} note="Verfallene Aussagen bleiben für die Recherche sichtbar, zählen aber nicht mehr als aktuelles Sondersignal.">
              {history.length ? (
                showHistory ? <div className="mentions">{history.map((m) => <MentionCard key={m.id} m={m} maxDays={d.rule.max_age_days} />)}</div>
                  : <button className="more" onClick={() => setShowHistory(true)}>Historie anzeigen</button>
              ) : <Empty>Noch keine Historie.</Empty>}
            </Panel>
          </Page>
        );
      }}
    </Gate>
  );
}
