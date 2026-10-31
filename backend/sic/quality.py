"""Company Quality Score (Lastenheft Kap. 4).

Ausschliesslich fundamentale Merkmale. News, Social Media, Trump-Erwähnungen und
technische Kursindikatoren werden hier bewusst NICHT importiert.

- Fehlende Daten -> 'unknown' (weder bestanden noch negativ); Gewicht wird umverteilt
- Datenabdeckung in Prozent wird ausgewiesen
- Finanzunternehmen erhalten ein angepasstes Kennzahlenmodell
- Marktposition, Wachstumspotenzial, Management sind kostenlos nur über Proxys
  messbar; Proxys sind gekennzeichnet, manuelle Einschätzungen per CSV haben Vorrang
"""
from __future__ import annotations

import csv
from dataclasses import dataclass

from . import config


def lin(x: float | None, lo: float, hi: float) -> float | None:
    """Lineare Skalierung auf 0..100 (lo -> 0, hi -> 100), begrenzt. hi < lo erlaubt (invers)."""
    if x is None:
        return None
    t = (x - lo) / (hi - lo)
    return round(max(0.0, min(1.0, t)) * 100, 1)


@dataclass
class Metric:
    key: str
    label: str
    unit: str
    lo: float
    hi: float


# Kennzahlmodell je Dimension: (Metric, Teilgewicht)
STANDARD_MODEL: dict[str, list[tuple[Metric, float]]] = {
    "revenue_growth": [
        (Metric("revenue_cagr", "Umsatz-CAGR (mehrjährig)", "%", -5, 20), 0.7),
        (Metric("revenue_growth_yoy", "Umsatzwachstum Vorjahr", "%", -10, 25), 0.3),
    ],
    "profitability": [
        (Metric("operating_margin", "Operative Marge", "%", 0, 30), 0.6),
        (Metric("net_margin", "Nettomarge", "%", -5, 20), 0.4),
    ],
    "financial_stability": [
        (Metric("debt_to_equity", "Verschuldung (Debt/Equity)", "x", 3.0, 0.2), 0.4),
        (Metric("current_ratio", "Liquidität (Current Ratio)", "x", 0.7, 2.0), 0.3),
        (Metric("interest_coverage", "Zinsdeckung (EBIT/Zinsen)", "x", 1.5, 15), 0.3),
    ],
    "cashflow": [
        (Metric("fcf_margin", "Free-Cashflow-Marge", "%", -5, 20), 0.6),
        (Metric("ocf_positive", "Operativer Cashflow positiv", "bool", 0, 1), 0.4),
    ],
    "market_position": [  # Proxy: Preissetzungsmacht über Bruttomarge
        (Metric("gross_margin", "Bruttomarge (Proxy Preissetzungsmacht)", "%", 15, 65), 1.0),
    ],
    "growth_potential": [  # Proxy: Analystenerwartung + Investitionsintensitaet
        (Metric("revenue_growth_forward", "Erwartetes Umsatzwachstum (Yahoo)", "%", -5, 25), 0.6),
        (Metric("reinvestment", "Reinvestition (F&E + Capex in % Umsatz)", "%", 2, 20), 0.4),
    ],
    "management": [  # Proxy: Kapitalrendite und Verwässerung
        (Metric("roe", "Eigenkapitalrendite", "%", 0, 25), 0.6),
        (Metric("share_change_yoy", "Aktienanzahl Veränderung (Verwässerung)", "%", 5, -3), 0.4),
    ],
}

FINANCIAL_MODEL: dict[str, list[tuple[Metric, float]]] = {
    **STANDARD_MODEL,
    "profitability": [
        (Metric("net_margin", "Nettomarge", "%", 0, 30), 0.5),
        (Metric("roe", "Eigenkapitalrendite", "%", 0, 18), 0.5),
    ],
    # Verschuldung/Liquidität sind bei Banken branchenimmanent -> nur Verwässerung
    "financial_stability": [
        (Metric("share_change_yoy", "Aktienanzahl Veränderung", "%", 5, -3), 1.0),
    ],
    "cashflow": [],               # FCF bei Finanzinstituten nicht aussagekraeftig
    "market_position": [],
    "growth_potential": [
        (Metric("revenue_growth_forward", "Erwartetes Umsatzwachstum (Yahoo)", "%", -5, 15), 1.0),
    ],
}

