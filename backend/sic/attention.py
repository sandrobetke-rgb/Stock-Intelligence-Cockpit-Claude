"""Öffentliche Aufmerksamkeit über Wikipedia-Seitenaufrufe (Wikimedia-Pageviews-API, kostenlos, ohne Konto).

Je Aktie wird der englische Wikipedia-Artikel zum Unternehmen ermittelt (MediaWiki-API, Weiterleitungen
aufgelöst, Begriffsklärungen und Artikel ohne Unternehmensbezug verworfen; Ergebnis 30 Tage gecacht).
Täglich werden die Aufrufe (nur Menschen, alle Zugriffsarten) der letzten 60 Tage geladen.
Kennzahlen: Aufrufe am letzten Tag, Schnitt 7 Tage, Basis = Schnitt der 30 Tage davor, Verhältnis.
Eine Spitze (≥ 3-fach über Basis und ≥ 2.000 Aufrufe) zeigt breites Interesse – Ursache kann positiv oder
negativ sein. Aufmerksamkeit erhöht nie den Company Quality Score.
"""
from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import quote

import requests

from . import config
from .util import iso, read_json, utcnow, write_json_atomic

log = logging.getLogger("sic.attention")
API = "https://en.wikipedia.org/w/api.php"
PV = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{t}/daily/{a}/{b}"
# Kurzbeschreibung des Artikels muss nach Unternehmen klingen (Wortanfänge, z. B. "manufactur" -> manufacturer/-ing)
COMPANY_STEMS = ("compan", "corporat", "manufactur", "bank", "retail", "conglomerat", "holding", "firm", "trust", "reit",
                 "provider", "operator", "airline", "insur", "developer", "maker", "producer", "chain", "brand",
                 "business", "utilit", "biotech", "pharmac", "semiconductor", "software", "restaurant", "railroad",
                 "supplier", "distribut", "enterprise", "investment", "financ", "lender", "publisher", "carrier",
                 "miner", "mining", "energy", "hotel", "studio", "multinational", "subsidiar", "partnership",
                 "aktiengesellschaft", "plc", "inc", "conglomerate", "biopharm", "therapeutics", "bancorp", "group",
                 "chemical", "automaker", "telecom", "e-commerce", "logistics", "homebuilder", "shipping", "fintech")
SPIKE_RATIO, SPIKE_MIN = 3.0, 2000


def _ua() -> str:
    return os.environ.get("SIC_USER_AGENT") or "stock-intelligence-cockpit/1.2 (private, non-commercial)"


def _titles_path():
    return config.STATE_DIR / "wiki_titles.json"


def _views_path():
    return config.STATE_DIR / "wiki_views.json"


def _variants(name: str) -> list[str]:
    n = re.sub(r"\s*\(.*?\)", "", name or "")
    n = re.sub(r"\s+(Class|Series)\s+[A-Z]\b.*$", "", n, flags=re.I).strip()
    out = [n]
    base = re.sub(r",?\s+(Inc\.?|Corp\.?|Corporation|Co\.?|Ltd\.?|plc|PLC|N\.V\.|S\.A\.|SE|AG|Holdings?|Group|Company)$", "", n).strip()
    if base and base != n:
        out += [base, f"{base} Inc.", f"{base} (company)"]
    if n.isupper() and len(n) > 4:
        out.append(n.title())
    return list(dict.fromkeys(x for x in out if x))


def _company_like(desc: str) -> bool:
    toks = re.findall(r"[a-z][a-z-]*", (desc or "").lower())
    return any(t.startswith(w) for t in toks for w in COMPANY_STEMS)


