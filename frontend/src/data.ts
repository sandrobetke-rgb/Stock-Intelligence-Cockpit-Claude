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
