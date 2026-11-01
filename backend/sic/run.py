"""Pipeline des Stock Intelligence Cockpit.

    python -m sic.run                 # vollstaendiger Lauf (GitHub Actions)
    python -m sic.run --no-fetch      # nur Zustand + CSV-Importe neu auswerten
    python -m sic.run --skip-fundamentals --skip-insider

Jeder Schritt laeuft isoliert: ein Fehler wird protokolliert und als Status ausgewiesen,
ohne die uebrigen Daten zu verwerfen. Veröffentlicht wird nur nach Validierung.
"""
from __future__ import annotations

import argparse
import os
import logging
import time
import traceback
from collections import Counter
from datetime import datetime

from . import alerts, config, report, congress, corporate_events, events, insider, news, politics, social, superinvestors, translate, universe
from .export import publish
from .intelligence import market_intelligence
from .market import fetch_prices, load_fundamentals, refresh_fundamentals
from .quality import load_manual_assessments, score_quality
from .risk import load_manual_risks, score_risk
from .signals import (cluster_signals, load_factcheck_overrides, load_store, merge_into_store,
                      save_store, verify, VERIFICATION, in_window)
from .util import iso, read_json, utcnow, write_json_atomic

log = logging.getLogger("sic")
SCHEMA_VERSION = "1.1.0"
PRICES_CACHE = config.CACHE_DIR / "prices.json"


class RunLog:
    def __init__(self):
        self.steps: list[dict] = []

    def step(self, name: str, fn, *a, **kw):
        t0 = time.time()
        try:
            res = fn(*a, **kw)
            self.steps.append({"step": name, "status": "ok", "seconds": round(time.time() - t0, 1)})
            return res
        except Exception as exc:  # noqa: BLE001
            log.error("Schritt %s fehlgeschlagen: %s\n%s", name, exc, traceback.format_exc())
            self.steps.append({"step": name, "status": "error", "seconds": round(time.time() - t0, 1),
                               "message": str(exc)[:300]})
            return None


def _memberships(sec: dict) -> list[str]:
    return sorted({m["index"] for m in sec["memberships"] if m.get("until") is None})


def _swing(mkt: dict | None, market_cap: float | None) -> dict | None:
    """Swing-Auswertung übernehmen; Marktkapitalisierung (S02) aus den Fundamentaldaten nachprüfen."""
    sw = (mkt or {}).get("swing")
    if not sw:
        return None
    sw = {**sw, "criteria": {k: dict(v) for k, v in sw["criteria"].items()}}
    if market_cap is not None and "Marktkap. > 1 Mrd." in sw["criteria"].get("S02", {}):
        sw["criteria"]["S02"]["Marktkap. > 1 Mrd."] = market_cap > 1e9
        sw["hits"] = [h for h in sw["hits"] if h != "S02" or all(sw["criteria"]["S02"].values())]
    return sw


