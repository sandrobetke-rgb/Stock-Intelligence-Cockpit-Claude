"""Political Intelligence und Trump Mention Radar (Lastenheft Kap. 6).

Kernregeln:
- Sonderbonus nur für Aussagen, deren ORIGINALER Äußerungs-/Veröffentlichungszeitpunkt
  höchstens TRUMP_MAX_AGE_DAYS Kalendertage zurückliegt; danach automatischer Verfall
- Kein Bonus bei unklarem Datum oder nicht verifizierbarer Originalquelle
- Direkte Nennung > eindeutig indirekt (nur mit dokumentierter Zuordnung) > Branche/Allgemein (kein Bonus)
- Wirkungsrichtung positiv/negativ/neutral getrennt; negative Aussagen nie als positives Signal
- Der Bonus beeinflusst niemals Company Quality
"""
from __future__ import annotations

import csv
import logging
import re
from datetime import datetime, timedelta, timezone

from . import config
from .signals import is_primary
from .util import domain_of, iso, normalize_text, parse_dt, stable_id, utcnow

log = logging.getLogger("sic.politics")

TRUMP_OFFICIAL_DOMAINS = {"whitehouse.gov", "truthsocial.com", "govinfo.gov", "federalregister.gov"}

NAME_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "company", "co", "plc", "ag", "se", "sa", "nv",
                 "holdings", "holding", "group", "ltd", "limited", "the", "class", "a", "b", "c", "lp", "llc",
                 "kgaa", "co kgaa", "international", "technologies", "com"}
# Firmennamen, die zugleich gaengige Woerter sind -> Zuordnung nur nach Prüfung
AMBIGUOUS = {"target", "apple", "visa", "gap", "ball", "match", "block", "meta", "best", "general", "united",
             "first", "american", "national", "public", "global", "southern", "progressive", "boston",
             "fox", "news", "delta", "air", "energy", "gold", "home", "live", "now", "on", "snap", "square",
             "carrier", "graco", "lennar", "ross", "masco", "nucor", "progress", "realty", "edison"}

SECTOR_TERMS = {
    "Halbleiter": ["chip", "chips", "semiconductor", "semiconductors"],
    "Pharma": ["pharma", "drug prices", "drugmakers", "pharmaceutical"],
    "Automobil": ["car makers", "automakers", "auto industry", "cars", "autos"],
    "Stahl/Aluminium": ["steel", "aluminum"],
    "Energie": ["oil", "drilling", "natural gas", "coal", "lng", "energy companies"],
    "Verteidigung": ["defense contractors", "weapons makers", "defense industry"],
    "Banken": ["banks", "big banks", "bankers"],
    "Tech/Plattformen": ["big tech", "social media companies", "tech companies"],
}

NEG = ["tariff", "tariffs", "ban", "banned", "sanction", "penalt", "investigat", "lawsuit", "sue ", "terrible",
       "disgrace", "boycott", "fine ", "fined", "punish", "restrict", "export control", "antitrust", "break up",
       "bad ", "failing", "unfair", "cancel", "terminate", "revoke", "probe"]
POS = ["great company", "invest", "investment", "deal", "agreement", "approve", "approved", "award", "contract",
       "tax cut", "subsid", "incentive", "thank", "congratulat", "fantastic", "jobs", "build", "expand",
       "partnership", "exempt", "relief", "great job"]


# ----------------------------------------------------------- Zuordnung ----
def core_name(name: str) -> str:
    toks = [t for t in normalize_text(name).split() if t not in NAME_SUFFIXES]
    return " ".join(toks)


def load_aliases() -> list[dict]:
    """aliases.csv: symbol,alias,kind(direct|indirect),rationale,source
    'indirect' braucht eine dokumentierte Begründung (z. B. 'the iPhone maker')."""
    p = config.IMPORT_DIR / "aliases.csv"
    out = []
    if p.exists():
        with p.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if not r.get("symbol") or r["symbol"].startswith("#") or not r.get("alias"):
                    continue
                kind = (r.get("kind") or "direct").strip()
                if kind == "indirect" and not (r.get("rationale") or "").strip():
                    continue
                out.append({"symbol": r["symbol"].strip().upper(), "alias": normalize_text(r["alias"]),
                            "kind": kind, "rationale": r.get("rationale", ""), "source": r.get("source", ""),
                            "reviewed": True})
    return out


