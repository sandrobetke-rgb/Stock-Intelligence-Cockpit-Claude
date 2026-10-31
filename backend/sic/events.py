"""Market & Economic Ticker (Lastenheft Kap. 7) -> market-events.json

- Aktuelle Nachrichten aus kostenlosen offiziellen RSS-Feeds (Fed, EZB, BLS, Destatis)
  mit Relevanzfilter
- Kommende Ereignisse aus market_calendar.csv (offizielle Terminquellen), klar als
  'planned' gekennzeichnet, mit Zeitzone
- Statuswechsel nach Eintritt; Terminänderungen werden in einer Historie gespeichert
"""
from __future__ import annotations

import csv
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config
from .util import iso, parse_dt, read_json, stable_id, utcnow, write_json_atomic

log = logging.getLogger("sic.events")
STATE = config.STATE_DIR / "events.json"
NEWS_KEEP_DAYS = 14
STATUSES = {"planned", "published", "occurred", "postponed", "cancelled"}


def relevance_categories(text: str) -> list[str]:
    t = f" {text.lower()} "
    return [cat for cat, kws in config.MARKET_KEYWORDS.items() if any(k in t for k in kws)]


def _discover_feed(page_url: str) -> str | None:
    """RSS-Autodiscovery: <link rel="alternate" type="application/rss+xml" href=...> auf einer Seite."""
    from urllib.parse import urljoin
    from .util import http_get

    html = http_get(page_url).text
    for tag in re.findall(r"<link[^>]+>", html, flags=re.I):
        if re.search(r"application/(rss|atom)\+xml", tag, re.I):
            m = re.search(r'href=["\']([^"\']+)', tag, re.I)
            if m:
                return urljoin(page_url, m.group(1).replace("&amp;", "&"))
    return None


def _load_feed(src: dict):
    import feedparser
    from .util import http_get

    try:
        feed = feedparser.parse(http_get(src["url"]).content)
        if feed.entries:
            return feed
        err: Exception = ValueError("Feed ohne Eintraege")
    except Exception as exc:  # noqa: BLE001
        err = exc
    if src.get("page"):
        found = _discover_feed(src["page"])
        if found:
            log.info("Feed %s gefunden ueber Autodiscovery: %s", src["id"], found)
            return feedparser.parse(http_get(found).content)
    raise err


