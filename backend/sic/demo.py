"""Synthetische DEMO-Daten für Frontend-Entwicklung und Tests.

    python -m sic.demo   -> frontend/public/demo-data/*.json

Alle Unternehmen, Zitate und Zahlen sind ERFUNDEN und mit 'DEMO' gekennzeichnet
(fiktive Ticker DMxx). summary.json traegt mode='demo'; das Frontend zeigt dann ein
Warnbanner. Nie als echte Daten veröffentlichen.
"""
from __future__ import annotations

import random
import tempfile
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from .events import load_calendar
from .export import publish
from .insider import insider_summary  # noqa: F401  (Import-Prüfung)
from .market import compute_metrics
from .politics import build_alias_index, process_trump
from .run import SOURCES, assemble
from .signals import cluster_signals, make_signal, verify
from .social import analyze
from .util import iso, stable_id, utcnow

SECTORS = ["Technology", "Industrials", "Healthcare", "Financial Services", "Energy", "Consumer Cyclical",
           "Communication Services", "Basic Materials"]
WORDS = ["Nordwind", "Aurelia", "Kestrel", "Brightline", "Halvard", "Sundial", "Meridian", "Corvex", "Lumen",
         "Ostara", "Pinecrest", "Quadra", "Rivulet", "Solace", "Tessera", "Umbra", "Vantor", "Wexley", "Ysolde",
         "Zephyrin", "Arclight", "Beacon", "Calder", "Driftwood", "Emberly", "Fjordan", "Granite", "Harbor",
         "Ironleaf", "Juniper", "Kinsale", "Larkspur", "Marrow", "Nimbus", "Orchard", "Prairie", "Quill",
         "Redfern", "Silvan", "Thistle"]


def _ohlcv(rng: random.Random, n=260, start=50.0, drift=0.0004, vol=0.02) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(utcnow().date()), periods=n)
    r = np.array([rng.gauss(drift, vol) for _ in range(n)])
    close = start * np.exp(np.cumsum(r))
    high = close * (1 + np.abs([rng.gauss(0, vol / 2) for _ in range(n)]))
    low = close * (1 - np.abs([rng.gauss(0, vol / 2) for _ in range(n)]))
    volume = np.array([rng.uniform(4e5, 3e6) for _ in range(n)])
    volume[-1] *= rng.choice([1, 1, 1, 2.5, 4])
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": volume}, index=idx)


def _fund(rng: random.Random, sector: str, name: str) -> dict:
    rev = rng.uniform(0.3e9, 40e9)
    g = rng.uniform(-0.08, 0.3)
    om = rng.uniform(-0.05, 0.35)
    missing = rng.random() < 0.15
    f = {
        "revenue": rev, "revenue_cagr": g * 100, "revenue_cagr_years": 3, "revenue_growth_yoy": (g + rng.uniform(-0.05, 0.05)) * 100,
        "operating_margin": om * 100, "operating_margin_prev": (om + rng.uniform(-0.06, 0.04)) * 100,
        "net_margin": (om * 0.75) * 100, "debt_to_equity": rng.uniform(0.05, 3.5), "net_debt": rev * rng.uniform(-0.2, 1),
        "current_ratio": rng.uniform(0.6, 3.0), "interest_coverage": None if missing else rng.uniform(0.8, 40),
        "operating_cashflow": rev * rng.uniform(-0.05, 0.35), "free_cashflow": rev * rng.uniform(-0.1, 0.25),
        "fcf_margin": rng.uniform(-10, 25), "capex_intensity": rng.uniform(1, 15), "rnd_intensity": rng.uniform(0, 18) if sector == "Technology" else None,
        "roe": rng.uniform(-5, 35), "share_change_yoy": rng.uniform(-4, 9), "buyback": None,
        "market_cap": rev * rng.uniform(0.8, 9), "market_cap_currency": "USD", "financial_currency": "USD",
        "trailing_pe": rng.uniform(8, 90), "forward_pe": rng.uniform(8, 60), "price_to_sales": rng.uniform(0.5, 15),
        "beta": rng.uniform(0.6, 2), "gross_margin": None if missing else rng.uniform(15, 75),
        "revenue_growth_forward": None if missing else rng.uniform(-5, 30), "sector": sector, "industry": f"{sector} (Demo)",
        "country": "Demo-Land", "long_name": name, "fiscal_year_end": "2025-12-31",
        "audit_risk": float(rng.randint(1, 10)), "board_risk": float(rng.randint(1, 10)), "top_customer_share": None,
    }
    return f


