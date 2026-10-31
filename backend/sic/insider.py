"""Insider- und institutionelle Aktivitaeten (Lastenheft Kap. 8).

- Unternehmensinsider (USA): SEC EDGAR Form 4 (kostenlos; User-Agent mit Kontakt Pflicht,
  max. 10 Anfragen/s). Unterscheidung Open-Market-Kauf/-Verkauf vs. Optionsausübung,
  Vergütung, Steuereinbehalt.
- DAX-Insider (Directors' Dealings, Art. 19 MAR): CSV-Import aus BaFin-Datenbank
- Institutionelle Beteiligungen (13F): CSV-Import; Stichtag und Veröffentlichungsverzug
  werden ausgewiesen – nie als Echtzeitkaeufe dargestellt.
Politische Aktiengeschaefte liegen getrennt in politics.py.
"""
from __future__ import annotations

import csv
import logging
import re
from datetime import timedelta
from xml.etree import ElementTree as ET

from . import config
from .util import RateLimiter, http_get, iso, parse_dt, read_json, stable_id, utcnow, write_json_atomic

log = logging.getLogger("sic.insider")
CIK_CACHE = config.CACHE_DIR / "sec_cik.json"
STORE = config.STATE_DIR / "insider.json"
CURSOR = config.STATE_DIR / "insider_cursor.json"
_rl = RateLimiter(config.SEC_MAX_REQ_PER_SEC)

# SEC-Transaktionscodes (Form 4)
CODES = {
    "P": ("buy", "Kauf am offenen Markt", True),
    "S": ("sell", "Verkauf am offenen Markt", True),
    "M": ("option_exercise", "Optionsausübung", False),
    "C": ("conversion", "Wandlung derivativer Wertpapiere", False),
    "A": ("award", "Zuteilung (Vergütung)", False),
    "F": ("tax_withholding", "Steuereinbehalt bei Vergütung", False),
    "G": ("gift", "Schenkung", False),
    "D": ("disposition_issuer", "Rückgabe an Emittenten", False),
    "J": ("other", "Sonstige Transaktion", False),
}


def cik_map() -> dict[str, int]:
    cached = read_json(CIK_CACHE)
    if cached and (utcnow() - (parse_dt(cached["fetched_at"])[0] or utcnow())) < timedelta(days=7):
        return cached["map"]
    data = http_get(config.SEC_TICKER_MAP, limiter=_rl).json()
    m = {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in data.values()}
    write_json_atomic(CIK_CACHE, {"fetched_at": iso(utcnow()), "map": m})
    return m


def _txt(node, path) -> str | None:
    el = node.find(path)
    return el.text.strip() if el is not None and el.text else None


def parse_form4(xml: str, symbol: str, filing_url: str, filed_at: str) -> list[dict]:
    root = ET.fromstring(xml)
    owner = _txt(root, "reportingOwner/reportingOwnerId/rptOwnerName") or "unbekannt"
    rel = root.find("reportingOwner/reportingOwnerRelationship")
    roles = []
    if rel is not None:
        if _txt(rel, "isDirector") in ("1", "true"):
            roles.append("Director")
        if _txt(rel, "isOfficer") in ("1", "true"):
            roles.append(_txt(rel, "officerTitle") or "Officer")
        if _txt(rel, "isTenPercentOwner") in ("1", "true"):
            roles.append("10%-Eigentümer")
    plan_10b5 = bool(root.find(".//aff10b5One") is not None and _txt(root, ".//aff10b5One") in ("1", "true"))
    out = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _txt(tx, "transactionCoding/transactionCode") or "J"
        kind, label, open_market = CODES.get(code, ("other", f"Code {code}", False))
        shares = float(_txt(tx, "transactionAmounts/transactionShares/value") or 0)
        price = _txt(tx, "transactionAmounts/transactionPricePerShare/value")
        price_f = float(price) if price else None
        date = _txt(tx, "transactionDate/value")
        out.append({
            "id": stable_id(filing_url, date, code, shares),
            "symbol": symbol, "insider": owner.title(), "role": ", ".join(roles) or "meldepflichtige Person",
            "transaction_code": code, "transaction_kind": kind, "transaction_label": label,
            "open_market": open_market, "rule_10b5_1_plan": plan_10b5,
            "transaction_date": date, "filed_at": filed_at,
            "reporting_delay_days": (parse_dt(filed_at)[0] - parse_dt(date)[0]).days if date and filed_at else None,
            "shares": shares, "price": price_f, "value": round(shares * price_f, 2) if price_f else None,
            "currency": "USD", "source": "SEC EDGAR Form 4", "source_url": filing_url,
        })
    return out


