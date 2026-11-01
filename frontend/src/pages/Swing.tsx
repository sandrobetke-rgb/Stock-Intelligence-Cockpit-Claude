import { useMemo, useState } from "react";
import { fmt, useData } from "../data";
import type { StockRow, SwingMeta } from "../types";
import { CompanyLink, DataTable, EventBadges, Gate, Page, Panel, Tag } from "../ui";
import type { Stocks } from "./QualityStocks";

const CAP_KEY = "sic-capital";

function readCap(): number {
  try { return Number(localStorage.getItem(CAP_KEY)) || 0; } catch { return 0; }
}

export function sizing(trigger: number, risk: number, capital: number, riskPct: number, maxPos: number) {
  if (!capital || !risk) return null;
  const byRisk = Math.floor((capital * riskPct / 100) / risk);
  const byCap = Math.floor(capital / maxPos / trigger);
  return Math.max(0, Math.min(byRisk, byCap));
}

export function SwingPage() {
  const s = useData<Stocks>("stocks.json");
  const m = useData<SwingMeta>("swing.json");
  return <Gate s={s}>{(d) => <Gate s={m}>{(meta) => <SwingView rows={d.stocks} meta={meta} />}</Gate>}</Gate>;
}

function SwingView({ rows, meta }: { rows: StockRow[]; meta: SwingMeta }) {
  const [setup, setSetup] = useState<string>("ALL");
  const [onlyFilter, setOnlyFilter] = useState(true);
  const [noEarnings, setNoEarnings] = useState(true);
  const [minQ, setMinQ] = useState(0);
  const [capital, setCapital] = useState(readCap);
  const list = useMemo(() => rows.filter((r) => r.status === "active" && r.swing?.hits.length
    && (setup === "ALL" || r.swing.hits.includes(setup))
    && (!onlyFilter || r.swing.filter_pass || (setup !== "ALL" && !setup.startsWith("S0")))
    && (!noEarnings || !(r.events ?? []).some((e) => e.type === "earnings" && e.days_until >= 0 && e.days_until <= 5))
    && (!minQ || (r.quality.score ?? -1) >= minQ)), [rows, setup, onlyFilter, noEarnings, minQ]);
  const counts = useMemo(() => Object.fromEntries(Object.keys(meta.setups).map((k) => [k, rows.filter((r) => r.swing?.hits.includes(k)).length])), [rows, meta]);
  const tomorrowFriday = new Date().getDay() === 4;
  const isFriday = new Date().getDay() === 5;
  const f = meta.filter;
  return (
    <Page title="Swing-Setups"
      intro={<>Deine Screener S01–S04 und deine Strategien (Daily Swing Master, Überdehnter Rücksetzer, Momentum-Breakout; regelbasierte Annäherung, bitte im Chart gegenprüfen) auf Tagesbasis nach US-Börsenschluss ({fmt.date(rows.find((r) => r.market.price_date)?.market.price_date)}), mit Abendfilter und Einstiegsplan für den nächsten Handelstag.
        Der Einstieg selbst bleibt deine Regel im Chart: 1H-Kerze schließt ab 16:00 MEZ über dem Auslöser, höchstens {meta.entry.max_above_trigger_pct} % darüber.</>}>
      {tomorrowFriday || isFriday ? <p className="state state-warn">{isFriday ? "Heute ist Freitag" : "Morgen ist Freitag"}: laut deinen Regeln keine neuen Trades. Die Liste gilt dann für Montag.</p> : null}
      <div className="filters">
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={setup === "ALL"} className={`tab ${setup === "ALL" ? "sel" : ""}`} onClick={() => setSetup("ALL")}>Alle</button>
          {Object.entries(meta.setups).map(([k, v]) => (
            <button key={k} role="tab" aria-selected={setup === k} className={`tab ${setup === k ? "sel" : ""}`} onClick={() => setSetup(k)} title={v.text}>{v.name} ({counts[k]})</button>
          ))}
        </div>
        <label className="check"><input type="checkbox" checked={onlyFilter} onChange={(e) => setOnlyFilter(e.target.checked)} /> Abendfilter für S01–S04 (grün, RelVol ≥ {fmt.num(f.rvol_min, 1)}, RSI ≤ {f.rsi_max}, ATR% {fmt.num(f.atr_pct_min, 1)}–{fmt.num(f.atr_pct_max, 0)}, über EMA 200)</label>
        <label className="check"><input type="checkbox" checked={noEarnings} onChange={(e) => setNoEarnings(e.target.checked)} /> Keine Zahlen in den nächsten 5 Tagen</label>
        <label>Quality ab<input type="number" min={0} max={100} step={10} value={minQ} onChange={(e) => setMinQ(Number(e.target.value))} /></label>
        <label>Kapital (für Stückzahl)<input type="number" min={0} step={1000} value={capital || ""} placeholder="z. B. 25000"
          onChange={(e) => { const v = Number(e.target.value); setCapital(v); try { localStorage.setItem(CAP_KEY, String(v)); } catch { /* */ } }} /></label>
      </div>
      {setup !== "ALL" ? <p className="note">{meta.setups[setup].text}</p> : null}
      <Panel title={`${list.length} Kandidaten`} note={<>Stopp = Auslöser − {meta.entry.stop_atr} × ATR, Ziel 1 = {meta.entry.rrr}:1 (dort 50 % verkaufen). Stückzahl: {meta.entry.risk_pct} % Risiko vom Kapital, höchstens Kapital ÷ {meta.entry.max_positions}. Kein Kandidat ist auch ein gültiges Ergebnis.</>}>
        <DataTable rows={list} rowKey={(r) => r.symbol} initialSort={{ key: "rv", dir: -1 }} limit={60} empty="Heute erfüllt keine Aktie die gewählten Bedingungen."
          cols={[
            { key: "s", label: "Aktie", render: (r) => <><CompanyLink symbol={r.symbol} name={r.name} /><div>{r.swing!.hits.map((h) => <Tag key={h} tone="hi">{h}</Tag>)}<EventBadges events={r.events} /></div></>, sort: (r) => r.symbol },
            { key: "rv", label: "RelVol", num: true, render: (r) => fmt.num(r.swing!.tech.rvol as number, 2), sort: (r) => r.swing!.tech.rvol as number },
            { key: "rsi", label: "RSI", num: true, render: (r) => fmt.num(r.swing!.tech.rsi14 as number, 0), sort: (r) => r.swing!.tech.rsi14 as number },
            { key: "atr", label: "ATR %", num: true, render: (r) => fmt.num(r.swing!.tech.atr_pct as number, 1), sort: (r) => r.swing!.tech.atr_pct as number },
            { key: "e200", label: "zu EMA 200", num: true, render: (r) => fmt.pct(r.swing!.tech.dist_ema200_pct as number, 1), sort: (r) => r.swing!.tech.dist_ema200_pct as number },
            { key: "tr", label: "Auslöser / max.", num: true, render: (r) => <>{fmt.num(r.swing!.plan.trigger, 2)}<div className="small muted">bis {fmt.num(r.swing!.plan.entry_max, 2)}</div></>, sort: (r) => r.swing!.plan.trigger },
            { key: "st", label: "Stopp", num: true, render: (r) => <span className="neg">{fmt.num(r.swing!.plan.stop, 2)}</span> },
            { key: "tg", label: "Ziel 1", num: true, render: (r) => <span className="pos">{fmt.num(r.swing!.plan.target_1, 2)}</span> },
            { key: "n", label: "Stück", num: true, render: (r) => { const n = sizing(r.swing!.plan.trigger, r.swing!.plan.risk_per_share, capital, meta.entry.risk_pct, meta.entry.max_positions); return n == null ? "–" : fmt.num(n, 0); } },
            { key: "ctx", label: "Weitere Signale", render: (r) => <Context r={r} /> },
          ]} />
      </Panel>
    </Page>
  );
}

/** Zusätzliche, getrennte Signale als Kontext (keine Verrechnung mit dem Setup). */
function Context({ r }: { r: StockRow }) {
  const t: JSX.Element[] = [];
  if (r.quality.score != null) t.push(<Tag key="q" tone={r.quality.score >= 70 ? "ok" : undefined}>Quality {fmt.num(r.quality.score, 0)}</Tag>);
  if (r.insider.open_market_buys) t.push(<Tag key="i" tone="ok">Insiderkäufe {r.insider.open_market_buys}</Tag>);
  if (r.superinvestors?.buyers) t.push(<Tag key="si" tone="ok">Superinvestoren +{r.superinvestors.buyers}</Tag>);
  if (r.politicians?.buys) t.push(<Tag key="p" tone="ok">Politiker kaufen {r.politicians.buys}</Tag>);
  if (r.risk.level === "hoch" || r.risk.level === "erhoeht") t.push(<Tag key="r" tone="warn">Risiko {r.risk.level === "erhoeht" ? "erhöht" : "hoch"}</Tag>);
  if (r.social?.manipulation_risk === "hoch") t.push(<Tag key="so" tone="err">Social-Hype</Tag>);
  return <>{t}</>;
}
