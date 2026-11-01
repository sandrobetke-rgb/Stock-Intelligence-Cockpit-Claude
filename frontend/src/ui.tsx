import { ReactNode, useMemo, useState } from "react";
import { DIRECTION_LABEL, Loaded, VERIFICATION_LABEL, fmt } from "./data";
import type { CorpEvent, StockRow } from "./types";

// ---------------------------------------------------------------- Achsen --
type AxisKey = "q" | "m" | "p" | "r";
const AXES: { key: AxisKey; short: string; label: string }[] = [
  { key: "q", short: "Q", label: "Company Quality" },
  { key: "m", short: "M", label: "Market Intelligence" },
  { key: "p", short: "P", label: "Political Intelligence" },
  { key: "r", short: "R", label: "Risk" },
];

/** Vier getrennte Bewertungsachsen – bewusst nie zu einem Gesamtwert verrechnet. */
export function Axes({ q, m, p, r, compact = false, pDir }: {
  q: number | null; m: number | null; p: number | null; r: number | null; compact?: boolean; pDir?: string;
}) {
  const vals: Record<AxisKey, number | null> = { q, m, p, r };
  return (
    <div className={`axes ${compact ? "axes-compact" : ""}`} role="group" aria-label="Bewertungsachsen">
      {AXES.map((a) => {
        const v = vals[a.key];
        return (
          <div key={a.key} className={`axis axis-${a.key}`} title={`${a.label}: ${v == null ? "unbekannt" : fmt.num(v, 0)}`}>
            <span className="axis-name">{compact ? a.short : a.label}</span>
            <span className="axis-track">
              {v == null ? <span className="axis-unknown" /> : <span className="axis-fill" style={{ width: `${Math.max(2, v)}%` }} />}
            </span>
            <span className="axis-val">
              {v == null ? "?" : fmt.num(v, 0)}
              {a.key === "p" && pDir && pDir !== "keine" && v ? <DirArrow d={pDir} /> : null}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function stockAxes(s: StockRow) {
  return { q: s.quality.score, m: s.market_intelligence.score, p: s.political.relevance || 0, r: s.risk.score, pDir: s.political.direction };
}

export function DirArrow({ d }: { d: string }) {
  const sym = d === "positive" ? "▲" : d === "negative" ? "▼" : d === "mixed" ? "◆" : "";
  return sym ? <span className={`dir-arrow dir-${d}`} aria-label={DIRECTION_LABEL[d]}>{sym}</span> : null;
}

export function Direction({ d }: { d: string }) {
  return <span className={`tag dir dir-${d}`}><DirArrow d={d} /> {DIRECTION_LABEL[d] ?? d}</span>;
}

export function Verif({ v }: { v: string }) {
  return <span className={`tag verif v-${v.replace(/\s/g, "")}`}>{VERIFICATION_LABEL[v] ?? v}</span>;
}

/** Deutsche Übersetzung mit englischem Original darunter (Original bleibt maßgeblich). */
export function Translated({ de, orig, href, className }: { de?: string | null; orig: string; href?: string; className?: string }) {
  const main = de || orig;
  return (
    <>
      {href ? <a href={href} target="_blank" rel="noopener noreferrer" className={className}>{main}</a> : <span className={className}>{main}</span>}
      {de ? <span className="orig" lang="en"><span className="mt">maschinell übersetzt</span> Original: {orig}</span> : null}
    </>
  );
}

/** Hinweis auf anstehende Termine (Quartalszahlen, Ex-Dividende). */
export function EventBadges({ events, max = 2 }: { events?: CorpEvent[]; max?: number }) {
  const upcoming = (events ?? []).filter((e) => e.days_until >= -1).slice(0, max);
  if (!upcoming.length) return null;
  return (
    <span className="ev-badges">
      {upcoming.map((e) => {
        const when = e.days_until === 0 ? "heute" : e.days_until === 1 ? "morgen" : e.days_until === -1 ? "gestern" : `in ${e.days_until} T.`;
        const label = e.type === "earnings" ? `Zahlen ${when}` : `Ex-Div. ${when}`;
        const title = `${e.type === "earnings" ? "Quartalszahlen" : "Ex-Dividende"} am ${new Date(e.date).toLocaleDateString("de-DE", { timeZone: "UTC" })}`
          + (e.time ? `, ${e.time}` : "") + (e.confirmed === false ? " (geschätzt)" : "") + (e.amount ? `, ${e.amount} USD je Aktie` : "") + ` – Quelle: ${e.source}`;
        return <a key={e.type + e.date} href={e.source_url} target="_blank" rel="noopener noreferrer"
          className={`evb evb-${e.type} ${e.days_until <= 7 ? "soon" : ""}`} title={title}>{label}</a>;
      })}
    </span>
  );
}

export function Tag({ children, tone }: { children: ReactNode; tone?: string }) {
  return <span className={`tag ${tone ? "tone-" + tone : ""}`}>{children}</span>;
}

export function IndexTags({ idx }: { idx: string[] }) {
  return <span className="idx-tags">{idx.map((i) => <span key={i} className="idx">{i}</span>)}</span>;
}

export function CompanyLink({ symbol, name }: { symbol: string; name?: string }) {
  return (
    <a className="co-link" href={`#/company/${encodeURIComponent(symbol)}`}>
      <strong>{symbol}</strong>{name ? <span className="co-name"> {name}</span> : null}
    </a>
  );
}

export function Src({ url, label }: { url?: string | null; label?: string }) {
  if (!url) return <span className="muted">keine Quelle</span>;
  let host = label;
  if (!host) {
    try { host = new URL(url).hostname.replace(/^www\./, ""); } catch { host = url; }
  }
  return <a className="src" href={url} target="_blank" rel="noopener noreferrer">{host}</a>;
}

// ---------------------------------------------------------------- Layout --
export function Page({ title, intro, children, actions }: { title: string; intro?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="page">
      <header className="page-head">
        <div>
          <h1>{title}</h1>
          {intro ? <p className="intro">{intro}</p> : null}
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}

export function Panel({ title, children, note, className = "" }: { title?: string; children: ReactNode; note?: ReactNode; className?: string }) {
  return (
    <div className={`panel ${className}`}>
      {title ? <h2>{title}</h2> : null}
      {children}
      {note ? <p className="note">{note}</p> : null}
    </div>
  );
}

export function Gate<T>({ s, children }: { s: Loaded<T>; children: (d: T) => ReactNode }) {
  if (s.loading) return <p className="state">Daten werden geladen …</p>;
  if (s.error || !s.data) return <p className="state state-error">{s.error ?? "Keine Daten vorhanden."} Prüfe den letzten Pipeline-Lauf im Dashboard.</p>;
  return <>{children(s.data)}</>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

// --------------------------------------------------------------- Tabelle --
export type Col<T> = { key: string; label: string; render: (r: T) => ReactNode; sort?: (r: T) => number | string | null; num?: boolean; className?: string };

export function DataTable<T>({ rows, cols, initialSort, rowKey, limit = 200, empty }: {
  rows: T[]; cols: Col<T>[]; initialSort?: { key: string; dir: 1 | -1 }; rowKey: (r: T) => string; limit?: number; empty?: string;
}) {
  const [sort, setSort] = useState(initialSort ?? { key: "", dir: -1 as 1 | -1 });
  const [shown, setShown] = useState(limit);
  const sorted = useMemo(() => {
    const c = cols.find((x) => x.key === sort.key);
    if (!c?.sort) return rows;
    const get = c.sort;
    return [...rows].sort((a, b) => {
      const va = get(a), vb = get(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;   // unbekannte Werte immer ans Ende
      if (vb == null) return -1;
      return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
    });
  }, [rows, cols, sort]);
  if (!rows.length) return <Empty>{empty ?? "Keine Einträge für die aktuelle Auswahl."}</Empty>;
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.key} className={`${c.num ? "num" : ""} ${c.className ?? ""}`}
                aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : undefined}>
                {c.sort ? (
                  <button className="th-btn" onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? (-s.dir as 1 | -1) : -1 }))}>
                    {c.label}{sort.key === c.key ? (sort.dir === 1 ? " ↑" : " ↓") : ""}
                  </button>
                ) : c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.slice(0, shown).map((r) => (
            <tr key={rowKey(r)}>
              {cols.map((c) => <td key={c.key} className={`${c.num ? "num" : ""} ${c.className ?? ""}`}>{c.render(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {sorted.length > shown ? (
        <button className="more" onClick={() => setShown((n) => n + limit)}>
          Weitere {Math.min(limit, sorted.length - shown)} von {sorted.length - shown} anzeigen
        </button>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- Filter --
export type StockFilter = {
  q: string; index: string; region: string; sector: string; minQuality: number; minMI: number; minPol: number;
  risk: string; status: string;
};
export const emptyFilter: StockFilter = { q: "", index: "", region: "", sector: "", minQuality: 0, minMI: 0, minPol: 0, risk: "", status: "active" };

export function applyFilter(rows: StockRow[], f: StockFilter) {
  const q = f.q.trim().toLowerCase();
  return rows.filter((s) =>
    (!q || s.symbol.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)) &&
    (!f.index || s.indexes.includes(f.index)) &&
    (!f.region || s.region === f.region) &&
    (!f.sector || s.sector === f.sector) &&
    (!f.minQuality || (s.quality.score ?? -1) >= f.minQuality) &&
    (!f.minMI || (s.market_intelligence.score ?? -1) >= f.minMI) &&
    (!f.minPol || s.political.relevance >= f.minPol) &&
    (!f.risk || s.risk.level === f.risk) &&
    (!f.status || s.status === f.status));
}

export function StockFilters({ rows, f, set }: { rows: StockRow[]; f: StockFilter; set: (f: StockFilter) => void }) {
  const sectors = useMemo(() => [...new Set(rows.map((r) => r.sector).filter(Boolean) as string[])].sort(), [rows]);
  const regions = useMemo(() => [...new Set(rows.map((r) => r.region))].sort(), [rows]);
  const up = (k: keyof StockFilter) => (e: { target: { value: string } }) =>
    set({ ...f, [k]: typeof emptyFilter[k] === "number" ? Number(e.target.value) : e.target.value });
  return (
    <form className="filters" onSubmit={(e) => e.preventDefault()} aria-label="Filter">
      <label className="f-search">Suche<input type="search" value={f.q} onChange={up("q")} placeholder="Ticker oder Name" /></label>
      <label>Index<select value={f.index} onChange={up("index")}><option value="">Alle</option>{["NDX", "SPX", "RUT", "DAX"].map((i) => <option key={i}>{i}</option>)}</select></label>
      <label>Region<select value={f.region} onChange={up("region")}><option value="">Alle</option>{regions.map((r) => <option key={r}>{r}</option>)}</select></label>
      <label>Branche<select value={f.sector} onChange={up("sector")}><option value="">Alle</option>{sectors.map((r) => <option key={r}>{r}</option>)}</select></label>
      <label>Quality ab<input type="number" min={0} max={100} step={5} value={f.minQuality} onChange={up("minQuality")} /></label>
      <label>Market Int. ab<input type="number" min={0} max={100} step={5} value={f.minMI} onChange={up("minMI")} /></label>
      <label>Political ab<input type="number" min={0} max={100} step={5} value={f.minPol} onChange={up("minPol")} /></label>
      <label>Risikostufe<select value={f.risk} onChange={up("risk")}><option value="">Alle</option>{["niedrig", "moderat", "erhoeht", "hoch", "unbekannt"].map((r) => <option key={r} value={r}>{r === "erhoeht" ? "erhöht" : r}</option>)}</select></label>
      <label>Status<select value={f.status} onChange={up("status")}><option value="active">Aktives Universum</option><option value="archived">Archiviert</option><option value="">Alle</option></select></label>
      <button type="button" className="reset" onClick={() => set(emptyFilter)}>Filter zurücksetzen</button>
    </form>
  );
}

export function riskLabel(l: string) {
  return l === "erhoeht" ? "erhöht" : l;
}
