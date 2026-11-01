"""Social Media Intelligence (Lastenheft Kap. 9).

Quellen (alle kostenlos):
- Reddit: offizielle API mit eigenem kostenlosen App-Zugang (REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET),
  sonst öffentliche RSS-Feeds. Nicht-kommerzielle Nutzung gemäß Reddit-Bedingungen.
- StockTwits (börsenspezifische Alternative zu X): öffentliche API, Trending-Liste und Beiträge je
  Aktie; Bullish/Bearish wird vom Verfasser selbst gesetzt.
- CSV-Import (social_mentions.csv), z. B. für X-Beiträge (X-API ist nicht kostenlos).
Beiträge werden 30 Tage gespeichert, damit 24-Std./7-Tage/30-Tage-Vergleiche möglich sind.
Sentiment ist eine Einschätzung (Nutzerkennzeichnung oder Lexikon). Social Media erhöht nie Company Quality.
"""
from __future__ import annotations

import csv
import logging
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import requests

from . import config
from .util import RateLimiter, iso, jaccard, parse_dt, read_json, stable_id, tokens, utcnow, write_json_atomic

log = logging.getLogger("sic.social")
SUBREDDITS = ["wallstreetbets", "stocks", "investing", "StockMarket", "options", "pennystocks", "ValueInvesting",
              "Daytrading", "SecurityAnalysis", "dividends", "mauerstrassenwetten", "Finanzen", "wallstreetbetsGER"]
UA = "linux:stock-intelligence-cockpit:1.1 (private, non-commercial)"
PUMP = ["to the moon", "100x", "10x", "short squeeze", "next gme", "don't miss", "load up", "\U0001F680",
        "guaranteed", "easy money", "last chance", "lambo", "going parabolic"]
POS = ["bullish", "buy", "beat", "strong", "upgrade", "growth", "undervalued", "calls", "long", "breakout", "kaufen", "steigt"]
NEG = ["bearish", "sell", "miss", "weak", "downgrade", "fraud", "overvalued", "puts", "short", "dump", "bankrupt", "verkaufen", "fällt"]
# Ticker, die zugleich häufige Wörter/Abkürzungen sind: ohne $ nicht als Aktie zählen
COMMON = set("""A I AM AN ANY ALL ARE AT BE BIG BY CAN CEO CFO CTO DD EOD EPS ER ETF EV FOR FED GDP GO GOOD HAS HE
IMO IPO IT ITM IV LOL LOVE LOW MAN MAIN NEW NOW OK ON ONE OP OPEN OR OTM OUT PE PM PT REAL RUN SAFE SEC SO TA TV
UK US USA WSB YOLO FYI ATH ATM CPI IRA HSA LLC INC TLDR RIP EDIT POST BEST KEY PEAK WELL JOB EAT WISH BEAT SAVE
FUN PLAY HOME CASH NICE TRUE FAST AI DM CC EU AG SE TO UP WAY TOP HOLD GAIN LOSS RISK BULL BEAR PUMP DUMP MOON APE
APES CALL CALLS PUT PUTS LONG SHORT FREE NEXT LAST HUGE GAME CARE LIFE""".split())
_rl_reddit = RateLimiter(1.0)          # API mit Zugang: 100 Anfragen/Minute erlaubt
_rl_reddit_rss = RateLimiter(1 / 7)    # ohne Zugang: Reddit drosselt stark
_rl_st = RateLimiter(0.8)


def _store():
    return config.STATE_DIR / "social_posts.json"


# ------------------------------------------------------------ Erkennung ---
def symbol_resolver(universe: set[str], securities: dict[str, dict] | None = None):
    """Erzeugt eine Funktion text -> Symbole. Cashtags immer; Ticker ohne $ nur ab 3 Zeichen und
    kein häufiges Wort; eindeutige Firmennamen (geprüfte Aliasse) zusätzlich."""
    base = {}
    for s in universe:
        b = s.split(".")[0]
        if s.endswith(".DE") and b in universe:
            continue
        base.setdefault(b, s)
    aliases = []
    if securities:
        from .politics import build_alias_index
        aliases = [a for a in build_alias_index(securities) if a.get("reviewed") and len(a["alias"]) >= 4]

    def resolve(text: str) -> list[str]:
        t = text or ""
        found = {base[m.upper()] for m in re.findall(r"\$([A-Za-z][A-Za-z.]{0,5})\b", t) if m.upper() in base}
        for m in re.findall(r"(?<![\w$])([A-Z]{3,5})(?![\w])", t):
            if m in base and m not in COMMON:
                found.add(base[m])
        if aliases:
            from .util import normalize_text
            norm = f" {normalize_text(t)} "
            for a in aliases:
                if f" {a['alias']} " in norm:
                    found.add(a["symbol"])
        return sorted(found)
    return resolve


