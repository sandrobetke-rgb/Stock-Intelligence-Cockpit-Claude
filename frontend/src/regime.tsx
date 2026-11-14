import { useState } from "react";
import { fmt, useData } from "./data";
import type { Meta } from "./types";

export interface RegimeLight { key: string; name: string; level: "green" | "yellow" | "red"; value: number; date: string | null; text: string; weight: number }
export interface Regime extends Meta { overall: "green" | "yellow" | "red" | null; label: string; hint: string; score_pct: number | null; lights: RegimeLight[] }

const DOT: Record<string, string> = { green: "🟢", yellow: "🟡", red: "🔴" };

/** Marktampel: Umfeld für neue Long-Swings (S&P 500, Nasdaq, DAX, VIX, Zinskurve, Marktbreite). */
export function MarketLight({ compact = false }: { compact?: boolean }) {
  const s = useData<Regime>("regime.json");
  const [open, setOpen] = useState(!compact);
  const r = s.data;
  if (!r || !r.overall) return null;
  return (
    <section className={`regime regime-${r.overall}`} aria-label="Marktampel">
      <button className="regime-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="regime-dot" aria-hidden>{DOT[r.overall]}</span>
        <span><strong>Marktampel: {r.label}</strong> <span className="small">({r.score_pct} %)</span><br /><span className="small">{r.hint}</span></span>
        <span className="small muted regime-toggle">{open ? "weniger" : "Details"}</span>
      </button>
      {open ? (
        <ul className="regime-list">
          {r.lights.map((l) => (
            <li key={l.key}>
              <span aria-hidden>{DOT[l.level]}</span> <strong>{l.name}</strong>
              {l.key === "breadth" ? null : <> {fmt.num(l.value, l.key === "curve" ? 2 : l.key === "^VIX" ? 1 : 0)}{l.key === "curve" ? " %-Pkt." : ""}</>}
              <span className="muted"> – {l.text}</span>
            </li>
          ))}
          <li className="small muted">Einordnung des Umfelds nach festen Regeln, keine Prognose. Stand {fmt.dt(r.generated_at)}.</li>
        </ul>
      ) : null}
    </section>
  );
}
