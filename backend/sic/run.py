"""Pipeline des Stock Intelligence Cockpit.

    python -m sic.run                 # vollstaendiger Lauf (GitHub Actions)
    python -m sic.run --no-fetch      # nur Zustand + CSV-Importe neu auswerten
    python -m sic.run --skip-fundamentals --skip-insider

Jeder Schritt laeuft isoliert: ein Fehler wird protokolliert und als Status ausgewiesen,
ohne die uebrigen Daten zu verwerfen. Veröffentlicht wird nur nach Validierung.
"""
from __future__ import annotations

import argparse
import logging
import time
import traceback
from collections import Counter
from datetime import datetime

from . import config, events, insider, news, politics, social, translate, universe
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


def assemble(*, state: dict, prices: dict, fundamentals: dict[str, dict], signals: list[dict],
             trump: list[dict], pol_events: list[dict], pol_trades: list[dict], social_stats: dict,
             insiders: list[dict], institutions: list[dict], market_events: dict, runlog: list[dict],
             sources: list[dict], mode: str = "live", now: datetime | None = None) -> tuple[dict, dict]:
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
            "quality": {"score": q["score"], "coverage_pct": q["coverage_pct"], "model": q["model"],
                        "dimensions": {d["key"]: d["score"] for d in q["dimensions"]}},
            "risk": {"score": rk["score"], "level": rk["level"], "coverage_pct": rk["coverage_pct"], "top_factors": rk["top_factors"]},
            "market_intelligence": {"score": mi["score"], "drivers": mi["drivers"],
                                    "independent_7d": mi["windows"]["7d"]["independent"],
                                    "independent_24h": mi["windows"]["24h"]["independent"]},
            "political": {k: pol[k] for k in ("relevance", "trump_bonus", "trump_bonus_active", "direction",
                                              "negative_signals_30d", "positive_signals_30d")},
            "social": {"mentions_7d": soc["mentions_7d"], "manipulation_risk": soc["manipulation_risk"]} if soc else None,
            "insider": ins,
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
            "political_trades": [x for x in pol_trades if x["symbol"] == sym][:50],
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
                          "scores": {k: v for k, v in pol_scores.items() if v["relevance"] > 0}},
        "trump-mentions.json": {**meta, "rule": {"max_age_days": config.TRUMP_MAX_AGE_DAYS, "bonus_levels": config.TRUMP_BONUS,
                                                 "text": "Sonderbonus nur für verifizierte, direkte oder eindeutig indirekte "
                                                         "Unternehmensnennungen, deren Originalzeitpunkt höchstens "
                                                         f"{config.TRUMP_MAX_AGE_DAYS} Kalendertage zurückliegt. "
                                                         "Erhöht nie den Company Quality Score."},
                                "mentions": trump},
        "market-events.json": {**meta, **{k: v for k, v in market_events.items() if k != "generated_at"}},
        "social.json": {**meta, "stocks": social_stats, "note": "Sentiment = algorithmische Einschätzung."},
        "fact-checks.json": {**meta, "status_counts": {k: vstat.get(k, 0) for k in VERIFICATION},
                             "checks": [{"id": s["id"], "symbols": s["symbols"], "title": s["title"], "title_de": s.get("title_de"), "url": s["url"],
                                         "source": s["source"], "published_at": s["published_at"],
                                         "verification": s["verification"], "independence": s["independence"],
                                         "primary_source": s["primary_source"], "cluster_id": s["cluster_id"],
                                         "fact_check": s.get("fact_check")} for s in recent[:2000]],
                             "rules": ["Primärqülle -> Verified", "mind. 2 unabhängige Portale -> Partially Verified",
                                       "Einzelquelle -> Unverified", "> 30 Tage ohne Primärqülle -> Outdated",
                                       "Disputed/False nur per dokumentiertem Fact-Check (fact_checks.csv)"]},
        "insider.json": {**meta, "insiders": insiders[:3000], "institutions": institutions[:3000],
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
    {"area": "Trump-Aussagen", "source": "whitehouse.gov RSS, CSV-Import (z. B. Truth Social)", "status": "limited",
     "limitation": "Truth Social ohne kostenlose API -> CSV mit Original-URL"},
    {"area": "Wirtschaftsticker", "source": "Fed, EZB, BLS (RSS); market_calendar.csv", "status": "connected",
     "limitation": "Termine aus offiziellen Kalendern per CSV gepflegt"},
    {"area": "Insider USA", "source": "SEC EDGAR Form 4", "status": "connected",
     "limitation": "Rotierende Abfrage; User-Agent mit Kontakt (SIC_USER_AGENT) nötig"},
    {"area": "Insider DE / Institutionen / Politiker", "source": "CSV-Import (BaFin, 13F, Offenlegungsstellen)", "status": "limited",
     "limitation": "Keine kostenlose strukturierte API eingebunden"},
    {"area": "Social Media", "source": "CSV-Import; Reddit-RSS optional (standardmäßig aus)", "status": "limited",
     "limitation": "X-API nicht kostenlos; Reddit-Bedingungen vor Aktivierung prüfen"},
]