def extract_symbols(text: str, universe: set[str]) -> list[str]:
    """Kompatibel zur bisherigen Schnittstelle (ohne Firmennamen)."""
    return symbol_resolver(universe)(text)


def sentiment(text: str) -> float:
    t = (text or "").lower()
    p = sum(t.count(w) for w in POS)
    n = sum(t.count(w) for w in NEG)
    return 0.0 if p + n == 0 else round((p - n) / (p + n), 2)


def _post_sentiment(p: dict) -> float:
    lab = p.get("sentiment_label")
    return 1.0 if lab == "Bullish" else (-1.0 if lab == "Bearish" else sentiment(p["text"]))


# ---------------------------------------------------------------- Reddit --
def _reddit_token(sess: requests.Session) -> str | None:
    cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and sec):
        return None
    r = sess.post("https://www.reddit.com/api/v1/access_token", auth=(cid, sec),
                  data={"grant_type": "client_credentials"}, timeout=20)
    r.raise_for_status()
    return r.json().get("access_token")


def fetch_reddit(resolve) -> tuple[list[dict], dict]:
    import feedparser

    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    out, errors, mode = [], [], "rss"
    try:
        token = _reddit_token(sess)
    except Exception as exc:  # noqa: BLE001
        token = None
        errors.append(f"OAuth: {exc}"[:120])
    if token:
        mode = "api"
        sess.headers["Authorization"] = f"bearer {token}"
    for sub in SUBREDDITS:
        for listing in (("new", "hot") if token else ("new",)):
            try:
                (_rl_reddit if token else _rl_reddit_rss).wait()
                if token:
                    r = sess.get(f"https://oauth.reddit.com/r/{sub}/{listing}", params={"limit": 100}, timeout=20)
                    r.raise_for_status()
                    for ch in r.json().get("data", {}).get("children", []):
                        d = ch.get("data", {})
                        text = f"{d.get('title', '')} {d.get('selftext', '')[:1500]}"
                        syms = resolve(text)
                        if syms:
                            out.append({"id": "rd" + str(d.get("id")), "platform": "reddit", "community": f"r/{sub}",
                                        "author": d.get("author", ""),
                                        "posted_at": iso(datetime.fromtimestamp(float(d.get("created_utc") or 0), tz=timezone.utc)),
                                        "url": "https://www.reddit.com" + d.get("permalink", ""), "text": text[:400],
                                        "engagement": float((d.get("score") or 0) + (d.get("num_comments") or 0)),
                                        "symbols": syms, "origin": "reddit_api"})
                else:
                    r = sess.get(f"https://www.reddit.com/r/{sub}/{listing}/.rss", params={"limit": 100}, timeout=20)
                    r.raise_for_status()
                    for e in feedparser.parse(r.content).entries:
                        text = f"{e.get('title', '')} {re.sub('<[^>]+>', ' ', e.get('summary', ''))[:1500]}"
                        syms = resolve(text)
                        if syms:
                            out.append({"id": "rd" + (e.get("id") or e.get("link", "")).rsplit("/", 1)[-1],
                                        "platform": "reddit", "community": f"r/{sub}",
                                        "author": (e.get("author") or "").replace("/u/", ""),
                                        "posted_at": iso(parse_dt(e.get("published") or e.get("updated"))[0]),
                                        "url": e.get("link", ""), "text": text[:400], "engagement": 0.0,
                                        "symbols": syms, "origin": "reddit_rss"})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"r/{sub}/{listing}: {exc}"[:120])
    return out, {"source": "Reddit", "mode": "API" if mode == "api" else "RSS (ohne Zugang)",
                 "posts": len(out), "errors": errors[:8], "status": "ok" if len(errors) < len(SUBREDDITS) else "error"}