def build_alias_index(securities: dict[str, dict]) -> list[dict]:
    idx = load_aliases()
    manual = {(a["symbol"], a["alias"]) for a in idx}
    for sym, sec in securities.items():
        cn = core_name(sec.get("name") or "")
        if len(cn) < 3 or (sym, cn) in manual:
            continue
        ambiguous = cn in AMBIGUOUS or (len(cn.split()) == 1 and len(cn) <= 4)
        idx.append({"symbol": sym, "alias": cn, "kind": "direct", "rationale": "Firmenname",
                    "source": "Universum", "reviewed": not ambiguous, "ambiguous": ambiguous})
    return idx


def link_entities(text: str, alias_index: list[dict], universe: set[str]) -> list[dict]:
    """Findet Unternehmensbezüge. Rückgabe je Treffer: symbol, mention_type, matched, mapping_verified."""
    hits: dict[str, dict] = {}
    raw = text or ""
    # 1) Cashtags/Boersenangaben = direkte, eindeutige Nennung
    for m in re.finditer(r"\$([A-Z]{1,5})\b|\((?:NASDAQ|NYSE|XETRA|ETR)\s*:\s*([A-Z.]{1,6})\)", raw):
        sym = (m.group(1) or m.group(2) or "").upper()
        if sym in universe:
            hits[sym] = {"symbol": sym, "mention_type": "direct", "matched": m.group(0), "mapping_verified": True,
                         "rationale": "Ticker eindeutig genannt"}
    norm = f" {normalize_text(raw)} "
    for a in alias_index:
        if a["symbol"] in hits or not a["alias"]:
            continue
        if f" {a['alias']} " in norm:
            hits[a["symbol"]] = {"symbol": a["symbol"], "mention_type": a["kind"], "matched": a["alias"],
                                 "mapping_verified": bool(a.get("reviewed")), "rationale": a.get("rationale"),
                                 "ambiguous": a.get("ambiguous", False)}
    return list(hits.values())


def detect_sectors(text: str) -> list[str]:
    norm = f" {normalize_text(text)} "
    return [sec for sec, terms in SECTOR_TERMS.items() if any(f" {normalize_text(t)} " in norm for t in terms)]


def direction(text: str) -> tuple[str, list[str]]:
    """Regelbasierte Wirkungsrichtung (algorithmisch, per CSV überschreibbar)."""
    t = (text or "").lower() + " "
    neg = [w.strip() for w in NEG if w in t]
    pos = [w.strip() for w in POS if w in t]
    if neg and not pos:
        return "negative", neg
    if pos and not neg:
        return "positive", pos
    if pos and neg:
        return "mixed", pos + neg
    return "neutral", []


# --------------------------------------------------------------- Trump ----
def trump_verification(url: str, explicit: str | None) -> str:
    if explicit in ("Verified", "Partially Verified", "Unverified", "Disputed", "False"):
        return explicit
    d = domain_of(url)
    if any(d == x or d.endswith("." + x) for x in TRUMP_OFFICIAL_DOMAINS):
        return "Verified"
    return "Partially Verified" if is_primary(url) else "Unverified"


def bonus_state(statement_at: datetime | None, date_only: bool, mention_type: str,
                mapping_verified: bool, verification: str, now: datetime | None = None) -> dict:
    """Fünf-Tage-Regel (6.2/6.4). Gibt aktiven Bonus, Ablaufzeit und Begründung zurück."""
    now = now or utcnow()
    if statement_at is None:
        return {"active": False, "value": 0, "reason": "Datum unklar – kein Sonderbonus", "expires_at": None,
                "age_days": None}
    # Reine Datumsangabe: Frist ab Tagesende bewertet, Unsicherheit gekennzeichnet
    anchor = statement_at + timedelta(hours=23, minutes=59) if date_only else statement_at
    expires = anchor + timedelta(days=config.TRUMP_MAX_AGE_DAYS)
    age_days = round((now - statement_at).total_seconds() / 86400, 2)
    base = {"expires_at": iso(expires), "age_days": age_days}
    if statement_at > now + timedelta(hours=1):
        return {**base, "active": False, "value": 0, "reason": "Zeitstempel in der Zukunft – prüfen"}
    if now > expires:
        return {**base, "active": False, "value": 0, "reason": f"Älter als {config.TRUMP_MAX_AGE_DAYS} Kalendertage – verfallen"}
    if verification not in ("Verified",):
        return {**base, "active": False, "value": 0, "reason": "Originalquelle nicht verifiziert – kein Sonderbonus"}
    if mention_type in ("sector", "general"):
        return {**base, "active": False, "value": 0, "reason": "Branchen-/allgemeine Aussage – kein Unternehmensbonus"}
    if not mapping_verified:
        return {**base, "active": False, "value": 0, "reason": "Zuordnung nicht geprüft – kein Sonderbonus"}
    return {**base, "active": True, "value": config.TRUMP_BONUS.get(mention_type, 0),
            "reason": "Direkte, verifizierte Nennung" if mention_type == "direct" else "Eindeutig indirekte, dokumentierte Zuordnung"}


