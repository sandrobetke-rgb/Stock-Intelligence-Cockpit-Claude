"""Watchlist und Alarme.

Watchlist: backend/data/imports/watchlist/*.csv (neueste Datei gilt, eine Aktie je Zeile) – wird vom
Cockpit per Klick als neue Datei in GitHub angelegt; alternativ watchlist.csv.
Alarme werden je Ereignis nur einmal ausgelöst (Zustand in data/state/alerts_state.json) und
- immer im Cockpit (alerts.json) angezeigt,
- optional als Push-Nachricht über ntfy.sh (Secret NTFY_TOPIC, kostenlos, ohne Konto),
- optional per E-Mail (Secrets SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO).
Zusätzlich täglich eine Liste neuer Swing-Kandidaten (S01–S04 + Abendfilter, ohne Zahlen in den
nächsten 5 Tagen). Alarme sind Hinweise, keine Handelsempfehlung.
"""
from __future__ import annotations

import csv
import logging
import os
import smtplib
from datetime import date, timedelta
from email.mime.text import MIMEText

import requests

from . import config
from .util import iso, read_json, utcnow, write_json_atomic

log = logging.getLogger("sic.alerts")
KIND = {
    "insider_buy": "Insiderkauf", "cluster": "Cluster-Kauf", "si_13f": "Superinvestor (13F)", "si_form4": "Superinvestor (Form 4)",
    "stake": "Großbeteiligung", "politician": "Politiker-Trade", "earnings": "Quartalszahlen", "ex_div": "Ex-Dividende",
    "trump": "Trump-Erwähnung", "setup": "Swing-Setup", "social_spike": "Social-Media-Anstieg", "digest": "Swing-Kandidaten",
}


def _state():
    return config.STATE_DIR / "alerts_state.json"


