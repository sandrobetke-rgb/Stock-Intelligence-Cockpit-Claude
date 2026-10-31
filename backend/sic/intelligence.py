"""Market Intelligence / Multi-Source Radar (Lastenheft Kap. 5).

Die Anzahl der Meldungen allein bestimmt nicht die Relevanz: gezaehlt werden unabhängige
Meldungscluster (Syndizierungen/Kopien nicht), logarithmisch gedaempft, plus Quellenvielfalt,
Primärquellen, Analystenänderungen, Kurs-/Volumenauffaelligkeit und Social Media.
"""
from __future__ import annotations

import math

from . import config
from .signals import in_window


def market_intelligence(symbol: str, signals: list[dict], market: dict | None, social: dict | None,
                        insider: dict | None) -> dict:
    mine = [s for s in signals if symbol in s["symbols"]]
    windows = {}
    for name, h in config.NEWS_WINDOWS_H.items():
        w = [s for s in mine if in_window(s, h)]
        clusters = {s["cluster_id"] for s in w}
        windows[name] = {
            "signals": len(w),
            "independent": len(clusters),
            "duplicates": sum(1 for s in w if s["independence"] in ("copy", "syndicated")),
            "sources": len({s["source_domain"] for s in w}),
            "primary": sum(1 for s in w if s["primary_source"]),
            "analyst_changes": sum(1 for s in w if s["signal_type"] == "analyst_change"),
            "verified": sum(1 for s in w if s["verification"] == "Verified"),
        }
    w7, w24 = windows["7d"], windows["24h"]
    m = market or {}
    comp = {
        # log-gedaempft: 1 Cluster ~ 30, 3 ~ 60, 7 ~ 90
        "news_flow": min(100.0, 43 * math.log2(1 + w7["independent"])) if w7["independent"] else 0.0,
        "freshness": min(100.0, 50 * w24["independent"]),
        "source_diversity": min(100.0, 20 * w7["sources"]),
        "primary_sources": min(100.0, 50 * w7["primary"]),
        "analyst_activity": min(100.0, 35 * w7["analyst_changes"]),
        "price_volume_anomaly": None,
        "social_attention": None,
        "insider_activity": None,
    }
    if m.get("rvol") is not None or m.get("move_zscore") is not None:
        rv = max(0.0, min(100.0, ((m.get("rvol") or 1) - 1) * 50))
        zs = max(0.0, min(100.0, abs(m.get("move_zscore") or 0) * 30))
        comp["price_volume_anomaly"] = round(max(rv, zs), 1)
    if social:
        s7 = social["mentions_7d"]
        att = min(100.0, 25 * math.log2(1 + s7))
        # Manipulationsverdacht daempft den Beitrag
        comp["social_attention"] = round(att * (0.4 if social["manipulation_risk"] == "hoch" else 1.0), 1)
    if insider and (insider["open_market_buys"] or insider["open_market_sells"]):
        comp["insider_activity"] = min(100.0, 30 * insider["distinct_buyers"] + 10 * insider["open_market_sells"])
    weights = {"news_flow": 0.25, "freshness": 0.10, "source_diversity": 0.15, "primary_sources": 0.10,
               "analyst_activity": 0.10, "price_volume_anomaly": 0.15, "social_attention": 0.10, "insider_activity": 0.05}
    known = {k: v for k, v in comp.items() if v is not None}
    kw = sum(weights[k] for k in known)
    score = round(sum(v * weights[k] for k, v in known.items()) / kw, 1) if kw else None
    drivers = sorted(((k, v * weights[k]) for k, v in known.items() if v and v > 0), key=lambda x: -x[1])[:3]
    return {"score": score, "components": {k: (round(v, 1) if v is not None else None) for k, v in comp.items()},
            "windows": windows, "drivers": [d[0] for d in drivers],
            "note": "Aufmerksamkeit ist keine Qualitäts- oder Kursaussage."}