def assemble(*, state: dict, prices: dict, fundamentals: dict[str, dict], signals: list[dict],
             trump: list[dict], pol_events: list[dict], pol_trades: list[dict], social_stats: dict,
             insiders: list[dict], institutions: list[dict], market_events: dict, runlog: list[dict],
             sources: list[dict], mode: str = "live", now: datetime | None = None,
             superinv: dict | None = None, corp_events: dict | None = None, extras: dict | None = None) -> tuple[dict, dict]:
    now = now or utcnow()
    meta = {"generated_at": iso(now), "schema_version": SCHEMA_VERSION, "mode": mode}
    manual_q, manual_r = load_manual_assessments(), load_manual_risks()
    stocks, details = [], {}
    pol_scores = {}
    by_sym: dict[str, list[dict]] = {}
    for s in signals:
        for x in s["symbols"]:
            by_sym.setdefault(x, []).append(s)
    ins_by: dict[str, list[dict]] = {}
    for x in insiders:
        ins_by.setdefault(x["symbol"], []).append(x)
    superinv = superinv or {"managers": [], "stocks": [], "errors": []}
    corp_events = corp_events or {}
    extras = extras or {}
    for a in superinv["stocks"]:
        if a.get("symbol") in corp_events:
            a["events"] = corp_events[a["symbol"]]
    pt_by: dict[str, list[dict]] = {}
    for x in pol_trades:
        pt_by.setdefault(x["symbol"], []).append(x)
    si_by = {a["symbol"]: a for a in superinv["stocks"] if a.get("symbol")}
    for sym, sec in sorted(state["securities"].items()):
        fc = fundamentals.get(sym)
        fund = (fc or {}).get("data")
        sector = (fund or {}).get("sector") or sec.get("sector")
        mkt = prices.get(sym)
        q = score_quality(sym, fund, sector, fc, manual_q)
        pol = politics.political_score(sym, sector, trump, pol_events, now)
        pol_scores[sym] = pol
        ins = insider.insider_summary(sym, ins_by.get(sym, []))
        soc = social_stats.get(sym)
        mi = market_intelligence(sym, by_sym.get(sym, []), mkt, soc, ins)
        rk = score_risk(fund, mkt, pol, manual_r.get(sym), is_financial=q["model"] == "financial")
        flags = list((mkt or {}).get("flags", []))
        if fc is None:
            flags.append("no_fundamentals")
        data_status = "error" if "no_price_data" in flags else ("warning" if flags else "ok")
        row = {
            "symbol": sym, "name": (fund or {}).get("long_name") or sec["name"], "region": sec["region"],
            "currency": sec["currency"], "sector": sector, "industry": (fund or {}).get("industry"),
            "indexes": _memberships(sec), "status": sec["status"], "status_reason": sec.get("status_reason"),
            "data_status": data_status, "data_flags": flags,
            "market": {k: (mkt or {}).get(k) for k in ("last_close", "price_date", "perf_20d", "perf_63d", "adr20",
                                                       "rvol", "ema10", "ema21", "sma50", "sma200")},
            "market_cap": (fund or {}).get("market_cap"), "market_cap_currency": (fund or {}).get("market_cap_currency"),
            "swing": _swing(mkt, (fund or {}).get("market_cap")),
            "quality": {"score": q["score"], "coverage_pct": q["coverage_pct"], "model": q["model"],
                        "dimensions": {d["key"]: d["score"] for d in q["dimensions"]}},
            "risk": {"score": rk["score"], "level": rk["level"], "coverage_pct": rk["coverage_pct"], "top_factors": rk["top_factors"]},
            "market_intelligence": {"score": mi["score"], "drivers": mi["drivers"],
                                    "independent_7d": mi["windows"]["7d"]["independent"],
                                    "independent_24h": mi["windows"]["24h"]["independent"]},
            "political": {k: pol[k] for k in ("relevance", "trump_bonus", "trump_bonus_active", "direction",
                                              "negative_signals_30d", "positive_signals_30d")},
            "social": {"mentions_7d": soc["mentions_7d"], "manipulation_risk": soc["manipulation_risk"],
                       "mentions_24h": soc["mentions_24h"], "sentiment_7d": soc.get("sentiment_7d"),
                       "bullish_7d": soc.get("bullish_7d"), "bearish_7d": soc.get("bearish_7d")} if soc else None,
            "insider": ins,
            "superinvestors": {k: si_by[sym][k] for k in ("holders", "buyers", "new_buyers", "sellers", "sold_out")} if sym in si_by else None,
            "events": corp_events.get(sym, []),
            "politicians": {"buys": sum(1 for x in pt_by.get(sym, []) if x["transaction_type"] == "purchase"),
                            "sells": sum(1 for x in pt_by.get(sym, []) if x["transaction_type"] in ("sale", "sale_partial"))}
            if sym in pt_by else None,
        }
        stocks.append(row)
        sym_signals = by_sym.get(sym, [])[:60]
        details[sym] = {
            **meta, "profile": {**row, "first_seen": sec.get("first_seen"), "archived_at": sec.get("archived_at"),
                                "country": (fund or {}).get("country")},
            "memberships": sec["memberships"],
            "market_detail": mkt, "quality_detail": q, "risk_detail": rk, "intelligence_detail": mi,
            "political_detail": pol,
            "trump_mentions": [t for t in trump if t["symbol"] == sym][:30],
            "political_events": [e for e in pol_events if sym in e["symbols"]][:30],
            "signals": sym_signals,
            "insiders": ins_by.get(sym, [])[:50],
            "institutions": [x for x in institutions if x["symbol"] == sym][:50],
            "political_trades": pt_by.get(sym, [])[:50],
            "big_stakes": [x for x in extras.get("stakes", []) if x["symbol"] == sym][:20],
            "superinvestors": si_by[sym]["managers"] if sym in si_by else [],
            "social_detail": soc,
            "history": [h for h in state.get("history", []) if h["symbol"] == sym][-20:],
        }

    active = [s for s in stocks if s["status"] == "active"]
    qs = [s["quality"]["score"] for s in active if s["quality"]["score"] is not None]
    buckets = Counter(("80-100" if v >= 80 else "60-79" if v >= 60 else "40-59" if v >= 40 else "0-39") for v in qs)
    radar = sorted([s for s in active if (s["market_intelligence"]["score"] or 0) > 0
                    and s["market_intelligence"]["independent_7d"] >= 1],
                   key=lambda s: s["market_intelligence"]["score"], reverse=True)[:100]
    vstat = Counter(s["verification"] for s in signals)
    summary = {
        **meta,
        "universe": {
            "active": len(active), "archived": len(stocks) - len(active),
            "index_positions": universe.index_positions(state),
            "indexes": list(state.get("indexes", {}).values()),
            "upcoming_changes": state.get("upcoming_changes", []),
            "built_at": state.get("built_at"),
        },
        "coverage": {
            "prices_pct": round(100 * sum(1 for s in active if s["market"]["last_close"] is not None) / max(len(active), 1)),
            "fundamentals_pct": round(100 * sum(1 for s in active if "no_fundamentals" not in s["data_flags"]) / max(len(active), 1)),
            "quality_scored_pct": round(100 * len(qs) / max(len(active), 1)),
            "avg_quality_coverage_pct": round(sum(s["quality"]["coverage_pct"] for s in active) / max(len(active), 1)),
            "data_errors": sum(1 for s in active if s["data_status"] == "error"),
        },
        "quality_distribution": {k: buckets.get(k, 0) for k in ("0-39", "40-59", "60-79", "80-100")},
        "freshness": {
            "latest_price_date": max((s["market"]["price_date"] for s in active if s["market"]["price_date"]), default=None),
            "signals_24h": sum(1 for s in signals if in_window(s, 24, now)),
            "trump_bonus_active": sum(1 for t in trump if t["bonus"]["active"]),
            "upcoming_events": len(market_events.get("upcoming", [])),
        },
        "verification_counts": {k: vstat.get(k, 0) for k in VERIFICATION},
        "sources": sources,
        "steps": runlog,
        "errors": [s for s in runlog if s["status"] == "error"],
        "disclaimer": "Informations- und Analyseplattform. Keine Anlageberatung, keine Kauf-/Verkaufsempfehlung.",
    }
    recent = [s for s in signals if in_window(s, 24 * 30, now)]
    payloads = {
        "summary.json": summary,
        "stocks.json": {**meta, "stocks": stocks},
        "intelligence.json": {**meta, "signals": recent[:3000],
                              "radar": [{"symbol": s["symbol"], "name": s["name"], "score": s["market_intelligence"]["score"],
                                         "drivers": s["market_intelligence"]["drivers"],
                                         "independent_24h": s["market_intelligence"]["independent_24h"],
                                         "independent_7d": s["market_intelligence"]["independent_7d"],
                                         "quality": s["quality"]["score"], "risk": s["risk"]["score"],
                                         "risk_level": s["risk"]["level"], "political_direction": s["political"]["direction"],
                                         "political": s["political"]["relevance"],
                                         "indexes": s["indexes"], "sector": s["sector"]} for s in radar]},
        "politics.json": {**meta, "events": pol_events, "trades": pol_trades,
                          "congress_status": extras.get("congress_status", []),
                          "unparsed_reports": extras.get("unparsed_reports", []),
                          "scores": {k: v for k, v in pol_scores.items() if v["relevance"] > 0}},
        "trump-mentions.json": {**meta, "rule": {"max_age_days": config.TRUMP_MAX_AGE_DAYS, "bonus_levels": config.TRUMP_BONUS,
                                                 "text": "Sonderbonus nur für verifizierte, direkte oder eindeutig indirekte "
                                                         "Unternehmensnennungen, deren Originalzeitpunkt höchstens "
                                                         f"{config.TRUMP_MAX_AGE_DAYS} Kalendertage zurückliegt. "
                                                         "Erhöht nie den Company Quality Score."},
                                "mentions": trump, "source_status": dict(politics.TRUMP_STATUS)},
        "market-events.json": {**meta, **{k: v for k, v in market_events.items() if k != "generated_at"}},
        "social.json": {**meta, "stocks": social_stats, "sources": extras.get("social_sources", []),
                        "stocktwits_trending": extras.get("stocktwits_trending", []),
                        "note": "Sentiment = Einschätzung: Bullish/Bearish-Kennzeichnung der StockTwits-Nutzer, sonst Lexikon."},
        "fact-checks.json": {**meta, "status_counts": {k: vstat.get(k, 0) for k in VERIFICATION},
                             "checks": [{"id": s["id"], "symbols": s["symbols"], "title": s["title"], "title_de": s.get("title_de"), "url": s["url"],
                                         "source": s["source"], "published_at": s["published_at"],
                                         "verification": s["verification"], "independence": s["independence"],
                                         "primary_source": s["primary_source"], "cluster_id": s["cluster_id"],
                                         "fact_check": s.get("fact_check")} for s in recent[:2000]],
                             "rules": ["Primärquelle -> Verified", "mind. 2 unabhängige Portale -> Partially Verified",
                                       "Einzelquelle -> Unverified", "> 30 Tage ohne Primärquelle -> Outdated",
                                       "Disputed/False nur per dokumentiertem Fact-Check (fact_checks.csv)"]},
        "superinvestors.json": {**meta, **{k: v for k, v in superinv.items() if k != "generated_at"},
                                "stakes": extras.get("stakes", []),
                                "insider_trades": [x for x in insiders if x.get("superinvestor")][:200]},
        "insider.json": {**meta, "insiders": insiders[:3000], "institutions": institutions[:3000],
                         "cluster_buys": insider.cluster_buys(insiders, now=now)[:100],
                         "political_trades": pol_trades,
                         "notes": ["Open-Market-Käufe/-Verkäufe getrennt von Optionsausübung und Vergütung",
                                   "13F-Daten sind Quartalsstichtage mit bis zu 45 Tagen Veröffentlichungsverzug",
                                   "Politische Geschäfte: Wertbandbreiten und Meldeverzug laut Offenlegung"]},
    }
    return payloads, details


