"""Risk Score (Lastenheft Kap. 11). 0 = geringes, 100 = hohes Risiko.

Separat ausgewiesen. Positive Aufmerksamkeit senkt das Risiko nie; negative politische
Signale koennen es erhoehen. Fehlende Faktoren bleiben 'unknown'.
"""
from __future__ import annotations

import csv

from . import config
from .quality import lin

LEVELS = [(25, "niedrig"), (45, "moderat"), (65, "erhoeht"), (101, "hoch")]


def level(score: float | None) -> str:
    if score is None:
        return "unbekannt"
    return next(name for lim, name in LEVELS if score < lim)


def load_manual_risks() -> dict[str, list[dict]]:
    """risk_manual.csv: symbol,factor,severity(0-100),description,source,as_of
    für Rechtsstreitigkeiten, Kundenabhängigkeit, Bilanzrisiken usw."""
    p = config.IMPORT_DIR / "risk_manual.csv"
    out: dict[str, list[dict]] = {}
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("symbol") or r["symbol"].startswith("#") or not r.get("source"):
                continue
            try:
                sev = max(0.0, min(100.0, float(r["severity"])))
            except (TypeError, ValueError):
                continue
            out.setdefault(r["symbol"].strip().upper(), []).append(
                {"factor": r["factor"], "severity": sev, "description": r.get("description", ""),
                 "source": r["source"], "as_of": r.get("as_of")})
    return out


def score_risk(fund: dict | None, market: dict | None, political: dict | None,
               manual: list[dict] | None = None, is_financial: bool = False) -> dict:
    f, m = fund or {}, market or {}
    factors: list[dict] = []

    def add(key, label, value, unit, sev, weight):
        factors.append({"key": key, "label": label, "value": None if value is None else round(value, 2),
                        "unit": unit, "severity": sev, "weight": weight,
                        "status": "unknown" if sev is None else "ok"})

    if not is_financial:
        add("leverage", "Verschuldung (Debt/Equity)", f.get("debt_to_equity"), "x", lin(f.get("debt_to_equity"), 0.3, 3.0), 0.15)
        add("liquidity", "Liquidität (Current Ratio)", f.get("current_ratio"), "x", lin(f.get("current_ratio"), 2.0, 0.7), 0.10)
        add("interest", "Zinsdeckung", f.get("interest_coverage"), "x", lin(f.get("interest_coverage"), 15, 1.0), 0.08)
        add("cashflow", "Free-Cashflow-Marge", f.get("fcf_margin"), "%", lin(f.get("fcf_margin"), 15, -10), 0.12)
    om, omp = f.get("operating_margin"), f.get("operating_margin_prev")
    trend = (om - omp) if om is not None and omp is not None else None
    add("margin_trend", "Margenentwicklung (Vorjahr, Pp.)", trend, "Pp", lin(trend, 3, -8), 0.08)
    add("dilution", "Verwässerung (Aktienanzahl yoy)", f.get("share_change_yoy"), "%", lin(f.get("share_change_yoy"), 0, 10), 0.10)
    add("volatility", "Volatilität (63T, annualisiert)", m.get("volatility_ann"), "%", lin(m.get("volatility_ann"), 20, 80), 0.12)
    adv = m.get("avg_dollar_volume_20d")
    add("trading_liquidity", "Handelsliquidität (Umsatz 20T)", adv, "Whg", lin(adv, 5e7, 1e6) if adv is not None else None, 0.07)
    pe = f.get("forward_pe") or f.get("trailing_pe")
    val_sev = lin(pe, 15, 80) if pe is not None and pe > 0 else (lin(f.get("price_to_sales"), 2, 20) if f.get("price_to_sales") else None)
    add("valuation", "Bewertung (KGV bzw. KUV)", pe if pe and pe > 0 else f.get("price_to_sales"), "x", val_sev, 0.08)
    add("governance", "Governance-/Prüfungsrisiko (ISS via Yahoo, 1-10)", f.get("audit_risk"), "1-10",
        lin(f.get("audit_risk"), 1, 10), 0.04)

    pol = political or {}
    neg = pol.get("negative_signals_30d", 0)
    add("political", "Negative politische/regulatorische Signale (30T)", neg, "Anzahl",
        lin(float(neg), 0, 4) if pol.get("covered") else None, 0.06)

    for mr in manual or []:
        factors.append({"key": f"manual:{mr['factor']}", "label": mr["factor"], "value": None, "unit": "",
                        "severity": mr["severity"], "weight": 0.10, "status": "manual",
                        "description": mr["description"], "source": mr["source"], "as_of": mr.get("as_of")})

    known = [x for x in factors if x["severity"] is not None]
    tot_w = sum(x["weight"] for x in factors)
    known_w = sum(x["weight"] for x in known)
    score = round(sum(x["severity"] * x["weight"] for x in known) / known_w, 1) if known_w else None
    coverage = round(known_w / tot_w * 100) if tot_w else 0
    if coverage < 35:
        score = None
    top = sorted(known, key=lambda x: x["severity"] * x["weight"], reverse=True)[:3]
    return {"score": score, "level": level(score), "coverage_pct": coverage, "factors": factors,
            "top_factors": [x["label"] for x in top if x["severity"] >= 50],
            "unknown_factors": ["Kunden- und Branchenabhängigkeit", "Rechtsstreitigkeiten"]
            if not manual else []}