def fetch_form4(symbols: list[str]) -> tuple[list[dict], dict]:
    cmap = cik_map()
    us = [s for s in symbols if s in cmap]
    cur = read_json(CURSOR, {"pos": 0})
    take = min(config.INSIDER_MAX_TICKERS_PER_RUN, len(us))
    start = cur["pos"] % max(len(us), 1)
    batch = (us[start:] + us[:start])[:take]
    since = (utcnow() - timedelta(days=config.INSIDER_LOOKBACK_DAYS)).date().isoformat()
    out, errors = [], 0
    for sym in batch:
        cik = cmap[sym]
        try:
            sub = http_get(config.SEC_SUBMISSIONS.format(cik=cik), limiter=_rl).json()
            rec = sub.get("filings", {}).get("recent", {})
            for form, acc, doc, filed in zip(rec.get("form", []), rec.get("accessionNumber", []),
                                             rec.get("primaryDocument", []), rec.get("filingDate", [])):
                if form != "4" or filed < since:
                    continue
                raw_doc = re.sub(r"^xsl[^/]+/", "", doc)  # Roh-XML statt XSL-Darstellung
                url = config.SEC_ARCHIVE.format(cik=cik, acc=acc.replace("-", ""), doc=raw_doc)
                xml = http_get(url, limiter=_rl).text
                out.extend(parse_form4(xml, sym, url.replace(raw_doc, doc), filed))
        except Exception as exc:  # noqa: BLE001
            errors += 1
            log.warning("Form 4 %s: %s", sym, exc)
    write_json_atomic(CURSOR, {"pos": (start + take) % max(len(us), 1)})
    return out, {"queried": len(batch), "errors": errors, "rotation": f"{take}/{len(us)} US-Ticker je Lauf"}


def import_csv_insiders() -> list[dict]:
    """insider_manual.csv (z. B. BaFin Directors' Dealings): symbol,insider,role,transaction_kind,
    transaction_date,filed_at,shares,price,currency,source_url"""
    p = config.IMPORT_DIR / "insider_manual.csv"
    out = []
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("symbol") or r["symbol"].startswith("#") or not r.get("source_url"):
                continue
            kind = (r.get("transaction_kind") or "other").strip()
            shares = float(r["shares"]) if r.get("shares") else None
            price = float(r["price"]) if r.get("price") else None
            tx, fd = parse_dt(r.get("transaction_date"))[0], parse_dt(r.get("filed_at"))[0]
            out.append({"id": stable_id(r["source_url"], r["insider"], r.get("transaction_date")),
                        "symbol": r["symbol"].strip().upper(), "insider": r["insider"], "role": r.get("role"),
                        "transaction_code": None, "transaction_kind": kind,
                        "transaction_label": {"buy": "Kauf", "sell": "Verkauf"}.get(kind, kind),
                        "open_market": kind in ("buy", "sell"), "rule_10b5_1_plan": False,
                        "transaction_date": r.get("transaction_date"), "filed_at": r.get("filed_at"),
                        "reporting_delay_days": (fd - tx).days if tx and fd else None,
                        "shares": shares, "price": price,
                        "value": round(shares * price, 2) if shares and price else None,
                        "currency": r.get("currency") or "EUR", "source": "CSV-Import (z. B. BaFin)",
                        "source_url": r["source_url"]})
    return out


def merge_store(new: list[dict]) -> list[dict]:
    store = {x["id"]: x for x in read_json(STORE, [])}
    for x in new:
        store[x["id"]] = x
    cutoff = (utcnow() - timedelta(days=400)).date().isoformat()
    items = [x for x in store.values() if (x.get("transaction_date") or "9999") >= cutoff]
    items.sort(key=lambda x: x.get("filed_at") or "", reverse=True)
    write_json_atomic(STORE, items)
    return items


def import_institutional() -> list[dict]:
    """institutional_holdings.csv (13F u. ae.): institution,symbol,report_period,filed_at,shares,
    shares_change,value_usd,position_status(new|increased|reduced|closed|unchanged),pct_outstanding,source_url"""
    p = config.IMPORT_DIR / "institutional_holdings.csv"
    out = []
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("symbol") or (r.get("institution") or "").startswith("#"):
                continue
            rp, fd = parse_dt(r.get("report_period"))[0], parse_dt(r.get("filed_at"))[0]
            num = lambda k: float(r[k]) if r.get(k) else None  # noqa: E731
            out.append({"id": stable_id(r.get("source_url"), r["institution"], r["symbol"], r.get("report_period")),
                        "institution": r["institution"], "symbol": r["symbol"].strip().upper(),
                        "report_period": r.get("report_period"), "filed_at": r.get("filed_at"),
                        "publication_delay_days": (fd - rp).days if rp and fd else None,
                        "shares": num("shares"), "shares_change": num("shares_change"), "value_usd": num("value_usd"),
                        "position_status": r.get("position_status") or "unknown", "pct_outstanding": num("pct_outstanding"),
                        "source_url": r.get("source_url"),
                        "note": "Quartalsmeldung zum Stichtag – keine Echtzeit-Transaktion"})
    return out


def insider_summary(symbol: str, items: list[dict], days: int = 90) -> dict:
    cutoff = (utcnow() - timedelta(days=days)).date().isoformat()
    mine = [x for x in items if x["symbol"] == symbol and (x.get("transaction_date") or "") >= cutoff]
    om = [x for x in mine if x["open_market"]]
    buys = [x for x in om if x["transaction_kind"] == "buy"]
    sells = [x for x in om if x["transaction_kind"] == "sell"]
    return {"window_days": days, "open_market_buys": len(buys), "open_market_sells": len(sells),
            "buy_value": round(sum(x["value"] or 0 for x in buys), 2),
            "sell_value": round(sum(x["value"] or 0 for x in sells), 2),
            "distinct_buyers": len({x["insider"] for x in buys}),
            "other_transactions": len(mine) - len(om)}
