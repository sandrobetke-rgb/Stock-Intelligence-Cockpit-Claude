"""Social Media Intelligence (Lastenheft Kap. 9).

Quelle: CSV-Import (social_mentions.csv) aus rechtlich zugaenglichen Exporten.
Optional Reddit-RSS (SIC_ENABLE_REDDIT_RSS=1) – nur nach Prüfung der Reddit-Bedingungen.
Sentiment ist eine algorithmische Einschätzung. Social Media erhoeht nie Company Quality.
"""
from __future__ import annotations

import csv
import logging
import os
import re
from collections import Counter, defaultdict
from datetime import timedelta

from . import config
from .util import iso, jaccard, parse_dt, stable_id, tokens, utcnow

log = logging.getLogger("sic.social")
REDDIT_FEEDS = ["https://www.reddit.com/r/stocks/new/.rss", "https://www.reddit.com/r/wallstreetbets/new/.rss",
                "https://www.reddit.com/r/investing/new/.rss"]
PUMP = ["to the moon", "moon", "100x", "10x", "squeeze", "short squeeze", "next gme", "don't miss", "load up",
        "rocket", "\U0001F680", "guaranteed", "easy money", "last chance", "lambo"]
POS = ["bullish", "buy", "beat", "strong", "upgrade", "growth", "undervalued", "calls", "long", "breakout"]
NEG = ["bearish", "sell", "miss", "weak", "downgrade", "fraud", "overvalued", "puts", "short", "dump", "bankrupt"]


def extract_symbols(text: str, universe: set[str]) -> list[str]:
    """Nur Cashtags ($AAPL) – reine Großbuchstabenwörter sind zu mehrdeutig."""
    return sorted({m.upper() for m in re.findall(r"\$([A-Za-z]{1,5})\b", text or "") if m.upper() in universe})


def sentiment(text: str) -> float:
    t = (text or "").lower()
    p = sum(t.count(w) for w in POS)
    n = sum(t.count(w) for w in NEG)
    return 0.0 if p + n == 0 else round((p - n) / (p + n), 2)


def load_posts(universe: set[str]) -> list[dict]:
    """social_mentions.csv: platform,post_id,author,posted_at,url,text,engagement,symbols(optional ;-getrennt)"""
    posts = []
    p = config.IMPORT_DIR / "social_mentions.csv"
    if p.exists():
        with p.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if not r.get("text") or (r.get("platform") or "").startswith("#"):
                    continue
                syms = [s.strip().upper() for s in (r.get("symbols") or "").split(";") if s.strip()] or extract_symbols(r["text"], universe)
                posts.append({"id": stable_id(r.get("platform"), r.get("post_id"), r.get("url")),
                              "platform": r.get("platform", "unknown"), "author": r.get("author", ""),
                              "posted_at": iso(parse_dt(r.get("posted_at"))[0]), "url": r.get("url", ""),
                              "text": r["text"][:500], "engagement": float(r.get("engagement") or 0),
                              "symbols": [s for s in syms if s in universe], "origin": "csv"})
    if os.environ.get("SIC_ENABLE_REDDIT_RSS") == "1":
        posts.extend(_reddit_rss(universe))
    return posts


def _reddit_rss(universe: set[str]) -> list[dict]:
    import feedparser
    from .util import http_get

    out = []
    for url in REDDIT_FEEDS:
        try:
            feed = feedparser.parse(http_get(url).content)
        except Exception as exc:  # noqa: BLE001
            log.warning("Reddit-RSS %s: %s", url, exc)
            continue
        for e in feed.entries:
            text = f"{e.get('title', '')} {re.sub('<[^>]+>', ' ', e.get('summary', ''))}"
            syms = extract_symbols(text, universe)
            if syms:
                out.append({"id": stable_id(e.get("link")), "platform": "reddit", "author": e.get("author", ""),
                            "posted_at": iso(parse_dt(e.get("published") or e.get("updated"))[0]),
                            "url": e.get("link", ""), "text": text[:500], "engagement": 0.0,
                            "symbols": syms, "origin": "reddit_rss"})
    return out


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
        texts = [tokens(p["text"]) for p in w7]
        near_dup = sum(1 for i in range(len(texts)) for j in range(i + 1, len(texts)) if jaccard(texts[i], texts[j]) > 0.8)
        if len(w7) >= 5 and near_dup >= len(w7) * 0.5:
            flags.append("Koordinierte Wiederholungen (nahezu identische Beiträge)")
        authors = Counter(p["author"] for p in w7 if p["author"])
        if len(w7) >= 6 and authors and authors.most_common(1)[0][1] / len(w7) > 0.4:
            flags.append("Wenige Accounts erzeugen Großteil der Erwähnungen")
        pump_hits = sum(1 for p in w7 if any(k in p["text"].lower() for k in PUMP))
        if w7 and pump_hits / len(w7) > 0.3:
            flags.append("Pump-typische Sprache")
        if baseline and len(d1) > 5 * baseline and len(d1) >= 10:
            flags.append("Plötzlicher Erwähnungsanstieg (>5x Basis)")
        out[sym] = {
            "mentions_24h": len(d1), "mentions_7d": len(w7), "mentions_30d": len(w30),
            "change_vs_baseline_pct": change, "engagement_7d": sum(p["engagement"] for p in w7),
            "sentiment_7d": round(sum(sentiment(p["text"]) for p in w7) / len(w7), 2) if w7 else None,
            "sentiment_basis": "algorithmisch (Lexikon)", "platforms": sorted({p["platform"] for p in w30}),
            "manipulation_flags": flags,
            "manipulation_risk": "hoch" if len(flags) >= 2 else ("auffaellig" if flags else "unauffällig"),
            "top_posts": [{k: p[k] for k in ("platform", "author", "posted_at", "url", "text", "engagement")}
                          for p in sorted(w7, key=lambda x: x["engagement"], reverse=True)[:5]],
        }
    return out
