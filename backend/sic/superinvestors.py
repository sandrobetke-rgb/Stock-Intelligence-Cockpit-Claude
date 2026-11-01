"""Superinvestoren-Depots aus SEC-13F-Meldungen (Lastenheft Kap. 8.2) – wie Dataroma/WhaleWisdom,
aber direkt aus der kostenlosen Originalquelle SEC EDGAR.

- Managerliste: data/imports/superinvestors.csv (CIK + erwarteter Name als Sicherheitsprüfung)
- je Manager die zwei jüngsten Quartalsmeldungen (13F-HR) -> Neukauf, Aufstockung, Reduktion, Verkauf
- CUSIP -> Ticker über OpenFIGI (kostenlos, ohne Schlüssel 25 Anfragen/Min.), dauerhaft gecacht;
  Ausweichlösung: Namensabgleich mit dem Universum
- bereits verarbeitete Meldungen werden je Aktenzeichen gecacht (13F ändert sich nur quartalsweise)

Wichtig: 13F zeigt Bestände zum Quartalsende, bis zu 45 Tage verzögert, nur US-gelistete Long-Positionen.
Optionen (Put/Call) werden getrennt und nicht als Aktienbestand gezählt. Keine Echtzeitkäufe.
"""
from __future__ import annotations

import csv
import logging
import os
import re
import time
from xml.etree import ElementTree as ET

from . import config
from .util import RateLimiter, http_get, iso, normalize_text, read_json, session, utcnow, write_json_atomic

log = logging.getLogger("sic.superinvestors")
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FILING_DIR = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"
OPENFIGI = "https://api.openfigi.com/v3/mapping"
_rl = RateLimiter(config.SEC_MAX_REQ_PER_SEC)


def _filing_cache():
    return config.STATE_DIR / "13f"


def _cusip_file():
    return config.STATE_DIR / "cusip_map.json"


def load_managers() -> list[dict]:
    p = config.IMPORT_DIR / "superinvestors.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if (r.get("cik") or "").strip().isdigit()]
    return [{"cik": int(r["cik"]), "manager": r["manager"].strip(), "fund": r["fund"].strip(),
             "expected": (r.get("expected_name") or "").strip().upper()} for r in rows]


# ---------------------------------------------------------------- Parsing --
def _strip_ns(xml: str) -> ET.Element:
    """Namensräume entfernen (Filer nutzen Präfixe wie ns1:, n1: oder Standard-Namensraum)."""
    root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def parse_info_table(xml: str) -> list[dict]:
    """13F Information Table -> Positionen je CUSIP (Aktien), Optionen getrennt."""
    root = _strip_ns(xml)
    agg: dict[tuple[str, str], dict] = {}
    for it in root.iter("infoTable"):
        g = lambda path: (it.findtext(path) or "").strip()  # noqa: E731
        cusip = g("cusip").upper()
        put_call = g("putCall").lower() or None
        typ = g("shrsOrPrnAmt/sshPrnamtType") or "SH"
        if not cusip or typ != "SH":
            continue
        key = (cusip, put_call or "")
        a = agg.setdefault(key, {"cusip": cusip, "issuer": g("nameOfIssuer"), "title": g("titleOfClass"),
                                 "put_call": put_call, "shares": 0.0, "value": 0.0})
        a["shares"] += float(g("shrsOrPrnAmt/sshPrnamt") or 0)
        a["value"] += float(g("value") or 0)
    return list(agg.values())