# ------------------------------------------------------------- StockTwits --
def fetch_stocktwits(focus: list[str], universe: set[str], max_symbols: int = 120) -> tuple[list[dict], dict, list[dict]]:
    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    trending, out, errors = [], [], []
    try:
        _rl_st.wait()
        r = sess.get("https://api.stocktwits.com/api/2/trending/symbols.json", timeout=20)
        r.raise_for_status()
        for i, s in enumerate(r.json().get("symbols", [])):
            sym = (s.get("symbol") or "").upper().replace(".", "-")
            trending.append({"rank": i + 1, "symbol": sym, "title": s.get("title"), "in_universe": sym in universe,
                             "watchlist_count": s.get("watchlist_count")})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Trending: {exc}"[:120])
    todo = []
    for s in [t["symbol"] for t in trending if t["in_universe"]] + focus:
        if s in universe and not s.endswith(".DE") and s not in todo:
            todo.append(s)
    for sym in todo[:max_symbols]:
        try:
            _rl_st.wait()
            r = sess.get(f"https://api.stocktwits.com/api/2/streams/symbol/{sym.replace('-', '.')}.json", timeout=20)
            if r.status_code == 429:
                errors.append("Rate-Limit erreicht")
                break
            r.raise_for_status()
            for m in r.json().get("messages", []):
                user = (m.get("user") or {}).get("username", "")
                syms = sorted({(x.get("symbol") or "").upper().replace(".", "-") for x in m.get("symbols", [])} & universe) or [sym]
                lab = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
                out.append({"id": f"st{m.get('id')}", "platform": "stocktwits", "community": "StockTwits", "author": user,
                            "posted_at": iso(parse_dt(m.get("created_at"))[0]),
                            "url": f"https://stocktwits.com/{user}/message/{m.get('id')}", "text": (m.get("body") or "")[:400],
                            "engagement": float(((m.get("likes") or {}).get("total")) or 0), "symbols": syms,
                            "sentiment_label": lab, "origin": "stocktwits"})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sym}: {exc}"[:120])
    return out, {"source": "StockTwits", "mode": "öffentliche API", "posts": len(out), "symbols": len(todo[:max_symbols]),
                 "errors": errors[:8], "status": "ok" if out or trending else "error"}, trending


# ------------------------------------------------------------------ Laden --
def load_csv(resolve) -> list[dict]:
    """social_mentions.csv: platform,post_id,author,posted_at,url,text,engagement,symbols(optional ;-getrennt)"""
    p = config.IMPORT_DIR / "social_mentions.csv"
    posts = []
    if p.exists():
        with p.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if not r.get("text") or (r.get("platform") or "").startswith("#"):
                    continue
                syms = [s.strip().upper() for s in (r.get("symbols") or "").split(";") if s.strip()] or resolve(r["text"])
                posts.append({"id": stable_id(r.get("platform"), r.get("post_id"), r.get("url")),
                              "platform": r.get("platform", "unknown"), "community": r.get("platform", ""),
                              "author": r.get("author", ""), "posted_at": iso(parse_dt(r.get("posted_at"))[0]),
                              "url": r.get("url", ""), "text": r["text"][:400], "engagement": float(r.get("engagement") or 0),
                              "symbols": syms, "origin": "csv"})
    return posts


def collect(universe: set[str], securities: dict | None = None, focus: list[str] | None = None,
            fetch: bool = True, now=None) -> tuple[list[dict], dict]:
    """Sammelt Beiträge, führt sie mit dem 30-Tage-Speicher zusammen. Rückgabe: (Beiträge, Quellenstatus)."""
    now = now or utcnow()
    resolve = symbol_resolver(universe, securities)
    new = load_csv(resolve)
    sources, trending = [], []
    if fetch:
        r_posts, r_stat = fetch_reddit(resolve)
        s_posts, s_stat, trending = fetch_stocktwits(focus or [], universe)
        new += r_posts + s_posts
        sources = [r_stat, s_stat]
    store = {p["id"]: p for p in read_json(_store(), [])}
    for p in new:
        p["symbols"] = [s for s in p["symbols"] if s in universe]
        if p["symbols"] and p.get("posted_at"):
            store[p["id"]] = p
    cutoff = iso(now - timedelta(days=30))
    posts = sorted([p for p in store.values() if (p.get("posted_at") or "") >= cutoff],
                   key=lambda p: p["posted_at"], reverse=True)[:30000]
    if fetch or new:
        write_json_atomic(_store(), posts)
    return posts, {"sources": sources, "stocktwits_trending": trending}