def run(fetch: bool = True, skip_fundamentals: bool = False, skip_insider: bool = False, skip_news: bool = False) -> dict:
    rl = RunLog()
    now = utcnow()
    state = rl.step("universe", universe.build_universe, fetch=fetch) or universe.load_state()
    syms = universe.active_symbols(state)
    if not syms:
        log.error("Universum leer – Abbruch ohne Veröffentlichung")
        return {"published": False, "errors": ["empty universe"]}
    uni = set(state["securities"])

    prices = read_json(PRICES_CACHE, {})
    if fetch:
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
    rows = politics.load_trump_csv() + ((rl.step("trump_feeds", politics.fetch_trump_feeds) or []) if fetch else [])
    trump = rl.step("trump", politics.process_trump, rows, alias_idx, uni, now) or []
    pol_events = rl.step("political_events", politics.load_political_events) or []
    pol_trades = rl.step("political_trades", politics.load_political_trades) or []

    posts = rl.step("social", social.load_posts, uni) or []
    social_stats = social.analyze(posts, now)

    ins_new = rl.step("insider_csv", insider.import_csv_insiders) or []
    if fetch and not skip_insider:
        res = rl.step("insider_sec", insider.fetch_form4, [s for s in syms if state["securities"][s]["region"] == "US"])
        if res:
            ins_new += res[0]
    insiders = insider.merge_store(ins_new)
    institutions = rl.step("institutions", insider.import_institutional) or []

    mev = rl.step("market_events", events.build_market_events, fetch=fetch, now=now) or {"current": [], "upcoming": [], "feeds": []}

    # Englische Texte zusätzlich maschinell ins Deutsche übersetzen (Original bleibt maßgeblich)
    rl.step("translate", translate.translate_items, [
        (signals[:3000], ["title"]), (mev["current"] + mev["upcoming"], ["title", "summary"]),
        (trump, ["quote"]), (pol_events, ["title"])])

    payloads, details = assemble(state=state, prices=prices, fundamentals=fundamentals, signals=signals, trump=trump,
                                 pol_events=pol_events, pol_trades=pol_trades, social_stats=social_stats,
                                 insiders=insiders, institutions=institutions, market_events=mev,
                                 runlog=rl.steps, sources=SOURCES, mode="live", now=now)
    result = publish(payloads, details)
    log.info("Veröffentlicht: %s | Fehler: %s", result["published"], [s for s in rl.steps if s["status"] == "error"])
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Stock Intelligence Cockpit – Datenpipeline")
    ap.add_argument("--no-fetch", action="store_true", help="kein Netzwerkabruf; Zustand + CSV neu auswerten")
    ap.add_argument("--skip-fundamentals", action="store_true")
    ap.add_argument("--skip-insider", action="store_true")
    ap.add_argument("--skip-news", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    res = run(fetch=not a.no_fetch, skip_fundamentals=a.skip_fundamentals, skip_insider=a.skip_insider,
              skip_news=a.skip_news)
    raise SystemExit(0 if res.get("published") else 1)


if __name__ == "__main__":
    main()