SOURCES = [
    {"area": "Kurse/Fundamentaldaten", "source": "Yahoo Finance (yfinance)", "status": "connected",
     "limitation": "Inoffizieller Zugang; Limits/Bedingungen prüfen; Daten ggf. verzögert"},
    {"area": "Indexzusammensetzung", "source": "Wikipedia (CC BY-SA), iShares IWM (Russell-2000-Proxy)", "status": "connected",
     "limitation": "Kein offizielles Wirksamkeitsdatum; angekündigte Änderungen per index_changes.csv"},
    {"area": "Nachrichten", "source": "Yahoo-Finance-RSS je Ticker, CSV-Import", "status": "connected",
     "limitation": "Nur Schlagzeilen; rotierende Abfrage wegen Rate-Limits"},
    {"area": "Trump-Aussagen", "source": "Truth Social (öffentliche Schnittstelle), whitehouse.gov RSS, CSV-Import", "status": "connected",
     "limitation": "Truth Social kann Server-Abrufe blockieren; Status im Trump-Radar"},
    {"area": "Wirtschaftsticker", "source": "Fed, EZB, BLS (RSS); market_calendar.csv", "status": "connected",
     "limitation": "Termine aus offiziellen Kalendern per CSV gepflegt"},
    {"area": "Insider USA", "source": "SEC EDGAR Form 4 (Tagesindex, gesamter Markt)", "status": "connected",
     "limitation": "Alle Meldungen der letzten 30 Tage; User-Agent mit Kontakt (SIC_USER_AGENT) nötig"},
    {"area": "Superinvestoren (13F)", "source": "SEC EDGAR 13F-HR, CUSIP-Zuordnung über OpenFIGI", "status": "connected",
     "limitation": "Quartalsstichtag, bis 45 Tage Verzug; nur US-Long-Positionen; Managerliste in superinvestors.csv"},
    {"area": "Insider DE / Institutionen / Politiker", "source": "CSV-Import (BaFin, 13F, Offenlegungsstellen)", "status": "limited",
     "limitation": "Keine kostenlose strukturierte API eingebunden"},
    {"area": "Politiker-Trades (US-Kongress)", "source": "House Clerk (PTR-PDFs), Senate eFD", "status": "connected",
     "limitation": "Bis 45 Tage Meldeverzug; Wertbandbreiten; gescannte Meldungen nur als Link; nur nicht-kommerzielle Nutzung"},
    {"area": "Unternehmenstermine", "source": "Nasdaq-Earnings-/Dividendenkalender, Yahoo (Nicht-US)", "status": "connected",
     "limitation": "Inoffizieller Zugang; Termine können sich verschieben"},
    {"area": "Social Media", "source": "Reddit (13 Subreddits, API oder RSS), StockTwits, CSV-Import", "status": "connected",
     "limitation": "X-API nicht kostenlos (StockTwits als Ersatz); Reddit ohne eigenen Zugang oft gedrosselt; nur nicht-kommerziell"},
]