def build_demo(out_dir: Path | None = None, n: int = 40, seed: int = 7) -> dict:
    rng = random.Random(seed)
    now = utcnow()
    tmp = Path(tempfile.mkdtemp(prefix="sic-demo-"))
    # Demo nutzt eigene, leere Zustands-/Importordner
    config.STATE_DIR, config.CACHE_DIR, config.IMPORT_DIR = tmp / "state", tmp / "cache", tmp / "imports"
    for d in (config.STATE_DIR, config.CACHE_DIR, config.IMPORT_DIR):
        d.mkdir(parents=True)
    secs, prices, funds = {}, {}, {}
    idx_codes = ["NDX", "SPX", "RUT", "DAX"]
    for i in range(n):
        sym = f"DM{i:02d}"
        sector = SECTORS[i % len(SECTORS)]
        name = f"{WORDS[i % len(WORDS)]} {'AG' if i % 5 == 0 else 'Inc.'} (DEMO)"
        mships = []
        if i % 5 == 0:
            mships.append({"index": "DAX", "since": "2024-01-02", "until": None, "date_basis": "initial_load"})
        else:
            mships.append({"index": rng.choice(["SPX", "RUT"]), "since": "2024-01-02", "until": None, "date_basis": "initial_load"})
            if i % 3 == 0:
                mships.append({"index": "NDX", "since": "2025-03-24", "until": None, "date_basis": "detected"})
        status = "active"
        if i in (37, 38):  # Universumsaustritt-Beispiel
            for m in mships:
                m["until"] = "2026-09-22"
            status = "archived"
        secs[sym] = {"symbol": sym, "name": name, "sector": sector, "region": "DE" if i % 5 == 0 else "US",
                     "currency": "EUR" if i % 5 == 0 else "USD", "memberships": mships, "status": status,
                     "status_reason": "no_target_index" if status == "archived" else None,
                     "first_seen": "2024-01-02", "archived_at": "2026-09-22" if status == "archived" else None}
        df = _ohlcv(rng, start=rng.uniform(10, 400), drift=rng.uniform(-0.001, 0.002), vol=rng.uniform(0.01, 0.04))
        prices[sym] = compute_metrics(df)
        if i != 12:  # ein Titel ohne Fundamentaldaten (Datenlücke)
            funds[sym] = {"symbol": sym, "fetched_at": iso(now - timedelta(days=rng.randint(0, 6))),
                          "source": "DEMO (synthetisch)", "source_url": None, "data": _fund(rng, sector, name)}
    state = {"securities": secs, "indexes": {c: {"code": c, "name": config.INDEXES[c]["name"], "source": "DEMO",
                                                 "checked_at": iso(now), "members": sum(1 for s in secs.values() if any(m["index"] == c and not m["until"] for m in s["memberships"])),
                                                 "status": "ok" if c != "RUT" else "error",
                                                 "message": None if c != "RUT" else "DEMO: Plausibilitätsprüfung fehlgeschlagen – letzter gültiger Stand bleibt",
                                                 "limitation": config.INDEXES[c].get("limitation")} for c in idx_codes},
             "history": [{"date": "2026-09-22", "symbol": "DM37", "from": "active", "to": "archived", "reason": "no_target_index"}],
             "upcoming_changes": [{"index": "SPX", "symbol": "DM05", "action": "add", "effective_date": (now + timedelta(days=12)).date().isoformat(),
                                   "source": "DEMO", "name": secs["DM05"]["name"]}],
             "built_at": iso(now)}

    domains = ["demo-wire.example", "demo-news.example", "demo-times.example", "sec.gov", "demo-blog.example"]
    sigs = []
    for k in range(140):
        sym = f"DM{rng.randint(0, 20):02d}"
        topic = rng.choice(["meldet Quartalszahlen über Erwartung", "erhoeht Prognose", "Analyst hebt Kursziel an (upgrade)",
                            "kündigt Übernahme an", "verliert Großkunden", "startet Aktienrückkauf"])
        title = f"[DEMO] {secs[sym]['name'].split(' (')[0]} {topic}"
        dom = rng.choice(domains)
        hours = rng.uniform(0, 24 * 25)
        sigs.append(make_signal(symbols=[sym], category="market", signal_type="analyst_change" if "upgrade" in topic else "company_news",
                                title=title, url=f"https://{dom}/demo/{k}", source=dom, published=iso(now - timedelta(hours=hours)),
                                summary="Synthetische Demo-Meldung."))
    cluster_signals(sigs)
    verify(sigs)

    aliases = build_alias_index(secs)
    rows = [
        {"statement_at": iso(now - timedelta(days=1, hours=3)), "quote": "[DEMO – keine echte Äußerung] Nordwind is a great company, they will invest and build big factories here!",
         "source_name": "DEMO", "source_url": "https://truthsocial.com/demo/1", "original_url": "https://truthsocial.com/demo/1",
         "verification": "Verified", "direction_override": "", "symbols_override": "DM00", "context": "Demo"},
        {"statement_at": iso(now - timedelta(days=2)), "quote": "[DEMO – keine echte Äußerung] We will put massive tariffs on Kestrel products, unfair!",
         "source_name": "DEMO", "source_url": "https://www.whitehouse.gov/demo/2", "original_url": "https://www.whitehouse.gov/demo/2",
         "verification": "Verified", "direction_override": "", "symbols_override": "DM02", "context": "Demo"},
        {"statement_at": iso(now - timedelta(days=8)), "quote": "[DEMO – keine echte Äußerung] Brightline did a fantastic job, great deal!",
         "source_name": "DEMO", "source_url": "https://truthsocial.com/demo/3", "original_url": "https://truthsocial.com/demo/3",
         "verification": "Verified", "direction_override": "", "symbols_override": "DM03", "context": "Demo – Bonus verfallen"},
        {"statement_at": iso(now - timedelta(days=1)), "quote": "[DEMO – keine echte Äußerung] The chip industry must come back to America, semiconductors!",
         "source_name": "DEMO", "source_url": "https://truthsocial.com/demo/4", "original_url": "https://truthsocial.com/demo/4",
         "verification": "Verified", "direction_override": "", "symbols_override": "", "context": "Demo – Branchenaussage"},
        {"statement_at": (now - timedelta(days=3)).date().isoformat(), "quote": "[DEMO – keine echte Äußerung] Halvard deal approved.",
         "source_name": "DEMO-Blog", "source_url": "https://demo-blog.example/5", "original_url": "https://demo-blog.example/5",
         "verification": "", "direction_override": "", "symbols_override": "DM04", "context": "Demo – unverifiziert, nur Datum"},
    ]
    trump = process_trump(rows, aliases, set(secs), now)
    pol_events = [{"id": stable_id("pe1"), "event_at": iso(now - timedelta(days=4)), "date_only": False,
                   "title": "[DEMO] Exportkontrolle für Halbleiter-Equipment verschärft", "category": "Exportkontrollen",
                   "symbols": ["DM08", "DM16"], "sectors": ["Halbleiter"], "direction": "negative",
                   "source_url": "https://www.commerce.gov/demo", "verification": "Verified", "note": "Demo"}]
    pol_trades = [{"id": stable_id("pt1"), "politician": "Demo-Abgeordnete/r", "chamber": "House", "party": "-",
                   "symbol": "DM06", "transaction_type": "purchase", "transaction_date": (now - timedelta(days=40)).date().isoformat(),
                   "disclosure_date": (now - timedelta(days=6)).date().isoformat(), "reporting_delay_days": 34,
                   "amount_range": [15001.0, 50000.0], "source_url": "https://disclosures-clerk.house.gov/demo", "note": "Demo"}]
    posts = []
    for k in range(120):
        sym = rng.choice(["DM01", "DM01", "DM01", "DM07", "DM09", "DM11"])
        pump = sym == "DM01" and k % 2 == 0
        txt = f"${sym} to the moon \U0001F680 load up now 100x" if pump else f"${sym} solide Zahlen, bullish auf Wachstum"
        posts.append({"id": f"p{k}", "platform": rng.choice(["reddit", "x"]), "author": "pumpbot" if pump else f"user{k % 17}",
                      "posted_at": iso(now - timedelta(hours=rng.uniform(0, 24 * 9))), "url": f"https://demo-social.example/{k}",
                      "text": txt, "engagement": rng.randint(0, 400), "symbols": [sym], "origin": "demo"})
    social_stats = analyze(posts, now)
    insiders = []
    for k in range(25):
        sym = f"DM{rng.randint(1, 20):02d}"
        code = rng.choice(["P", "S", "M", "A", "F", "S"])
        kinds = {"P": ("buy", "Kauf am offenen Markt", True), "S": ("sell", "Verkauf am offenen Markt", True),
                 "M": ("option_exercise", "Optionsausübung", False), "A": ("award", "Zuteilung (Vergütung)", False),
                 "F": ("tax_withholding", "Steuereinbehalt bei Vergütung", False)}[code]
        txd = now - timedelta(days=rng.randint(2, 60))
        sh, px = rng.randint(500, 40000), rng.uniform(20, 300)
        insiders.append({"id": f"i{k}", "symbol": sym, "insider": f"Demo Person {k}", "role": rng.choice(["CEO", "CFO", "Director"]),
                         "transaction_code": code, "transaction_kind": kinds[0], "transaction_label": kinds[1], "open_market": kinds[2],
                         "rule_10b5_1_plan": code == "S" and k % 2 == 0, "transaction_date": txd.date().isoformat(),
                         "filed_at": (txd + timedelta(days=2)).date().isoformat(), "reporting_delay_days": 2, "shares": sh,
                         "price": round(px, 2), "value": round(sh * px, 2), "currency": "USD", "source": "DEMO",
                         "source_url": "https://www.sec.gov/demo"})
    insiders.sort(key=lambda x: x["filed_at"], reverse=True)
    institutions = [{"id": f"h{k}", "institution": f"Demo Capital {k}", "symbol": f"DM{rng.randint(1, 20):02d}",
                     "report_period": "2026-06-30", "filed_at": "2026-08-14", "publication_delay_days": 45,
                     "shares": rng.randint(100_000, 5_000_000), "shares_change": rng.randint(-1_000_000, 1_000_000), "value_usd": rng.uniform(1e6, 4e8),
                     "position_status": rng.choice(["new", "increased", "reduced", "closed"]), "pct_outstanding": round(rng.uniform(0.1, 6), 2),
                     "source_url": "https://www.sec.gov/demo", "note": "Quartalsmeldung zum Stichtag – keine Echtzeit-Transaktion"} for k in range(18)]

    # Echter Kalender (offizielle Termine) + Demo-Nachrichten
    real_cal_dir = Path(__file__).resolve().parents[1] / "data" / "imports"
    config.IMPORT_DIR = real_cal_dir
    cal = load_calendar(now)
    config.IMPORT_DIR = tmp / "imports"
    cur = [{"id": f"n{k}", "kind": "news", "title": t, "summary": "Synthetische Demo-Meldung.", "time": iso(now - timedelta(hours=h)),
            "date_only": False, "timezone": "UTC", "source": "DEMO", "url": "https://demo-news.example/macro",
            "relevance": "Gesamtwirtschaft", "relevance_level": lvl, "categories": cats, "markets": mk, "sectors": [], "tickers": [],
            "direction": d, "verification": "Unverified", "status": "published", "captured_at": iso(now),
            "last_checked_at": iso(now), "changes": []}
           for k, (t, h, lvl, cats, mk, d) in enumerate([
               ("[DEMO] Zentralbank belässt Leitzins unverändert", 20, "high", ["Zentralbank"], ["USA", "global"], "unclear"),
               ("[DEMO] Verbraucherpreise steigen stärker als im Vormonat", 30, "high", ["Inflation"], ["Europa"], "negative"),
               ("[DEMO] Neue Zollrunde auf Stahlimporte angekündigt", 50, "medium", ["Handel/Zölle"], ["USA", "Europa"], "mixed"),
               ("[DEMO] Ölpreis fällt nach Fördererhöhung", 70, "medium", ["Energie/Rohstoffe"], ["global"], "unclear")])]
    for e in cal:
        e["summary"] = (e["summary"] + " (echter Termin aus market_calendar.csv)").strip()
    mev = {"current": cur, "upcoming": sorted([e for e in cal if e["status"] == "planned"], key=lambda x: x["time"]),
           "feeds": [{"id": f["id"], "name": f["name"], "status": "demo"} for f in config.MARKET_NEWS_FEEDS]}

    runlog = [{"step": s, "status": "ok", "seconds": round(rng.uniform(0.5, 40), 1)} for s in
              ["universe", "prices", "fundamentals", "news_rss", "trump", "insider_sec", "market_events"]]
    runlog.append({"step": "social", "status": "error", "seconds": 0.2, "message": "DEMO: Beispiel für protokollierten Fehler"})
    # DEMO-Superinvestoren: fiktive Depots, über dieselbe Vergleichslogik wie die echten 13F-Daten
    from .superinvestors import compare
    si_managers, si_agg = [], {}
    for k, (mgr, fund) in enumerate([("Demo-Investor A", "Alpha Capital (DEMO)"), ("Demo-Investor B", "Beta Partners (DEMO)"),
                                     ("Demo-Investor C", "Gamma Fund (DEMO)")]):
        picks = rng.sample([f"DM{i:02d}" for i in range(1, 20)], 8)
        cur = [{"cusip": f"DEMO{p}", "issuer": secs[p]["name"], "title": "COM", "put_call": None,
                "shares": float(rng.randint(1_000, 90_000)), "value": float(rng.randint(1, 40)) * 1e7} for p in picks[:6]]
        prev = [{**c, "shares": c["shares"] * rng.choice([0.5, 1.0, 1.4])} for c in cur[1:]] + \
               [{"cusip": f"DEMO{p}", "issuer": secs[p]["name"], "title": "COM", "put_call": None, "shares": 5000.0, "value": 2e7} for p in picks[6:]]
        pos = compare(cur, prev)
        for p_ in pos:
            p_["symbol"], p_["in_universe"] = p_["cusip"][4:], True
            a_ = si_agg.setdefault(p_["symbol"], {"symbol": p_["symbol"], "cusip": p_["cusip"], "issuer": p_["issuer"], "in_universe": True,
                                                  "holders": 0, "buyers": 0, "new_buyers": 0, "sellers": 0, "sold_out": 0, "value": 0.0, "managers": []})
            a_["holders"] += p_["action"] != "sold_out"; a_["buyers"] += p_["action"] in ("new", "increased")
            a_["new_buyers"] += p_["action"] == "new"; a_["sellers"] += p_["action"] in ("reduced", "sold_out")
            a_["sold_out"] += p_["action"] == "sold_out"; a_["value"] += p_["value"]
            a_["managers"].append({"manager": mgr, "fund": fund, "action": p_["action"], "weight_pct": p_["weight_pct"],
                                   "shares_change_pct": p_["shares_change_pct"], "value": p_["value"], "report_date": "2026-09-30"})
        si_managers.append({"cik": 9000 + k, "manager": mgr, "fund": fund, "sec_name": fund, "report_date": "2026-09-30",
                            "filed_at": "2026-10-28", "filing_url": "https://www.sec.gov/demo",
                            "portfolio_value": sum(p_["value"] for p_ in pos), "holdings": sum(p_["action"] != "sold_out" for p_ in pos),
                            "new": sum(p_["action"] == "new" for p_ in pos), "sold_out": sum(p_["action"] == "sold_out" for p_ in pos), "positions": pos})
    superinv = {"managers": si_managers, "stocks": sorted(si_agg.values(), key=lambda a_: -a_["holders"]), "errors": [],
                "note": "DEMO: fiktive Investoren und Depots."}
    insiders += [{**insiders[0], "id": "cb1", "symbol": "DM03", "insider": "Demo Cluster 1", "transaction_kind": "buy", "open_market": True,
                  "transaction_label": "Kauf am offenen Markt", "transaction_date": (now - timedelta(days=3)).date().isoformat()},
                 {**insiders[0], "id": "cb2", "symbol": "DM03", "insider": "Demo Cluster 2", "transaction_kind": "buy", "open_market": True,
                  "transaction_label": "Kauf am offenen Markt", "transaction_date": (now - timedelta(days=5)).date().isoformat()}]

    payloads, details = assemble(state=state, prices=prices, fundamentals=funds, signals=sigs, trump=trump,
                                 pol_events=pol_events, pol_trades=pol_trades, social_stats=social_stats, insiders=insiders,
                                 institutions=institutions, market_events=mev, runlog=runlog, sources=SOURCES, mode="demo", now=now,
                                 superinv=superinv)
    from .alerts import candidates
    from .setups import ENTRY, FILTER, SETUP_INFO
    meta = {"generated_at": iso(now), "schema_version": payloads["summary.json"]["schema_version"], "mode": "demo"}
    payloads["swing.json"] = {**meta, "setups": SETUP_INFO, "filter": FILTER, "entry": ENTRY,
                              "candidates": [x["symbol"] for x in candidates(payloads["stocks.json"]["stocks"])]}
    payloads["alerts.json"] = {**meta, "watchlist": ["DM03", "DM07"], "watchlist_file": "DEMO", "new_count": 1,
                               "channels": {"push": False, "email": False},
                               "history": [{"key": "demo", "kind": "cluster", "kind_label": "Cluster-Kauf", "symbol": "DM03",
                                            "title": "DM03: Cluster-Kauf", "text": "2 Insider kaufen (DEMO)", "url": None,
                                            "priority": 1, "created_at": iso(now)}]}
    from .report import build_report, confluence
    conf = confluence(payloads["stocks.json"]["stocks"])
    payloads["confluence.json"] = {**meta, "rows": conf}
    payloads["report.json"] = {**meta, **build_report(stocks=payloads["stocks.json"]["stocks"],
                               candidates=candidates(payloads["stocks.json"]["stocks"]), alerts_history=payloads["alerts.json"]["history"],
                               market_events=mev, insiders_clusters=[], superinv=superinv, pol_trades=pol_trades, trump=trump,
                               social_stats=social_stats, watchlist=["DM03", "DM07"], conf=conf, now=now)}
    out_dir = out_dir or (Path(__file__).resolve().parents[2] / "frontend" / "public" / "demo-data")
    return publish(payloads, details, out_dir)


if __name__ == "__main__":
    print(build_demo())
