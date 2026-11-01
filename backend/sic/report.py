"""Signal-Zusammenfluss und Tagesbericht.

Zusammenfluss: Je Aktie wird gezählt, wie viele voneinander unabhängige, positive Signalarten
gleichzeitig vorliegen. Die vier Bewertungsachsen werden dabei NICHT zu einem Score verrechnet –
es wird nur sichtbar, wo sie übereinstimmen. Warnsignale stehen getrennt daneben.

Tagesbericht: kompakte Übersicht für den Morgen (Termine heute, Swing-Kandidaten mit Preismarken,
neue Meldungen der letzten 24 Std., Watchlist-Alarme, Social-Media-Bewegungen).
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

import requests

from .util import iso, utcnow

log = logging.getLogger("sic.report")
WEEKDAY = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def confluence_row(s: dict) -> dict | None:
    if s["status"] != "active":
        return None
    pos, neg = [], []
    ins = s.get("insider") or {}
    if ins.get("distinct_buyers", 0) >= 2:
        pos.append(("insider", f"Cluster-Kauf: {ins['distinct_buyers']} Insider (90 T.)"))
    elif ins.get("open_market_buys"):
        pos.append(("insider", f"Insiderkauf ({ins['open_market_buys']}×, 90 T.)"))
    si = s.get("superinvestors") or {}
    if si.get("buyers", 0) >= 2 or si.get("new_buyers", 0) >= 1:
        pos.append(("superinvestors", f"Superinvestoren kaufen ({si.get('buyers', 0)}, davon {si.get('new_buyers', 0)} neu)"))
    if si.get("sellers", 0) >= 3 and si.get("sellers", 0) > si.get("buyers", 0):
        neg.append(f"{si['sellers']} Superinvestoren verkaufen")
    pol = s.get("politicians") or {}
    if pol.get("buys", 0) >= 1 and pol.get("buys", 0) >= pol.get("sells", 0):
        pos.append(("politicians", f"Politiker kaufen ({pol['buys']})"))
    q = (s.get("quality") or {}).get("score")
    if q is not None and q >= 70:
        pos.append(("quality", f"Quality {round(q)}"))
    sw = s.get("swing") or {}
    if sw.get("hits"):
        pos.append(("setup", "Setup " + "/".join(sw["hits"]) + (" + Abendfilter" if sw.get("filter_pass") else "")))
    soc = s.get("social") or {}
    if soc.get("mentions_7d", 0) >= 10 and (soc.get("sentiment_7d") or 0) >= 0.2 and soc.get("manipulation_risk") != "hoch":
        pos.append(("social", f"Social positiv ({soc['mentions_7d']} Beiträge)"))
    if soc.get("manipulation_risk") == "hoch":
        neg.append("Social-Media-Hype/Manipulationsverdacht")
    p = s.get("political") or {}
    if p.get("direction") == "positive":
        pos.append(("political", "Politisch positiv" + (" (Trump-Bonus)" if p.get("trump_bonus_active") else "")))
    elif p.get("direction") == "negative":
        neg.append("Negative politische Signale")
    if (s.get("risk") or {}).get("level") in ("erhoeht", "hoch"):
        neg.append(f"Risiko {'erhöht' if s['risk']['level'] == 'erhoeht' else 'hoch'}")
    for e in s.get("events") or []:
        if e["type"] == "earnings" and 0 <= e["days_until"] <= 5:
            neg.append(f"Zahlen in {e['days_until']} T.")
    if len(pos) < 2:
        return None
    return {"symbol": s["symbol"], "name": s["name"], "sector": s.get("sector"), "indexes": s.get("indexes"),
            "count": len(pos), "kinds": [k for k, _ in pos], "positives": [t for _, t in pos], "warnings": neg,
            "quality": q, "risk_level": (s.get("risk") or {}).get("level"), "events": s.get("events") or [],
            "close": (s.get("market") or {}).get("last_close"), "perf_20d": (s.get("market") or {}).get("perf_20d")}


def confluence(stocks: list[dict]) -> list[dict]:
    rows = [r for s in stocks if (r := confluence_row(s))]
    return sorted(rows, key=lambda r: (-r["count"], len(r["warnings"]), -(r["quality"] or 0)))


def build_report(*, stocks: list[dict], candidates: list[dict], alerts_history: list[dict], market_events: dict,
                 insiders_clusters: list[dict], superinv: dict, pol_trades: list[dict], trump: list[dict],
                 social_stats: dict, watchlist: list[str], conf: list[dict], now=None) -> dict:
    now = now or utcnow()
    today = now.date()
    # Berichtstag = nächster Handelstag aus Sicht des Abends, bzw. heute am Morgen
    day = today if now.hour < 14 else today + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    dstr = day.isoformat()
    since = iso(now - timedelta(hours=24))
    by = {s["symbol"]: s for s in stocks}
    big = sorted([s for s in stocks if s["status"] == "active" and (s.get("market_cap") or 0) > 0],
                 key=lambda s: -(s.get("market_cap") or 0))[:100]
    focus = set(watchlist) | {s["symbol"] for s in big}
    earnings = []
    for sym in focus:
        for e in (by.get(sym) or {}).get("events") or []:
            if e["type"] == "earnings" and e["date"] == dstr:
                earnings.append({"symbol": sym, "name": by[sym]["name"], "time": e.get("time"), "watchlist": sym in watchlist,
                                 "eps_forecast": e.get("eps_forecast")})
    macro = [e for e in market_events.get("upcoming", []) if (e.get("time") or "")[:10] in (dstr, (day + timedelta(days=1)).isoformat())]
    cands = [{"symbol": c["symbol"], "name": c["name"], "hits": c["swing"]["hits"], "trigger": c["swing"]["plan"]["trigger"],
              "entry_max": c["swing"]["plan"]["entry_max"], "stop": c["swing"]["plan"]["stop"], "target_1": c["swing"]["plan"]["target_1"],
              "rvol": c["swing"]["tech"].get("rvol"), "quality": c["quality"]["score"], "watchlist": c["symbol"] in watchlist}
             for c in candidates[:15]]
    new_si = [{"manager": m["manager"], "report_date": m["report_date"], "filed_at": m["filed_at"], "new": m["new"], "sold_out": m["sold_out"],
               "top_new": [p.get("symbol") or p["issuer"] for p in m["positions"] if p["action"] == "new"][:5]}
              for m in superinv.get("managers", []) if not m.get("stale") and (m.get("filed_at") or "") >= (today - timedelta(days=2)).isoformat()]
    pol_new = [t for t in pol_trades if (t.get("disclosure_date") or "") >= (today - timedelta(days=2)).isoformat()][:30]
    trump_new = [t for t in trump if t["bonus"]["active"] and (t.get("statement_at") or "") >= since]
    movers = sorted(((k, v) for k, v in social_stats.items() if v["mentions_24h"] >= 5),
                    key=lambda kv: -(kv[1].get("change_vs_baseline_pct") or 0))[:8]
    note = ("Heute ist Freitag: laut deinen Regeln keine neuen Trades." if day.weekday() == 4 else None)
    return {
        "report_date": dstr, "weekday": WEEKDAY[day.weekday()], "created_at": iso(now), "rule_note": note,
        "macro": macro, "earnings": sorted(earnings, key=lambda e: (not e["watchlist"], e["symbol"])),
        "candidates": cands, "watchlist_alerts": [a for a in alerts_history if a.get("created_at", "") >= since and a["kind"] != "digest"][:30],
        "clusters": insiders_clusters[:10], "superinvestor_filings": new_si, "politician_trades": pol_new,
        "trump": trump_new, "social_movers": [{"symbol": k, "mentions_24h": v["mentions_24h"], "change": v.get("change_vs_baseline_pct"),
                                               "sentiment": v.get("sentiment_7d")} for k, v in movers],
        "confluence_top": conf[:10],
    }


def send_report(rep: dict, cockpit_url: str | None) -> bool:
    topic = os.environ.get("NTFY_TOPIC")
    lines = []
    if rep.get("rule_note"):
        lines.append(rep["rule_note"])
    if rep["macro"]:
        lines.append("Termine: " + "; ".join(e["title"] for e in rep["macro"][:4]))
    if rep["earnings"]:
        lines.append("Zahlen heute: " + ", ".join(e["symbol"] + ("★" if e["watchlist"] else "") for e in rep["earnings"][:12]))
    if rep["candidates"]:
        lines.append("Swing: " + ", ".join(f"{c['symbol']} >{c['trigger']:.2f}" for c in rep["candidates"][:8]))
    if rep["watchlist_alerts"]:
        lines.append(f"Watchlist: {len(rep['watchlist_alerts'])} neue Ereignisse")
    if rep["confluence_top"]:
        lines.append("Zusammenfluss: " + ", ".join(f"{c['symbol']} ({c['count']})" for c in rep["confluence_top"][:6]))
    text = "\n".join(lines) or "Keine besonderen Ereignisse."
    ok = False
    if topic:
        try:
            requests.post(f"https://ntfy.sh/{topic}", data=text.encode("utf-8"), timeout=20,
                          headers={"Title": f"Tagesbericht {rep['weekday']} {rep['report_date']}".encode("utf-8"),
                                   "Tags": "sunrise", **({"Click": cockpit_url + "#/report"} if cockpit_url else {})}).raise_for_status()
            ok = True
        except Exception as exc:  # noqa: BLE001
            log.warning("ntfy Bericht: %s", exc)
    if os.environ.get("SMTP_HOST") and os.environ.get("ALERT_EMAIL_TO"):
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(text + f"\n\nVollständiger Bericht: {(cockpit_url or '') + '#/report'}\nHinweis, keine Anlageberatung.", "plain", "utf-8")
            msg["Subject"] = f"Tagesbericht {rep['weekday']} {rep['report_date']}"
            msg["From"], msg["To"] = os.environ.get("SMTP_USER", ""), os.environ["ALERT_EMAIL_TO"]
            with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
                s.starttls()
                s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
                s.send_message(msg)
            ok = True
        except Exception as exc:  # noqa: BLE001
            log.warning("E-Mail Bericht: %s", exc)
    return ok