def load_posts(universe: set[str]) -> list[dict]:
    """Alte Schnittstelle: nur CSV + Speicher, ohne Netzabruf."""
    return collect(universe, fetch=False)[0]


# --------------------------------------------------------------- Analyse --
def analyze(posts: list[dict], now=None) -> dict[str, dict]:
    """Je Titel: Erwähnungen, Veränderung, Interaktionen, Sentiment, Manipulationshinweise."""
    now = now or utcnow()
    by_sym: dict[str, list[dict]] = defaultdict(list)
    for p in posts:
        for s in p["symbols"]:
            by_sym[s].append(p)
    out = {}
    for sym, ps in by_sym.items():
        def window(h0, h1):
            return [p for p in ps if (dt := parse_dt(p["posted_at"])[0]) and timedelta(hours=h0) <= now - dt < timedelta(hours=h1)]
        d1, prev7 = window(0, 24), window(24, 24 * 8)
        w7, w30 = window(0, 24 * 7), window(0, 24 * 30)
        baseline = len(prev7) / 7 if prev7 else 0
        change = round((len(d1) / baseline - 1) * 100) if baseline else None
        flags = []
        sample = w7[:300]
        texts = [tokens(p["text"]) for p in sample]
        near_dup = sum(1 for i in range(len(texts)) for j in range(i + 1, len(texts)) if jaccard(texts[i], texts[j]) > 0.8)
        if len(sample) >= 5 and near_dup >= len(sample) * 0.5:
            flags.append("Koordinierte Wiederholungen (nahezu identische Beiträge)")
        authors = Counter(p["author"] for p in w7 if p["author"])
        if len(w7) >= 6 and authors and authors.most_common(1)[0][1] / len(w7) > 0.4:
            flags.append("Wenige Accounts erzeugen Großteil der Erwähnungen")
        pump_hits = sum(1 for p in w7 if any(k in p["text"].lower() for k in PUMP))
        if w7 and pump_hits / len(w7) > 0.3:
            flags.append("Pump-typische Sprache")
        if baseline and len(d1) > 5 * baseline and len(d1) >= 10:
            flags.append("Plötzlicher Erwähnungsanstieg (>5x Basis)")
        labeled = [p for p in w7 if p.get("sentiment_label") in ("Bullish", "Bearish")]
        bull = sum(1 for p in labeled if p["sentiment_label"] == "Bullish")
        out[sym] = {
            "mentions_24h": len(d1), "mentions_7d": len(w7), "mentions_30d": len(w30),
            "change_vs_baseline_pct": change, "engagement_7d": sum(p["engagement"] for p in w7),
            "sentiment_7d": round(sum(_post_sentiment(p) for p in w7) / len(w7), 2) if w7 else None,
            "sentiment_basis": "Nutzerkennzeichnung (StockTwits) + Lexikon" if labeled else "algorithmisch (Lexikon)",
            "bullish_7d": bull, "bearish_7d": len(labeled) - bull,
            "by_platform_7d": dict(Counter(p["platform"] for p in w7)),
            "communities_7d": dict(Counter(p.get("community") or p["platform"] for p in w7).most_common(5)),
            "platforms": sorted({p["platform"] for p in w30}),
            "manipulation_flags": flags,
            "manipulation_risk": "hoch" if len(flags) >= 2 else ("auffaellig" if flags else "unauffällig"),
            "top_posts": [{k: p.get(k) for k in ("platform", "community", "author", "posted_at", "url", "text", "engagement", "sentiment_label")}
                          for p in sorted(w7, key=lambda x: x["engagement"], reverse=True)[:5]],
        }
    return out