PROXY_DIMENSIONS = {"market_position", "growth_potential", "management"}
DIMENSION_LABELS = {
    "revenue_growth": "Umsatzwachstum", "profitability": "Profitabilität/Margen",
    "financial_stability": "Finanzielle Stabilität", "cashflow": "Cashflow",
    "market_position": "Marktposition/Wettbewerb", "growth_potential": "Wachstumspotenzial",
    "management": "Management/Kapitalallokation",
}


def load_manual_assessments() -> dict[tuple[str, str], dict]:
    """quality_manual.csv: symbol,dimension,score(0-100),rationale,source,as_of"""
    p = config.IMPORT_DIR / "quality_manual.csv"
    out: dict[tuple[str, str], dict] = {}
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("symbol") or r["symbol"].startswith("#"):
                continue
            try:
                score = float(r["score"])
            except (TypeError, ValueError):
                continue
            if not r.get("source"):
                continue  # keine unbelegten Bewertungen
            out[(r["symbol"].strip().upper(), r["dimension"].strip())] = {
                "score": max(0.0, min(100.0, score)), "rationale": r.get("rationale", ""),
                "source": r["source"], "as_of": r.get("as_of")}
    return out


def _derived(f: dict) -> dict:
    d = dict(f)
    ocf = f.get("operating_cashflow")
    d["ocf_positive"] = None if ocf is None else (1.0 if ocf > 0 else 0.0)
    parts = [f.get("rnd_intensity"), f.get("capex_intensity")]
    d["reinvestment"] = sum(p for p in parts if p is not None) if any(p is not None for p in parts) else None
    return d


def score_quality(symbol: str, fundamentals: dict | None, sector: str | None,
                  meta: dict | None = None, manual: dict | None = None) -> dict:
    manual = manual or {}
    f = _derived(fundamentals or {})
    is_fin = (sector or f.get("sector") or "") in config.FINANCIAL_SECTORS
    model = FINANCIAL_MODEL if is_fin else STANDARD_MODEL
    dims = []
    total_w = covered_w = weighted = 0.0
    for dim, weight in config.QUALITY_WEIGHTS.items():
        m = manual.get((symbol, dim))
        if not model.get(dim) and not m:
            # Branchenmodell sieht diese Dimension nicht vor -> nicht anwendbar (keine Datenlücke)
            dims.append({"key": dim, "label": DIMENSION_LABELS[dim], "weight": weight, "score": None,
                         "basis": "not_applicable", "coverage": None, "metrics": [], "manual": None})
            continue
        total_w += weight
        metrics, sub_w, sub_sum = [], 0.0, 0.0
        for metric, w in model.get(dim, []):
            val = f.get(metric.key)
            pts = lin(val, metric.lo, metric.hi)
            metrics.append({"key": metric.key, "label": metric.label, "unit": metric.unit,
                            "value": None if val is None else round(val, 3), "points": pts,
                            "status": "unknown" if pts is None else "ok"})
            if pts is not None:
                sub_w += w
                sub_sum += pts * w
        total_sub = sum(w for _, w in model.get(dim, [])) or 1
        if m:
            score, basis, cov = m["score"], "manual", 1.0
        elif sub_w > 0:
            score = round(sub_sum / sub_w, 1)
            basis = "proxy" if dim in PROXY_DIMENSIONS else "data"
            cov = sub_w / total_sub
        else:
            score, basis, cov = None, "unknown", 0.0
        if score is not None:
            covered_w += weight * cov
            weighted += score * weight * cov
        dims.append({"key": dim, "label": DIMENSION_LABELS[dim], "weight": weight, "score": score,
                     "basis": basis, "coverage": round(cov * 100), "metrics": metrics,
                     "manual": m if m else None})
    coverage = covered_w / total_w if total_w else 0.0
    overall = round(weighted / covered_w, 1) if covered_w > 0 and coverage >= config.QUALITY_MIN_COVERAGE else None
    return {
        "score": overall,
        "status": "ok" if overall is not None else "insufficient_data",
        "coverage_pct": round(coverage * 100),
        "model": "financial" if is_fin else "standard",
        "dimensions": dims,
        "source": (meta or {}).get("source", "Yahoo Finance (yfinance)"),
        "source_url": (meta or {}).get("source_url"),
        "as_of": (meta or {}).get("fetched_at"),
        "fiscal_year_end": f.get("fiscal_year_end"),
        "currency": f.get("financial_currency"),
        "note": "Startmodell; Gewichte und Schwellen sind zu validieren. Proxys sind gekennzeichnet.",
    }