def load_trump_csv() -> list[dict]:
    """trump_statements.csv: statement_at,quote,source_name,source_url,original_url,
    verification,direction_override,symbols_override,context
    statement_at = ORIGINALER Zeitpunkt (ISO mit Zeitzone; reines Datum erlaubt, wird gekennzeichnet)."""
    p = config.IMPORT_DIR / "trump_statements.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("quote") and not (r.get("statement_at") or "").startswith("#")]


def fetch_trump_feeds() -> list[dict]:
    import feedparser
    from .util import http_get

    rows = []
    for src in config.TRUMP_SOURCES:
        try:
            feed = feedparser.parse(http_get(src["url"]).content)
        except Exception as exc:  # noqa: BLE001
            log.warning("Trump-Quelle %s: %s", src["id"], exc)
            continue
        for e in feed.entries:
            text = f"{e.get('title', '')}. {re.sub('<[^>]+>', ' ', e.get('summary', ''))}"
            if "trump" not in text.lower() and "president" not in text.lower():
                continue
            rows.append({"statement_at": e.get("published"), "quote": text[:600], "source_name": "The White House",
                         "source_url": e.get("link", ""), "original_url": e.get("link", ""),
                         "verification": "", "direction_override": "", "symbols_override": "",
                         "context": src["id"]})
    return rows


