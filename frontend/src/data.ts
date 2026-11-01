import { useEffect, useState } from "react";

const BASE = import.meta.env.BASE_URL;
let root: Promise<string> | null = null;

/** Live-Daten unter data/, sonst Fallback auf DEMO-Daten (mit Warnbanner). */
function dataRoot(): Promise<string> {
  if (!root) {
    root = fetch(`${BASE}data/summary.json`, { cache: "no-store" })
      .then((r) => (r.ok ? `${BASE}data/` : `${BASE}demo-data/`))
      .catch(() => `${BASE}demo-data/`);
  }
  return root;
}

const cache = new Map<string, Promise<unknown>>();

export function load<T>(file: string): Promise<T> {
  if (!cache.has(file)) {
    cache.set(
      file,
      dataRoot().then(async (r) => {
        const res = await fetch(r + file, { cache: "no-store" });
        if (!res.ok) throw new Error(`${file} konnte nicht geladen werden (HTTP ${res.status}).`);
        return res.json();
      }),
    );
  }
  return cache.get(file) as Promise<T>;
}

export type Loaded<T> = { data?: T; error?: string; loading: boolean };

export function useData<T>(file: string | null): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({ loading: true });
  useEffect(() => {
    if (!file) return;
    let alive = true;
    setState({ loading: true });
    load<T>(file)
      .then((data) => alive && setState({ data, loading: false }))
      .catch((e: Error) => alive && setState({ error: e.message, loading: false }));
    return () => {
      alive = false;
    };
  }, [file]);
  return state;
}

// ----------------------------------------------------------- Formatierung --
const nf = (d: number) => new Intl.NumberFormat("de-DE", { maximumFractionDigits: d, minimumFractionDigits: d });

