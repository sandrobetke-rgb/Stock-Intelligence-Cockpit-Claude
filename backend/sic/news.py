"""Nachrichten und Unternehmensmeldungen aus kostenlosen Quellen (Lastenheft 5).

- Yahoo-Finance-RSS je Ticker (nur Titel, Link, Datum, Kurzbeschreibung)
- CSV-Import für weitere frei zugaengliche Meldungen und Analystenänderungen
Keine Bezahlschranken umgehen, keine Volltexte speichern.
"""
from __future__ import annotations

import csv
import logging

from . import config
from .signals import make_signal
from .util import RateLimiter, http_get, read_json, write_json_atomic

log = logging.getLogger("sic.news")
CURSOR = config.STATE_DIR / "news_cursor.json"
_rl = RateLimiter(2.0)


def classify(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ("upgrade", "downgrade", "price target", "kursziel", "initiates coverage", "rating")):
        return "analyst_change"
    if any(k in t for k in ("reports", "announces", "results", "quarter", "earnings", "guidance", "dividend", "acquire", "merger")):
        return "company_news"
    return "news"


def fetch_yahoo_rss(symbol: str) -> list[dict]:
    import feedparser

    r = http_get(config.YAHOO_RSS.format(ticker=symbol), limiter=_rl)
    feed = feedparser.parse(r.content)
    out = []
    for e in feed.entries:
        title = e.get("title", "")
        s = make_signal(symbols=[symbol], category="market", signal_type=classify(title), title=title,
                        url=e.get("link", ""), source=e.get("source", {}).get("title") if isinstance(e.get("source"), dict) else "Yahoo Finance RSS",
                        published=e.get("published"), summary=e.get("summary", ""),
                        extra={"feed": "yahoo_rss"})
        if s:
            out.append(s)
    return out


def fetch_news(symbols: list[str]) -> tuple[list[dict], dict]:
    """Rotierende Abfrage (Rate-Limits): pro Lauf max. N Ticker, Cursor im State."""
    cur = read_json(CURSOR, {"pos": 0})
    n = len(symbols)
    if n == 0:
        return [], {"queried": 0}
    take = min(config.NEWS_MAX_TICKERS_PER_RUN, n)
    start = cur["pos"] % n
    batch = (symbols[start:] + symbols[:start])[:take]
    out, errors = [], []
    for sym in batch:
        try:
            out.extend(fetch_yahoo_rss(sym))
        except Exception as exc:  # noqa: BLE001
            errors.append(sym)
            log.warning("RSS %s: %s", sym, exc)
    write_json_atomic(CURSOR, {"pos": (start + take) % n})
    return out, {"queried": len(batch), "errors": len(errors), "rotation": f"{take}/{n} Ticker je Lauf"}


def import_csv_news() -> list[dict]:
    """news_manual.csv: symbols(;getrennt),signal_type,title,url,source,published_at,summary"""
    p = config.IMPORT_DIR / "news_manual.csv"
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("title") or (r.get("symbols") or "").startswith("#"):
                continue
            s = make_signal(symbols=[x.strip().upper() for x in (r.get("symbols") or "").split(";") if x.strip()],
                            category="market", signal_type=r.get("signal_type") or classify(r["title"]),
                            title=r["title"], url=r.get("url", ""), source=r.get("source") or "CSV-Import",
                            published=r.get("published_at"), summary=r.get("summary", ""),
                            extra={"feed": "csv"})
            if s:
                out.append(s)
    return out