def fetch_market_news(now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    import feedparser
    from .util import http_get

    now = now or utcnow()
    items, status = [], []
    for src in config.MARKET_NEWS_FEEDS:
        try:
            feed = _load_feed(src)
            status.append({"id": src["id"], "name": src["name"], "status": "ok", "entries": len(feed.entries)})
        except Exception as exc:  # noqa: BLE001
            status.append({"id": src["id"], "name": src["name"], "status": "error", "message": str(exc)[:200]})
            continue
        for e in feed.entries:
            title = (e.get("title") or "").strip()
            summary = re.sub("<[^>]+>", " ", e.get("summary", ""))[:280]
            cats = relevance_categories(f"{title} {summary}")
            if not cats:
                continue  # Nur Eintraege mit plausibler Markt-/Wirtschaftsrelevanz
            pub, date_only = parse_dt(e.get("published") or e.get("updated"))
            if pub and now - pub > timedelta(days=NEWS_KEEP_DAYS):
                continue
            items.append(news_item(title=title, url=e.get("link", ""), source=src["name"], published=pub,
                                   date_only=date_only, markets=src["markets"], categories=[src["category"], *cats],
                                   summary=summary, now=now))
    return items, status


def news_item(*, title, url, source, published, date_only, markets, categories, summary="", sectors=None,
              tickers=None, verification="Verified", direction_override=None, now=None) -> dict:
    now = now or utcnow()
    return {
        "id": stable_id(url, title), "kind": "news", "title": title[:200], "summary": summary,
        "time": iso(published), "date_only": date_only, "timezone": "UTC",
        "source": source, "url": url,
        "relevance": "Gesamtwirtschaft" if not tickers and not sectors else ("Unternehmen" if tickers else "Branche"),
        "relevance_level": "high" if any(c in ("Zentralbank", "Inflation", "Arbeitsmarkt") for c in categories) else "medium",
        "categories": sorted(set(categories)), "markets": markets, "sectors": sectors or [], "tickers": tickers or [],
        # Wirkungsrichtung von Wirtschaftsdaten ist ohne Erwartungswert nicht belastbar ableitbar
        # -> 'unclear', solange keine geprüfte manuelle Einordnung vorliegt (keine Kursprognose)
        "direction": direction_override or "unclear",
        "verification": verification, "status": "published",
        "captured_at": iso(now), "last_checked_at": iso(now), "changes": [],
    }


def load_calendar(now: datetime | None = None) -> list[dict]:
    """market_calendar.csv: event_time,timezone,title,category,markets,sectors,tickers,relevance_level,
    status,source_name,source_url,note   (event_time lokal in 'timezone', z. B. America/New_York)"""
    now = now or utcnow()
    p = config.IMPORT_DIR / "market_calendar.csv"
    out = []
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("title") or (r.get("event_time") or "").startswith("#") or not r.get("source_url"):
                continue
            tzname = (r.get("timezone") or "UTC").strip()
            raw = r["event_time"].strip()
            date_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw))
            try:
                local = datetime.fromisoformat(raw)
                if local.tzinfo is None:
                    local = local.replace(tzinfo=ZoneInfo(tzname))
            except (ValueError, KeyError) as exc:
                log.warning("Kalendereintrag ungültig: %s (%s)", r["title"], exc)
                continue
            status = (r.get("status") or "planned").strip().lower()
            status = status if status in STATUSES else "planned"
            if status == "planned" and local < now - timedelta(hours=2):
                status = "occurred"  # Termin verstrichen; Ergebnis über News-Feed/Quelle prüfen
            out.append({
                "id": stable_id(r["title"], r.get("source_url"), r.get("category")),
                "kind": "event", "title": r["title"], "summary": r.get("note", ""),
                "time": iso(local), "local_time": local.isoformat(), "timezone": tzname, "date_only": date_only,
                "source": r.get("source_name") or "", "url": r["source_url"],
                "relevance": "Gesamtwirtschaft" if not (r.get("tickers") or r.get("sectors")) else "Branche",
                "relevance_level": (r.get("relevance_level") or "medium").strip(),
                "categories": [r.get("category") or "Termin"],
                "markets": [m.strip() for m in (r.get("markets") or "global").split(";") if m.strip()],
                "sectors": [s.strip() for s in (r.get("sectors") or "").split(";") if s.strip()],
                "tickers": [s.strip().upper() for s in (r.get("tickers") or "").split(";") if s.strip()],
                "direction": "unclear", "verification": "Verified" if r.get("source_url") else "Unverified",
                "status": status, "captured_at": iso(now), "last_checked_at": iso(now), "changes": [],
            })
    return out


def merge_with_history(items: list[dict], now: datetime | None = None) -> list[dict]:
    """Hält Terminänderungen nachvollziehbar fest (alter Termin -> neuer Termin)."""
    now = now or utcnow()
    prev = {e["id"]: e for e in read_json(STATE, [])}
    merged = []
    for it in items:
        old = prev.pop(it["id"], None)
        if old:
            it["captured_at"] = old.get("captured_at", it["captured_at"])
            it["changes"] = old.get("changes", [])
            if it["kind"] == "event" and old.get("time") != it["time"]:
                it["changes"].append({"changed_at": iso(now), "field": "time", "from": old.get("time"), "to": it["time"]})
                if it["status"] == "planned":
                    it["status"] = "postponed" if (old.get("time") or "") < it["time"] else "planned"
            if old.get("status") != it["status"]:
                it["changes"].append({"changed_at": iso(now), "field": "status", "from": old.get("status"), "to": it["status"]})
        merged.append(it)
    # verschwundene, noch aktuelle Nachrichten nicht verlieren
    for old in prev.values():
        t = parse_dt(old.get("time"))[0]
        if old["kind"] == "news" and t and now - t <= timedelta(days=NEWS_KEEP_DAYS):
            merged.append(old)
    write_json_atomic(STATE, merged)
    return merged


def build_market_events(fetch: bool = True, now: datetime | None = None) -> dict:
    now = now or utcnow()
    news, feed_status = fetch_market_news(now) if fetch else ([], [])
    cal = load_calendar(now)
    items = merge_with_history(news + cal, now)
    upcoming = sorted([i for i in items if i["kind"] == "event" and i["status"] in ("planned", "postponed")], key=lambda x: x["time"])
    recent = sorted([i for i in items if i not in upcoming], key=lambda x: x["time"] or "", reverse=True)
    return {"generated_at": iso(now), "timezone_note": "Zeiten in UTC (ISO 8601); Termine zusätzlich in lokaler Zeitzone",
            "current": recent[:150], "upcoming": upcoming[:150], "feeds": feed_status}