export const fmt = {
  num: (v: number | null | undefined, d = 1) => (v == null ? "–" : nf(d).format(v)),
  pct: (v: number | null | undefined, d = 1, sign = true) =>
    v == null ? "–" : `${sign && v > 0 ? "+" : ""}${nf(d).format(v)} %`,
  big: (v: number | null | undefined, cur?: string | null) => {
    if (v == null) return "–";
    const a = Math.abs(v);
    const [n, u] = a >= 1e12 ? [v / 1e12, " Bio."] : a >= 1e9 ? [v / 1e9, " Mrd."] : a >= 1e6 ? [v / 1e6, " Mio."] : a >= 1e3 ? [v / 1e3, " Tsd."] : [v, ""];
    return `${nf(a >= 1e3 ? 1 : 0).format(n)}${u}${cur ? " " + cur : ""}`;
  },
  dt: (iso: string | null | undefined, dateOnly = false) => {
    if (!iso) return "Datum unbekannt";
    const d = new Date(iso);
    if (dateOnly) return d.toLocaleDateString("de-DE", { timeZone: "UTC", day: "2-digit", month: "2-digit", year: "numeric" }) + " (nur Datum)";
    return d.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
  },
  date: (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" }) : "–"),
  rel: (iso: string | null | undefined) => {
    if (!iso) return "";
    const h = (Date.now() - new Date(iso).getTime()) / 36e5;
    if (h < 0) {
      const f = -h;
      return f < 48 ? `in ${Math.round(f)} Std.` : `in ${Math.round(f / 24)} Tagen`;
    }
    return h < 1 ? "vor < 1 Std." : h < 48 ? `vor ${Math.round(h)} Std.` : `vor ${Math.round(h / 24)} Tagen`;
  },
};

export const INDEX_NAMES: Record<string, string> = { NDX: "Nasdaq 100", SPX: "S&P 500", RUT: "Russell 2000", DAX: "DAX 40" };

export const DIRECTION_LABEL: Record<string, string> = {
  positive: "positiv", negative: "negativ", mixed: "gemischt", neutral: "neutral", unclear: "unklar", keine: "kein Signal",
};
export const VERIFICATION_LABEL: Record<string, string> = {
  Verified: "Bestätigt", "Partially Verified": "Teilweise bestätigt", Unverified: "Unbestätigt",
  Disputed: "Strittig", False: "Falsch", Outdated: "Veraltet",
};
export const STATUS_LABEL: Record<string, string> = {
  planned: "Geplant", published: "Veröffentlicht", occurred: "Erfolgt", postponed: "Verschoben", cancelled: "Abgesagt",
};
export const DRIVER_LABEL: Record<string, string> = {
  news_flow: "Nachrichtenfluss", freshness: "Aktualität (24 Std.)", source_diversity: "Quellenvielfalt",
  primary_sources: "Primärquellen", analyst_activity: "Analystenänderungen", price_volume_anomaly: "Kurs-/Volumenauffälligkeit",
  social_attention: "Social Media", insider_activity: "Insideraktivität",
};
export const MENTION_LABEL: Record<string, string> = {
  direct: "Direkte Nennung", indirect: "Eindeutig indirekt", sector: "Branchenbezogen", general: "Allgemein",
};

export const SI_ACTION: Record<string, string> = {
  new: "Neukauf", increased: "Aufgestockt", reduced: "Reduziert", unchanged: "Unverändert", sold_out: "Komplett verkauft", unknown: "Gehalten",
};
export const SI_TONE: Record<string, string | undefined> = { new: "ok", increased: "ok", reduced: "warn", sold_out: "err" };

/** Externe Recherche-Links (nur Verlinkung, keine automatische Datenübernahme). */
export function researchLinks(symbol: string, region: string) {
  const s = symbol.replace(/\.DE$/, "");
  const us = region === "US";
  return [
    us && { label: "Dataroma", url: `https://www.dataroma.com/m/stock.php?sym=${encodeURIComponent(s.replace("-", "."))}` },
    us && { label: "WhaleWisdom", url: `https://whalewisdom.com/stock/${encodeURIComponent(s.toLowerCase())}` },
    us && { label: "OpenInsider", url: `http://openinsider.com/screener?s=${encodeURIComponent(s)}` },
    us && { label: "Finviz", url: `https://finviz.com/quote.ashx?t=${encodeURIComponent(s)}` },
    us && { label: "SEC EDGAR", url: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${encodeURIComponent(s)}&type=&dateb=&owner=include&count=40` },
    { label: "Yahoo Finance", url: `https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}` },
    { label: "Macrotrends", url: `https://www.macrotrends.net/stocks/charts/${encodeURIComponent(s)}/` },
  ].filter(Boolean) as { label: string; url: string }[];
}

// ------------------------------------------------------------- Watchlist --
const WL_KEY = "sic-watchlist";

function readWl(): string[] {
  try { return JSON.parse(localStorage.getItem(WL_KEY) || "[]"); } catch { return []; }
}

export function useWatchlist() {
  const [wl, setWl] = useState<string[]>(readWl);
  useEffect(() => {
    const h = () => setWl(readWl());
    window.addEventListener("sic-watchlist", h);
    window.addEventListener("storage", h);
    return () => { window.removeEventListener("sic-watchlist", h); window.removeEventListener("storage", h); };
  }, []);
  const save = (next: string[]) => {
    const v = [...new Set(next)].sort();
    try { localStorage.setItem(WL_KEY, JSON.stringify(v)); } catch { /* privater Modus */ }
    setWl(v);
    window.dispatchEvent(new Event("sic-watchlist"));
  };
  return {
    list: wl,
    has: (s: string) => wl.includes(s),
    toggle: (s: string) => save(wl.includes(s) ? wl.filter((x) => x !== s) : [...wl, s]),
    replace: (l: string[]) => save(l),
  };
}

/** GitHub-Repo aus der Pages-Adresse ableiten (owner.github.io/repo/). */
export function repoInfo() {
  const gh = location.hostname.endsWith(".github.io");
  return { owner: gh ? location.hostname.split(".")[0] : "sandrobetke-rgb", repo: gh ? location.pathname.split("/")[1] : "Stock-Intelligence-Cockpit-Claude" };
}

/** Öffnet GitHub mit einer neuen, vorausgefüllten Watchlist-Datei (Speichern = 1 Klick auf "Commit"). */
export function githubWatchlistUrl(symbols: string[]) {
  const { owner, repo } = repoInfo();
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
  const content = ["symbol", ...symbols].join("\n") + "\n";
  return `https://github.com/${owner}/${repo}/new/main?filename=${encodeURIComponent(`backend/data/imports/watchlist/${stamp}.csv`)}&value=${encodeURIComponent(content)}&message=${encodeURIComponent("Watchlist aktualisiert")}`;
}

// ------------------------------------------------------------ Qualität --
type QMap = Record<string, [number | null, number]>;
let qPromise: Promise<QMap> | null = null;

/** Company-Quality-Score je Aktie (für Kennzeichnung und Filter auf allen Seiten). */
export function useQuality(): QMap | null {
  const [q, setQ] = useState<QMap | null>(null);
  useEffect(() => {
    if (!qPromise) qPromise = load<{ q: QMap }>("quality-map.json").then((d) => d.q).catch(() => ({}));
    let alive = true;
    qPromise.then((m) => alive && setQ(m));
    return () => { alive = false; };
  }, []);
  return q;
}

export function qualityGrade(score: number | null | undefined): { label: string; tone: string } {
  if (score == null) return { label: "?", tone: "qn" };
  if (score >= 80) return { label: "A", tone: "qa" };
  if (score >= 65) return { label: "B", tone: "qb" };
  if (score >= 50) return { label: "C", tone: "qc" };
  if (score >= 35) return { label: "D", tone: "qd" };
  return { label: "E", tone: "qe" };
}