def resolve_titles(securities: dict[str, dict], now=None) -> dict[str, str | None]:
    """Symbol -> Wikipedia-Artikel (oder None). Ungeprüfte/abgelaufene Einträge werden neu ermittelt."""
    now = now or utcnow()
    cache = read_json(_titles_path(), {})
    cutoff = iso(now - timedelta(days=30))
    todo = {s: v for s, v in securities.items() if v.get("status") == "active"
            and (s not in cache or (cache[s].get("checked") or "") < cutoff)}
    if todo:
        sess = requests.Session()
        sess.headers["User-Agent"] = _ua()
        cand = {s: _variants(v.get("name") or "") for s, v in todo.items()}
        found: dict[str, str | None] = {s: None for s in todo}
        for round_ in range(5):
            ask = {s: c[round_] for s, c in cand.items() if found[s] is None and len(c) > round_}
            names = list(dict.fromkeys(ask.values()))
            res: dict[str, str | None] = {}
            for i in range(0, len(names), 50):
                try:
                    r = sess.get(API, params={"action": "query", "format": "json", "redirects": 1, "prop": "pageprops",
                                              "ppprop": "disambiguation|wikibase-shortdesc", "titles": "|".join(names[i:i + 50])},
                                 timeout=30)
                    r.raise_for_status()
                    q = r.json().get("query", {})
                    alias = {x["from"]: x["to"] for x in q.get("normalized", []) + q.get("redirects", [])}
                    pages = {p["title"]: p for p in q.get("pages", {}).values()}
                    for nm in names[i:i + 50]:
                        t = alias.get(alias.get(nm, nm), alias.get(nm, nm))
                        p = pages.get(t)
                        if not p or "missing" in p or "disambiguation" in (p.get("pageprops") or {}):
                            continue
                        if _company_like((p.get("pageprops") or {}).get("wikibase-shortdesc", "")):
                            res[nm] = p["title"]
                except Exception as exc:  # noqa: BLE001
                    log.warning("Wikipedia-Titel: %s", exc)
            for s, nm in ask.items():
                if res.get(nm):
                    found[s] = res[nm]
        for s, t in found.items():
            cache[s] = {"title": t, "checked": iso(now)}
        write_json_atomic(_titles_path(), cache)
    return {s: (cache.get(s) or {}).get("title") for s in securities}


def fetch_views(titles: dict[str, str | None], now=None) -> dict:
    now = now or utcnow()
    end = (now - timedelta(days=1)).date()
    start = end - timedelta(days=60)
    a, b = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    sess = requests.Session()
    sess.headers["User-Agent"] = _ua()
    errors: list[str] = []

    def one(item):
        sym, t = item
        try:
            r = sess.get(PV.format(t=quote(t.replace(" ", "_"), safe=""), a=a, b=b), timeout=20)
            if r.status_code == 404:
                return sym, {}
            r.raise_for_status()
            return sym, {x["timestamp"][:8]: x["views"] for x in r.json().get("items", [])}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sym}: {exc}"[:100])
            return sym, None

    store = read_json(_views_path(), {})
    with ThreadPoolExecutor(max_workers=8) as ex:
        for sym, daily in ex.map(one, [(s, t) for s, t in titles.items() if t]):
            if daily is not None:
                store[sym] = {"title": titles[sym], "daily": daily, "fetched_at": iso(now)}
    for s in list(store):
        if not titles.get(s):
            store.pop(s)
    write_json_atomic(_views_path(), store)
    return {"source": "Wikipedia-Seitenaufrufe", "mode": "Wikimedia-API (ohne Konto)", "posts": len(store),
            "errors": errors[:8], "status": "ok" if store and len(errors) < max(10, len(titles) // 10) else "error"}


def metrics(store: dict | None = None) -> dict[str, dict]:
    store = store if store is not None else read_json(_views_path(), {})
    out = {}
    for sym, v in store.items():
        days = sorted(v.get("daily", {}).items())
        if len(days) < 20:
            continue
        vals = [n for _, n in days]
        last, last7, base = vals[-1], vals[-7:], vals[-37:-7]
        avg7 = sum(last7) / len(last7)
        avg30 = sum(base) / len(base) if base else None
        r1 = round(last / avg30, 2) if avg30 else None
        out[sym] = {
            "title": v["title"], "url": "https://en.wikipedia.org/wiki/" + quote(v["title"].replace(" ", "_")),
            "date": f"{days[-1][0][:4]}-{days[-1][0][4:6]}-{days[-1][0][6:]}", "views_1d": last,
            "avg_7d": round(avg7), "avg_30d": round(avg30) if avg30 else None, "ratio_1d": r1,
            "ratio_7d": round(avg7 / avg30, 2) if avg30 else None,
            "spike": bool(r1 and r1 >= SPIKE_RATIO and last >= SPIKE_MIN),
            "series": vals[-30:],
        }
    return out


def build(securities: dict[str, dict], fetch: bool = True, now=None) -> tuple[dict[str, dict], dict | None]:
    stat = None
    if fetch:
        titles = resolve_titles(securities, now)
        stat = fetch_views(titles, now)
    return metrics(), stat