def process_trump(rows: list[dict], alias_index: list[dict], universe: set[str], now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    out = []
    for r in rows:
        at, date_only = parse_dt(r.get("statement_at"))
        quote = (r.get("quote") or "").strip()
        url = (r.get("original_url") or r.get("source_url") or "").strip()
        ver = trump_verification(url, (r.get("verification") or "").strip() or None)
        dir_auto, cues = direction(quote)
        dir_final = (r.get("direction_override") or "").strip() or dir_auto
        overrides = [s.strip().upper() for s in (r.get("symbols_override") or "").split(";") if s.strip()]
        links = ([{"symbol": s, "mention_type": "direct", "matched": "manuell", "mapping_verified": True,
                   "rationale": "Manuelle, geprüfte Zuordnung"} for s in overrides if s in universe]
                 or link_entities(quote, alias_index, universe))
        sectors = detect_sectors(quote)
        base = {
            "statement_id": stable_id(url, quote[:120]), "quote": quote, "source_name": r.get("source_name") or domain_of(url),
            "source_url": url, "statement_at": iso(at), "date_only": date_only, "timezone": "UTC",
            "captured_at": iso(now), "verification": ver, "direction": dir_final,
            "direction_basis": "manual" if (r.get("direction_override") or "").strip() else "algorithmic",
            "direction_cues": cues, "context": r.get("context", ""), "sectors": sectors,
        }
        if not links:
            mtype = "sector" if sectors else "general"
            out.append({**base, "id": stable_id(base["statement_id"], mtype), "symbol": None, "mention_type": mtype,
                        "mapping_verified": False, "matched": None, "mapping_rationale": None,
                        "bonus": bonus_state(at, date_only, mtype, False, ver, now)})
            continue
        for ln in links:
            out.append({**base, "id": stable_id(base["statement_id"], ln["symbol"]), "symbol": ln["symbol"],
                        "mention_type": ln["mention_type"], "mapping_verified": ln["mapping_verified"],
                        "matched": ln["matched"], "mapping_rationale": ln.get("rationale"),
                        "ambiguous_name": ln.get("ambiguous", False),
                        "bonus": bonus_state(at, date_only, ln["mention_type"], ln["mapping_verified"], ver, now)})
    out.sort(key=lambda x: x["statement_at"] or "", reverse=True)
    return out


# ------------------------------------------------- weitere Politiksignale ----
def load_political_events() -> list[dict]:
    """political_events.csv: event_at,title,category,symbols,sectors,direction,source_url,verification,note
    category: Zölle|Sanktionen|Exportkontrollen|Subventionen|Staatsauftrag|Energiepolitik|Regulierung"""
    p = config.IMPORT_DIR / "political_events.csv"
    out = []
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("title") or (r.get("event_at") or "").startswith("#") or not r.get("source_url"):
                continue
            at, date_only = parse_dt(r.get("event_at"))
            out.append({"id": stable_id(r["source_url"], r["title"]), "event_at": iso(at), "date_only": date_only,
                        "title": r["title"], "category": r.get("category", "Regulierung"),
                        "symbols": [s.strip().upper() for s in (r.get("symbols") or "").split(";") if s.strip()],
                        "sectors": [s.strip() for s in (r.get("sectors") or "").split(";") if s.strip()],
                        "direction": r.get("direction") or direction(r["title"])[0],
                        "source_url": r["source_url"], "verification": r.get("verification") or trump_verification(r["source_url"], None),
                        "note": r.get("note", "")})
    return out


def load_political_trades(now: datetime | None = None) -> list[dict]:
    """political_trades.csv: politician,chamber,party,symbol,transaction_type,transaction_date,
    disclosure_date,amount_min,amount_max,source_url  (offizielle Offenlegungsstellen)"""
    p = config.IMPORT_DIR / "political_trades.csv"
    out = []
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("symbol") or (r.get("politician") or "").startswith("#"):
                continue
            tx, _ = parse_dt(r.get("transaction_date"))
            disc, _ = parse_dt(r.get("disclosure_date"))
            out.append({"id": stable_id(r.get("source_url"), r["politician"], r["symbol"], r.get("transaction_date")),
                        "politician": r["politician"], "chamber": r.get("chamber"), "party": r.get("party"),
                        "symbol": r["symbol"].strip().upper(), "transaction_type": r.get("transaction_type"),
                        "transaction_date": tx.date().isoformat() if tx else None,
                        "disclosure_date": disc.date().isoformat() if disc else None,
                        "reporting_delay_days": (disc - tx).days if tx and disc else None,
                        "amount_range": [float(r["amount_min"]) if r.get("amount_min") else None,
                                         float(r["amount_max"]) if r.get("amount_max") else None],
                        "source_url": r.get("source_url"),
                        "note": "Wertbandbreite laut Offenlegung; Meldeverzug beachten"})
    return out


def political_score(symbol: str, sector: str | None, trump: list[dict], events: list[dict],
                    now: datetime | None = None) -> dict:
    """Political Intelligence je Titel. Relevanz und Wirkungsrichtung getrennt."""
    now = now or utcnow()
    mine = [t for t in trump if t["symbol"] == symbol]
    active = [t for t in mine if t["bonus"]["active"]]
    trump_relevance = max((t["bonus"]["value"] for t in active), default=0)
    win = now - timedelta(days=30)
    ev = [e for e in events if symbol in e["symbols"] and (parse_dt(e["event_at"])[0] or now) >= win]
    neg30 = sum(1 for t in mine if t["direction"] == "negative" and (parse_dt(t["statement_at"])[0] or now) >= win)
    neg30 += sum(1 for e in ev if e["direction"] == "negative")
    pos30 = sum(1 for t in mine if t["direction"] == "positive" and (parse_dt(t["statement_at"])[0] or now) >= win)
    pos30 += sum(1 for e in ev if e["direction"] == "positive")
    relevance = min(100, trump_relevance * 2 + 15 * len(ev) + 5 * len(mine))
    dirs = {t["direction"] for t in active} | {e["direction"] for e in ev}
    if not dirs:
        net = "keine"
    elif dirs <= {"negative"}:
        net = "negative"
    elif dirs <= {"positive"}:
        net = "positive"
    else:
        net = "mixed"
    return {"relevance": relevance if (mine or ev) else 0, "trump_bonus": trump_relevance,
            "trump_bonus_active": bool(active), "direction": net, "positive_signals_30d": pos30,
            "negative_signals_30d": neg30, "mentions_total": len(mine), "events_30d": len(ev), "covered": True,
            "next_expiry": min((t["bonus"]["expires_at"] for t in active), default=None)}
