"""Gemeinsames Signalmodell, Signalspeicher, Deduplizierung und Verifizierung
(Lastenheft Kap. 5 und 10).

Jedes Signal: id, symbol(s), category, signal_type, title, source, url, published_at,
captured_at, fingerprint, cluster_id, independence, verification.
"""
from __future__ import annotations

import csv
import logging
from datetime import timedelta

from . import config
from .util import (domain_of, fingerprint, iso, jaccard, parse_dt, read_json, stable_id,
                   tokens, utcnow, write_json_atomic)

log = logging.getLogger("sic.signals")
STORE = config.STATE_DIR / "signals.json"
RETENTION_DAYS = 400  # historische Signale für Rückblicke

VERIFICATION = ["Verified", "Partially Verified", "Unverified", "Disputed", "False", "Outdated"]

# Primärquellen: Behoerden, Regulatoren, offizielle Verteiler von Unternehmensmeldungen
PRIMARY_DOMAINS = {
    "sec.gov", "whitehouse.gov", "federalreserve.gov", "ecb.europa.eu", "bls.gov", "bea.gov",
    "destatis.de", "bundesbank.de", "bafin.de", "treasury.gov", "commerce.gov", "ustr.gov",
    "truthsocial.com", "businesswire.com", "prnewswire.com", "globenewswire.com",
    "eqs-news.com", "dgap.de", "investor.gov",
}
AGENCY_HINTS = ("reuters", "associated press", "(ap)", "dpa", "afp", "bloomberg")


def is_primary(url: str) -> bool:
    d = domain_of(url)
    return any(d == p or d.endswith("." + p) for p in PRIMARY_DOMAINS) or d.startswith(("ir.", "investor.", "investors."))


def make_signal(*, symbols: list[str], category: str, signal_type: str, title: str, url: str,
                source: str, published: object, summary: str = "", extra: dict | None = None) -> dict | None:
    pub, date_only = parse_dt(published)
    if not title or not url:
        return None
    sig = {
        "id": stable_id(url, title),
        "symbols": sorted(set(symbols)),
        "category": category,
        "signal_type": signal_type,
        "title": title.strip()[:300],
        # Keine vollstaendige Übernahme geschuetzter Artikel: nur Kurzbeschreibung
        "summary": (summary or "").strip()[:280],
        "source": source,
        "source_domain": domain_of(url),
        "url": url,
        "published_at": iso(pub),
        "date_only": date_only,
        "captured_at": iso(utcnow()),
        "fingerprint": fingerprint(title),
        "primary_source": is_primary(url),
        "cluster_id": None,
        "independence": None,
        "verification": None,
    }
    if extra:
        sig.update(extra)
    return sig


def load_store() -> dict[str, dict]:
    return {s["id"]: s for s in read_json(STORE, [])}


def merge_into_store(store: dict[str, dict], new: list[dict]) -> int:
    added = 0
    for s in new:
        if s and s["id"] not in store:
            store[s["id"]] = s
            added += 1
        elif s:
            store[s["id"]]["symbols"] = sorted(set(store[s["id"]]["symbols"]) | set(s["symbols"]))
    cutoff = utcnow() - timedelta(days=RETENTION_DAYS)
    for k in [k for k, v in store.items() if (parse_dt(v.get("published_at") or v["captured_at"])[0] or utcnow()) < cutoff]:
        del store[k]
    return added


def save_store(store: dict[str, dict]) -> None:
    write_json_atomic(STORE, sorted(store.values(), key=lambda s: s.get("published_at") or "", reverse=True))


# ---------------------------------------------------------- Deduplizierung --
def cluster_signals(signals: list[dict]) -> None:
    """Originalmeldung vs. Kopie vs. Syndizierung (Lastenheft 5).

    - gleicher Fingerprint oder Jaccard >= Schwelle -> gleicher Cluster
    - fruehestes Signal im Cluster = 'original'
    - gleicher Text, anderes Portal -> 'syndicated' (Agenturtext), gleiches Portal -> 'copy'
    - verschiedene Cluster zum selben Titel = 'independent' Berichterstattung
    """
    ordered = sorted(signals, key=lambda s: s.get("published_at") or s["captured_at"])
    clusters: list[tuple[str, set[str], set[str], dict]] = []  # id, tokens, fps, original
    for s in ordered:
        tk = tokens(s["title"])
        hit = None
        for cid, ctk, fps, orig in clusters:
            if s["fingerprint"] in fps or jaccard(tk, ctk) >= config.SIMILARITY_DUPLICATE:
                if set(s["symbols"]) & set(orig["symbols"]) or not s["symbols"]:
                    hit = (cid, ctk, fps, orig)
                    break
        if hit is None:
            cid = s["id"]
            clusters.append((cid, tk, {s["fingerprint"]}, s))
            s["cluster_id"], s["independence"] = cid, "original"
        else:
            cid, ctk, fps, orig = hit
            fps.add(s["fingerprint"])
            ctk |= tk
            s["cluster_id"] = cid
            s["independence"] = "copy" if s["source_domain"] == orig["source_domain"] else "syndicated"


def verify(signals: list[dict], overrides: dict[str, dict] | None = None) -> None:
    """Verifizierungsstatus je Cluster (Lastenheft 10)."""
    overrides = overrides or {}
    by_cluster: dict[str, list[dict]] = {}
    for s in signals:
        by_cluster.setdefault(s["cluster_id"] or s["id"], []).append(s)
    now = utcnow()
    for cid, members in by_cluster.items():
        primary = any(m["primary_source"] for m in members)
        domains = {m["source_domain"] for m in members}
        newest = max((parse_dt(m.get("published_at"))[0] or now) for m in members)
        if primary:
            status = "Verified"
        elif len(domains) >= 2 and not all(any(h in (m["summary"] + m["title"]).lower() for h in AGENCY_HINTS) for m in members):
            status = "Partially Verified"
        else:
            status = "Unverified"
        if (now - newest).days > 30 and status != "Verified":
            status = "Outdated"
        for m in members:
            o = overrides.get(m["id"]) or overrides.get(m["url"])
            m["verification"] = o["status"] if o else status
            if o:
                m["fact_check"] = o


def load_factcheck_overrides() -> dict[str, dict]:
    """fact_checks.csv: signal_id_or_url,status,note,source,checked_at (z. B. Disputed/False)."""
    p = config.IMPORT_DIR / "fact_checks.csv"
    out: dict[str, dict] = {}
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            key = (r.get("signal_id_or_url") or "").strip()
            if not key or key.startswith("#") or r.get("status") not in VERIFICATION:
                continue
            out[key] = {"status": r["status"], "note": r.get("note", ""), "source": r.get("source", ""),
                        "checked_at": r.get("checked_at")}
    return out


def in_window(sig: dict, hours: int, now=None) -> bool:
    now = now or utcnow()
    dt = parse_dt(sig.get("published_at"))[0]
    return dt is not None and timedelta(0) <= now - dt <= timedelta(hours=hours)