def run(fetch: bool = True, skip_fundamentals: bool = False, skip_insider: bool = False, skip_news: bool = False,
        skip_prices: bool = False, morning: bool = False) -> dict:
    rl = RunLog()
    now = utcnow()
    state = rl.step("universe", universe.build_universe, fetch=fetch) or universe.load_state()
    syms = universe.active_symbols(state)
    if not syms:
        log.error("Universum leer – Abbruch ohne Veröffentlichung")
        return {"published": False, "errors": ["empty universe"]}
    uni = set(state["securities"])

    prices = read_json(PRICES_CACHE, {})
    if fetch and not skip_prices:
        res = rl.step("prices", fetch_prices, syms)
        if res:
            fresh, _errs = res
            prices.update(fresh)
            write_json_atomic(PRICES_CACHE, prices)
    if fetch and not skip_fundamentals:
        rl.step("fundamentals", refresh_fundamentals, syms)
    fundamentals = {s: f for s in uni if (f := load_fundamentals(s))}

    store = load_store()
    new_sigs = rl.step("news_csv", news.import_csv_news) or []
    if fetch and not skip_news:
        res = rl.step("news_rss", news.fetch_news, syms)
        if res:
            new_sigs += res[0]
    merge_into_store(store, new_sigs)
    signals = list(store.values())
    cluster_signals(signals)
    verify(signals, load_factcheck_overrides())
    save_store(store)
    signals.sort(key=lambda s: s.get("published_at") or "", reverse=True)

    alias_idx = politics.build_alias_index(state["securities"])
    fetched = (rl.step("trump_feeds", politics.fetch_trump_feeds) or []) if fetch else []
    rows = politics.load_trump_csv() + politics.trump_store(fetched, now)
    trump = rl.step("trump", politics.process_trump, rows, alias_idx, uni, now) or []
    pol_events = rl.step("political_events", politics.load_political_events) or []
    pol_trades = rl.step("political_trades", politics.load_political_trades) or []
    cg = rl.step("congress", congress.build, uni, fetch=fetch) or {"trades": [], "status": [], "unparsed_reports": []}
    pol_trades = pol_trades + cg["trades"]

    ins_new = rl.step("insider_csv", insider.import_csv_insiders) or []
    if fetch and not skip_insider:
        watch = {m["cik"]: m["manager"] for m in superinvestors.load_managers()}
        res = rl.step("insider_sec", insider.fetch_form4_daily, [s for s in syms if state["securities"][s]["region"] == "US"],
                      None, watch)
        if res:
            ins_new += res[0]
    insiders = insider.merge_store(ins_new)
    institutions = rl.step("institutions", insider.import_institutional) or []

    si = rl.step("superinvestors", superinvestors.build, state["securities"], fetch=fetch and not skip_insider) \
        or {"managers": [], "stocks": [], "errors": []}
    watch = {m["cik"]: m["manager"] for m in superinvestors.load_managers()}
    for x in insiders:
        if x.get("owner_cik") in watch:
            x["superinvestor"] = watch[x["owner_cik"]]
    stakes = insider.load_stakes(now=now)

    corp = rl.step("corporate_events", corporate_events.build, uni, fundamentals, fetch=fetch, now=now) or {}

    focus = [a["symbol"] for a in sorted(si["stocks"], key=lambda a: -a.get("buyers", 0)) if a.get("symbol")][:40]
    focus += [c["symbol"] for c in insider.cluster_buys(insiders, now=now)][:20]
    sres = rl.step("social", social.collect, uni, state["securities"], focus, fetch=fetch, now=now) or ([], {})
    posts, sinfo = sres
    social_stats = social.analyze(posts, now)

    mev = rl.step("market_events", events.build_market_events, fetch=fetch, now=now) or {"current": [], "upcoming": [], "feeds": []}

    # Englische Texte zusätzlich maschinell ins Deutsche übersetzen (Original bleibt maßgeblich)
    rl.step("translate", translate.translate_items, [
        (signals[:3000], ["title"]), (mev["current"] + mev["upcoming"], ["title", "summary"]),
        (trump, ["quote"]), (pol_events, ["title"])])

    payloads, details = assemble(state=state, prices=prices, fundamentals=fundamentals, signals=signals, trump=trump,
                                 pol_events=pol_events, pol_trades=pol_trades, social_stats=social_stats,
                                 insiders=insiders, institutions=institutions, market_events=mev,
                                 runlog=rl.steps, sources=SOURCES, mode="live", now=now, superinv=si, corp_events=corp,
                                 extras={"stakes": stakes, "congress_status": cg["status"],
                                         "unparsed_reports": cg["unparsed_reports"],
                                         "social_sources": sinfo.get("sources", []),
                                         "stocktwits_trending": sinfo.get("stocktwits_trending", [])})
    # Watchlist-Alarme und tägliche Swing-Kandidaten
    def _alerts():
        wl, wl_file = alerts.load_watchlist()
        gen = alerts.generate(stocks=payloads["stocks.json"]["stocks"], insiders=insiders,
                              clusters=insider.cluster_buys(insiders, now=now), superinv=si, stakes=stakes,
                              pol_trades=pol_trades, trump=trump, social_stats=social_stats, watchlist=wl, now=now)
        if morning:   # Kandidatenliste kommt morgens im Tagesbericht, nicht doppelt
            gen = [a for a in gen if a["kind"] != "digest"]
        return alerts.process(gen, wl, wl_file, notify=True, now=now)
    al = rl.step("alerts", _alerts) or {"watchlist": [], "history": [], "channels": {}, "new_count": 0}
    from .setups import ENTRY, FILTER, SETUP_INFO
    payloads["alerts.json"] = {"generated_at": iso(now), "schema_version": SCHEMA_VERSION, "mode": "live", **al}
    payloads["swing.json"] = {"generated_at": iso(now), "schema_version": SCHEMA_VERSION, "mode": "live",
                              "setups": SETUP_INFO, "filter": FILTER, "entry": ENTRY,
                              "candidates": [s["symbol"] for s in alerts.candidates(payloads["stocks.json"]["stocks"])]}
    # Signal-Zusammenfluss und Tagesbericht
    stocks_out = payloads["stocks.json"]["stocks"]
    conf = report.confluence(stocks_out)
    payloads["confluence.json"] = {"generated_at": iso(now), "schema_version": SCHEMA_VERSION, "mode": "live", "rows": conf}
    rep = rl.step("report", report.build_report, stocks=stocks_out, candidates=alerts.candidates(stocks_out),
                  alerts_history=al.get("history", []), market_events=mev, insiders_clusters=insider.cluster_buys(insiders, now=now),
                  superinv=si, pol_trades=pol_trades, trump=trump, social_stats=social_stats,
                  watchlist=al.get("watchlist", []), conf=conf, now=now, insiders=insiders,
                  trending=sinfo.get("stocktwits_trending", []))
    if rep:
        rep["sent"] = report.send_report(rep, os.environ.get("COCKPIT_URL")) if morning else False
        payloads["report.json"] = {"generated_at": iso(now), "schema_version": SCHEMA_VERSION, "mode": "live", **rep}
    payloads["summary.json"]["steps"] = rl.steps
    result = publish(payloads, details)
    log.info("Veröffentlicht: %s | Fehler: %s", result["published"], [s for s in rl.steps if s["status"] == "error"])
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Stock Intelligence Cockpit – Datenpipeline")
    ap.add_argument("--no-fetch", action="store_true", help="kein Netzwerkabruf; Zustand + CSV neu auswerten")
    ap.add_argument("--skip-fundamentals", action="store_true")
    ap.add_argument("--skip-insider", action="store_true")
    ap.add_argument("--skip-news", action="store_true")
    ap.add_argument("--morning", action="store_true", help="Morgenlauf: ohne Kurse/Fundamentaldaten, Tagesbericht verschicken")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    res = run(fetch=not a.no_fetch, skip_fundamentals=a.skip_fundamentals or a.morning, skip_insider=a.skip_insider,
              skip_news=a.skip_news, skip_prices=a.morning, morning=a.morning)
    raise SystemExit(0 if res.get("published") else 1)


if __name__ == "__main__":
    main()