def _value_in_dollars(rows: list[dict], report_date: str) -> None:
    """Bis Ende 2022 meldeten Filer Werte in Tausend USD, seit 2023 in USD. Manche Filer melden
    weiterhin in Tausend: erkennbar an einem unplausibel niedrigen Wert je Aktie (Median < 0,50 USD)."""
    per_share = sorted(r["value"] / r["shares"] for r in rows if r["shares"] > 0 and not r["put_call"])
    median = per_share[len(per_share) // 2] if per_share else None
    if report_date < "2022-12-31" or (median is not None and median < 0.5):
        for r in rows:
            r["value"] *= 1000


# ---------------------------------------------------------------- Abruf ---
def _latest_13f(cik: int) -> tuple[str, list[dict]]:
    sub = http_get(SUBMISSIONS.format(cik=cik), limiter=_rl).json()
    rec = sub.get("filings", {}).get("recent", {})
    seen, out = set(), []
    for form, acc, rep, filed in zip(rec.get("form", []), rec.get("accessionNumber", []),
                                     rec.get("reportDate", []), rec.get("filingDate", [])):
        if form == "13F-HR" and rep and rep not in seen:
            seen.add(rep)
            out.append({"accession": acc, "report_date": rep, "filed_at": filed})
        if len(out) == 2:
            break
    return sub.get("name", ""), out


def _load_filing(cik: int, f: dict) -> list[dict]:
    cache = _filing_cache() / f"{cik}-{f['accession']}-v2.json"
    hit = read_json(cache)
    if hit is not None:
        return hit
    base = FILING_DIR.format(cik=cik, acc=f["accession"].replace("-", ""))
    items = http_get(base + "index.json", limiter=_rl).json()["directory"]["item"]
    xmls = [i["name"] for i in items if i["name"].lower().endswith(".xml") and i["name"].lower() != "primary_doc.xml"]
    rows: list[dict] = []
    for name in xmls:
        txt = http_get(base + name, limiter=_rl).text
        if "infoTable" in txt or "informationTable" in txt:
            rows = parse_info_table(txt)
            break
    _value_in_dollars(rows, f["report_date"])
    write_json_atomic(cache, rows)
    return rows


# ------------------------------------------------------------ CUSIP->Ticker --
def map_cusips(cusips: set[str], names: dict[str, str], universe: dict[str, dict]) -> dict[str, str | None]:
    cmap: dict[str, str | None] = read_json(_cusip_file(), {})
    todo = [c for c in sorted(cusips) if c not in cmap]
    key = os.environ.get("OPENFIGI_API_KEY")
    batch, pause = (100, 0.25) if key else (10, 2.6)   # ohne Schluessel: 25 Anfragen/Minute
    headers = {"Content-Type": "application/json", **({"X-OPENFIGI-APIKEY": key} if key else {})}
    deadline = time.monotonic() + 15 * 60               # Lauf nicht blockieren; Rest folgt naechstes Mal
    for i in range(0, len(todo), batch):
        if time.monotonic() > deadline:
            break
        chunk = todo[i:i + batch]
        try:
            r = session().post(OPENFIGI, json=[{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in chunk],
                               headers=headers, timeout=config.HTTP_TIMEOUT)
            if r.status_code == 429:
                time.sleep(30)
                continue
            r.raise_for_status()
            for c, res in zip(chunk, r.json()):
                data = res.get("data") or []
                eq = [d for d in data if (d.get("securityType2") or "").lower() in ("common stock", "depositary receipt", "")] or data
                t = eq[0].get("ticker") if eq else None
                cmap[c] = t.replace("/", "-").replace(" ", "-").upper() if t else None
        except Exception as exc:  # noqa: BLE001
            log.warning("OpenFIGI: %s", exc)
            break
        time.sleep(pause)
    # Ausweichloesung: Name des Emittenten mit Universum abgleichen
    by_name = {}
    for sym, sec in universe.items():
        n = normalize_text(re.sub(r"\b(inc|corp|corporation|co|ltd|plc|holdings?|group|class [abc]|the)\b", " ", (sec.get("name") or "").lower()))
        if n:
            by_name.setdefault(n, sym)
    for c in cusips:
        if not cmap.get(c):
            n = normalize_text(re.sub(r"\b(inc|corp|corporation|co|ltd|plc|holdings?|group|cl [abc]|com|new|the)\b", " ", names.get(c, "").lower()))
            if n in by_name:
                cmap[c] = by_name[n]
    write_json_atomic(_cusip_file(), cmap)
    return cmap


# ------------------------------------------------------------- Auswertung --
def compare(cur: list[dict], prev: list[dict] | None) -> list[dict]:
    """Veränderung je Position gegenüber Vorquartal (nur Aktien, keine Optionen)."""
    total = sum(r["value"] for r in cur if not r["put_call"]) or 1
    pmap = {r["cusip"]: r for r in (prev or []) if not r["put_call"]}
    out = []
    for r in cur:
        if r["put_call"]:
            continue
        p = pmap.pop(r["cusip"], None)
        if prev is None:
            action, chg = "unknown", None
        elif p is None:
            action, chg = "new", None
        else:
            chg = (r["shares"] / p["shares"] - 1) * 100 if p["shares"] else None
            action = "increased" if chg and chg > 1 else ("reduced" if chg and chg < -1 else "unchanged")
        out.append({**r, "weight_pct": round(r["value"] / total * 100, 2), "action": action,
                    "shares_change_pct": round(chg, 1) if chg is not None else None,
                    "prev_shares": p["shares"] if p else 0})
    for p in pmap.values():
        out.append({**p, "shares": 0, "value": 0, "weight_pct": 0, "action": "sold_out",
                    "shares_change_pct": -100.0, "prev_shares": p["shares"]})
    return sorted(out, key=lambda x: -x["value"])


def build(universe: dict[str, dict], fetch: bool = True) -> dict:
    """Erzeugt superinvestors.json. Ohne Netzwerk (fetch=False) wird nur der Cache gelesen."""
    managers, errors = [], []
    raw: list[tuple[dict, dict, list[dict], list[dict] | None]] = []
    for m in load_managers():
        state_file = config.STATE_DIR / "13f_index.json"
        idx = read_json(state_file, {})
        try:
            if fetch:
                name, filings = _latest_13f(m["cik"])
                if m["expected"] and m["expected"] not in name.upper():
                    raise ValueError(f"CIK {m['cik']} gehört zu '{name}', erwartet '{m['expected']}' – übersprungen")
                idx[str(m["cik"])] = {"name": name, "filings": filings}
                write_json_atomic(state_file, idx)
            entry = idx.get(str(m["cik"]))
            if not entry or not entry["filings"]:
                continue
            fl = entry["filings"]
            cur = _load_filing(m["cik"], fl[0]) if fetch else read_json(_filing_cache() / f"{m['cik']}-{fl[0]['accession']}-v2.json", [])
            prev = None
            if len(fl) > 1:
                prev = _load_filing(m["cik"], fl[1]) if fetch else read_json(_filing_cache() / f"{m['cik']}-{fl[1]['accession']}-v2.json")
            raw.append((m, {**fl[0], "sec_name": entry["name"]}, cur, prev))
        except Exception as exc:  # noqa: BLE001
            errors.append({"manager": m["manager"], "cik": m["cik"], "error": str(exc)[:200]})
            log.warning("13F %s: %s", m["manager"], exc)

    names = {r["cusip"]: r["issuer"] for _, _, cur, prev in raw for r in cur + (prev or [])}
    cmap = map_cusips(set(names), names, universe) if (fetch and names) else read_json(_cusip_file(), {})
    agg: dict[str, dict] = {}
    for m, f, cur, prev in raw:
        pos = compare(cur, prev)
        for p in pos:
            p["symbol"] = cmap.get(p["cusip"])
            p["in_universe"] = bool(p["symbol"] and p["symbol"] in universe)
        cur_val = sum(p["value"] for p in pos if p["action"] != "sold_out")
        acc = f["accession"]
        managers.append({
            "cik": m["cik"], "manager": m["manager"], "fund": m["fund"], "sec_name": f["sec_name"],
            "report_date": f["report_date"], "filed_at": f["filed_at"],
            "filing_url": FILING_DIR.format(cik=m["cik"], acc=acc.replace("-", "")) + f"{acc}-index.htm",
            "portfolio_value": round(cur_val, 0), "holdings": sum(1 for p in pos if p["action"] != "sold_out"),
            "new": sum(1 for p in pos if p["action"] == "new"), "sold_out": sum(1 for p in pos if p["action"] == "sold_out"),
            "positions": pos,
        })
        for p in pos:
            k = p["symbol"] or p["cusip"]
            a = agg.setdefault(k, {"symbol": p["symbol"], "cusip": p["cusip"], "issuer": p["issuer"], "in_universe": p["in_universe"],
                                   "holders": 0, "buyers": 0, "new_buyers": 0, "sellers": 0, "sold_out": 0, "value": 0.0,
                                   "managers": []})
            held = p["action"] != "sold_out"
            a["holders"] += held
            a["buyers"] += p["action"] in ("new", "increased")
            a["new_buyers"] += p["action"] == "new"
            a["sellers"] += p["action"] in ("reduced", "sold_out")
            a["sold_out"] += p["action"] == "sold_out"
            a["value"] += p["value"]
            a["managers"].append({"manager": m["manager"], "fund": m["fund"], "action": p["action"],
                                  "weight_pct": p["weight_pct"], "shares_change_pct": p["shares_change_pct"],
                                  "value": p["value"], "report_date": f["report_date"]})
    stocks = sorted(agg.values(), key=lambda a: (-a["holders"], -a["value"]))
    return {
        "generated_at": iso(utcnow()), "managers": managers, "stocks": stocks, "errors": errors,
        "note": "13F-Meldungen zeigen US-Long-Bestände zum Quartalsende, bis zu 45 Tage verzögert. "
                "Keine Echtzeitkäufe, keine Leerverkäufe, keine Nicht-US-Titel. Quelle: SEC EDGAR.",
    }