def load_watchlist() -> tuple[list[str], str | None]:
    d = config.IMPORT_DIR / "watchlist"
    files = sorted(d.glob("*.csv")) if d.exists() else []
    src = files[-1] if files else (config.IMPORT_DIR / "watchlist.csv")
    if not src.exists():
        return [], None
    syms = []
    with src.open(encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if row and row[0].strip() and not row[0].startswith("#") and row[0].strip().lower() != "symbol":
                syms.append(row[0].strip().upper())
    return sorted(set(syms)), src.name


def _a(kind, key, symbol, title, text, url=None, prio=3) -> dict:
    return {"key": f"{kind}:{key}", "kind": kind, "kind_label": KIND[kind], "symbol": symbol, "title": title,
            "text": text, "url": url, "priority": prio}


def candidates(stocks: list[dict]) -> list[dict]:
    """Swing-Kandidaten: mindestens ein Setup + Abendfilter, keine Zahlen in den nächsten 5 Tagen."""
    out = []
    for s in stocks:
        sw = s.get("swing") or {}
        if s["status"] != "active" or not set(sw.get("hits") or []) & {"S01", "S02", "S03", "S04"} or not sw.get("filter_pass"):
            continue
        if any(e["type"] == "earnings" and 0 <= e["days_until"] <= 5 for e in s.get("events") or []):
            continue
        out.append(s)
    return sorted(out, key=lambda s: -((s["swing"].get("tech") or {}).get("rvol") or 0))


def generate(*, stocks: list[dict], insiders: list[dict], clusters: list[dict], superinv: dict, stakes: list[dict],
             pol_trades: list[dict], trump: list[dict], social_stats: dict, watchlist: list[str], now=None) -> list[dict]:
    now = now or utcnow()
    today = now.date()
    d3, d7 = (today - timedelta(days=3)).isoformat(), (today - timedelta(days=7)).isoformat()
    wl = set(watchlist)
    by = {s["symbol"]: s for s in stocks}
    out: list[dict] = []
    for x in insiders:
        if x["symbol"] in wl and x.get("open_market") and x.get("transaction_kind") == "buy" and (x.get("filed_at") or "") >= d3:
            out.append(_a("insider_buy", x["id"], x["symbol"], f"{x['symbol']}: Insiderkauf",
                          f"{x['insider']} ({x.get('role')}) kauft für {round((x.get('value') or 0) / 1e3):,} Tsd. {x.get('currency', '')}".replace(",", "."),
                          x.get("source_url"), 2))
        if x["symbol"] in wl and x.get("superinvestor") and (x.get("filed_at") or "") >= d7:
            out.append(_a("si_form4", x["id"], x["symbol"], f"{x['symbol']}: {x['superinvestor']}",
                          f"{x.get('transaction_label')} ({x.get('transaction_date')})", x.get("source_url"), 1))
    for c in clusters:
        if c["symbol"] in wl:
            out.append(_a("cluster", f"{c['symbol']}:{c['last']}", c["symbol"], f"{c['symbol']}: Cluster-Kauf",
                          f"{c['insiders']} Insider kaufen ({c['first']} bis {c['last']})", None, 1))
    for m in superinv.get("managers", []):
        if m.get("stale") or (m.get("filed_at") or "") < d7:
            continue
        for p in m["positions"]:
            if p.get("symbol") in wl and p["action"] in ("new", "increased", "sold_out"):
                verb = {"new": "kauft neu", "increased": "stockt auf", "sold_out": "verkauft komplett"}[p["action"]]
                out.append(_a("si_13f", f"{m['cik']}:{m['report_date']}:{p['symbol']}", p["symbol"], f"{p['symbol']}: {m['manager']} {verb}",
                              f"13F zum {m['report_date']}, Depotanteil {p['weight_pct']} %", m.get("filing_url"), 2))
    for s in stakes:
        if s["symbol"] in wl and s["filed_at"] >= d7:
            out.append(_a("stake", s["id"], s["symbol"], f"{s['symbol']}: {s['manager']} meldet {s['form']}",
                          "Beteiligung über 5 %", s["url"], 1))
    for t in pol_trades:
        if t["symbol"] in wl and (t.get("disclosure_date") or "") >= d7:
            verb = "kauft" if t["transaction_type"] == "purchase" else "verkauft"
            out.append(_a("politician", t["id"], t["symbol"], f"{t['symbol']}: {t['politician']} {verb}",
                          f"{t['chamber']}, Geschäft vom {t.get('transaction_date')}", t.get("source_url"), 2))
    for sym in wl:
        s = by.get(sym)
        if not s:
            continue
        for e in s.get("events") or []:
            if e["type"] == "earnings" and 0 <= e["days_until"] <= 2:
                out.append(_a("earnings", f"{sym}:{e['date']}", sym, f"{sym}: Zahlen am {e['date']}",
                              f"{e.get('time') or ''} – vor Einstieg beachten", e.get("source_url"), 2))
            if e["type"] == "ex_dividend" and 0 <= e["days_until"] <= 1:
                out.append(_a("ex_div", f"{sym}:{e['date']}", sym, f"{sym}: Ex-Dividende {e['date']}", f"{e.get('amount') or ''} je Aktie", e.get("source_url"), 3))
        sw = s.get("swing") or {}
        for h in sw.get("hits") or []:
            out.append(_a("setup", f"{sym}:{s['market'].get('price_date')}:{h}", sym, f"{sym}: Setup {h}",
                          f"Auslöser {sw['plan']['trigger']:.2f}, Stopp {sw['plan']['stop']:.2f}" + ("" if sw.get("filter_pass") else " (Abendfilter nicht erfüllt)"), None, 2))
        soc = social_stats.get(sym)
        if soc and soc["mentions_24h"] >= 10 and (soc.get("change_vs_baseline_pct") or 0) >= 200:
            out.append(_a("social_spike", f"{sym}:{today}", sym, f"{sym}: Social-Media-Anstieg",
                          f"{soc['mentions_24h']} Erwähnungen in 24 Std. (+{soc['change_vs_baseline_pct']} %)", None, 3))
    for t in trump:
        if t.get("symbol") in wl and t["bonus"]["active"]:
            out.append(_a("trump", t["id"], t["symbol"], f"{t['symbol']}: Trump-Erwähnung ({t['direction']})", t["quote"][:140], t.get("source_url"), 1))
    cands = candidates(stocks)
    if cands:
        lines = [f"{c['symbol']} {'/'.join(c['swing']['hits'])} RelVol {c['swing']['tech']['rvol']:.1f}" for c in cands[:10]]
        note = " Morgen ist Freitag: laut Regel keine neuen Trades." if today.weekday() == 3 else ""
        out.append(_a("digest", today.isoformat(), None, f"{len(cands)} Swing-Kandidaten für den nächsten Handelstag",
                      "; ".join(lines) + note, None, 2))
    return out


def dispatch(new: list[dict], cockpit_url: str | None) -> dict:
    sent = {"ntfy": False, "email": False}
    if not new:
        return sent
    wl = [a for a in new if a["kind"] != "digest"]
    dg = [a for a in new if a["kind"] == "digest"]
    body = "\n".join(f"• {a['title']} – {a['text']}" for a in sorted(wl, key=lambda a: a["priority"])[:25])
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        try:
            for title, text, prio in ([(f"Watchlist: {len(wl)} neue Ereignisse", body, "high" if any(a["priority"] == 1 for a in wl) else "default")] if wl else []) + \
                                     [(a["title"], a["text"], "default") for a in dg]:
                requests.post(f"https://ntfy.sh/{topic}", data=text.encode("utf-8"), timeout=20,
                              headers={"Title": title.encode("utf-8"), "Priority": prio, "Tags": "chart_with_upwards_trend",
                                       **({"Click": cockpit_url + "#/watchlist"} if cockpit_url else {})}).raise_for_status()
            sent["ntfy"] = True
        except Exception as exc:  # noqa: BLE001
            log.warning("ntfy: %s", exc)
    host, to = os.environ.get("SMTP_HOST"), os.environ.get("ALERT_EMAIL_TO")
    if host and to:
        try:
            text = (body + "\n\n" if body else "") + "\n".join(f"{a['title']}\n{a['text']}" for a in dg)
            text += f"\n\nCockpit: {cockpit_url or ''}\nHinweis, keine Anlageberatung."
            msg = MIMEText(text, "plain", "utf-8")
            msg["Subject"] = f"Stock Intelligence Cockpit: {len(new)} neue Alarme"
            msg["From"] = os.environ.get("SMTP_USER", to)
            msg["To"] = to
            with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
                s.starttls()
                s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
                s.send_message(msg)
            sent["email"] = True
        except Exception as exc:  # noqa: BLE001
            log.warning("E-Mail: %s", exc)
    return sent


def process(all_alerts: list[dict], watchlist: list[str], watch_file: str | None, notify: bool = True, now=None) -> dict:
    """Neue Alarme ermitteln (einmalig je Ereignis), verschicken und Verlauf für das Cockpit liefern."""
    now = now or utcnow()
    st = read_json(_state(), {"seen": {}, "history": []})
    new = [a for a in all_alerts if a["key"] not in st["seen"]]
    for a in new:
        a["created_at"] = iso(now)
        st["seen"][a["key"]] = iso(now)
    sent = dispatch(new, os.environ.get("COCKPIT_URL")) if notify else {"ntfy": False, "email": False}
    st["history"] = (new + st["history"])[:500]
    cutoff = iso(now - timedelta(days=90))
    st["seen"] = {k: v for k, v in st["seen"].items() if v >= cutoff}
    write_json_atomic(_state(), st)
    return {"watchlist": watchlist, "watchlist_file": watch_file, "new_count": len(new), "history": st["history"],
            "channels": {"push": bool(os.environ.get("NTFY_TOPIC")), "email": bool(os.environ.get("SMTP_HOST") and os.environ.get("ALERT_EMAIL_TO"))},
            "sent": sent, "today": date.today().isoformat()}
