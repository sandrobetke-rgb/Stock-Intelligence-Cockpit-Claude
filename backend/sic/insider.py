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
    owner_cik = _txt(root, "reportingOwner/reportingOwnerId/rptOwnerCik")
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
            "symbol": symbol, "insider": owner.title(), "owner_cik": int(owner_cik) if (owner_cik or "").isdigit() else None, "role": ", ".join(roles) or "meldepflichtige Person",
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


DAILY_INDEX = "https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/form.{d}.idx"
DAYS_STATE = config.STATE_DIR / "insider_days.json"
MAX_DAYS_PER_RUN = int(__import__("os").environ.get("SIC_INSIDER_MAX_DAYS", "8"))


STAKE_FORMS = {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A"}
STAKES = config.STATE_DIR / "big_stakes.json"


def parse_daily_index(text: str, forms: set[str] | None = None) -> list[dict]:
    """form.YYYYMMDD.idx: feste Spalten Form Type | Company Name | CIK | Date Filed | File Name.
    Eine Meldung erscheint je beteiligtem Filer (Emittent und meldende Person) -> nach Datei deduplizieren."""
    out, seen = [], set()
    for ln in text.splitlines():
        parts = re.split(r"\s{2,}", ln.strip())
        if len(parts) < 5 or parts[0] not in (forms or {"4"}) or not parts[-1].startswith("edgar/"):
            continue
        out.append({"form": parts[0], "company": parts[1], "cik": int(parts[-3]), "date": parts[-2], "file": parts[-1]})
    return out


def _extract_xml(txt: str) -> str | None:
    m = re.search(r"<XML>\s*(.*?)\s*</XML>", txt, flags=re.S | re.I)
    return m.group(1) if m else (txt if txt.lstrip().startswith("<?xml") or "<ownershipDocument" in txt else None)


def fetch_form4_daily(symbols: list[str], now=None, watch: dict[int, str] | None = None) -> tuple[list[dict], dict]:
    """Marktweite Insider-Erfassung wie OpenInsider: alle Form-4-Meldungen eines Tages aus dem
    EDGAR-Tagesindex, gefiltert auf Emittenten im Universum. Bereits verarbeitete Tage werden gemerkt."""
    now = now or utcnow()
    cmap = cik_map()
    uni = set(symbols)
    cik2sym: dict[int, str] = {}
    for t, c in sorted(cmap.items()):
        if t in uni and c not in cik2sym:
            cik2sym[c] = t
    done = set(read_json(DAYS_STATE, []))
    days = []
    for back in range(1, config.INSIDER_LOOKBACK_DAYS + 1):
        d = (now - timedelta(days=back)).date()
        if d.weekday() < 5 and d.isoformat() not in done:
            days.append(d)
    days = days[:MAX_DAYS_PER_RUN]          # neueste zuerst; aeltere folgen in spaeteren Laeufen
    out, errors, filings = [], 0, 0
    for d in days:
        url = DAILY_INDEX.format(y=d.year, q=(d.month - 1) // 3 + 1, d=d.strftime("%Y%m%d"))
        try:
            idx_text = http_get(url, limiter=_rl).text
            rows = parse_daily_index(idx_text)
            if watch:
                _collect_stakes(parse_daily_index(idx_text, STAKE_FORMS), cik2sym, watch, d.isoformat())
        except Exception as exc:  # noqa: BLE001
            if "404" in str(exc):          # Feiertag/kein Index
                done.add(d.isoformat())
            else:
                errors += 1
                log.warning("Tagesindex %s: %s", d, exc)
            continue
        files: dict[str, int] = {}
        for r in rows:
            if r["cik"] in cik2sym:
                files.setdefault(r["file"], r["cik"])
        for f, cik in files.items():
            try:
                xml = _extract_xml(http_get("https://www.sec.gov/Archives/" + f, limiter=_rl).text)
                if not xml:
                    continue
                acc = f.rsplit("/", 1)[-1].replace(".txt", "")
                link = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index.htm"
                out.extend(parse_form4(xml, cik2sym[cik], link, d.isoformat()))
                filings += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                log.debug("Form 4 %s: %s", f, exc)
        done.add(d.isoformat())
    cutoff = (now - timedelta(days=config.INSIDER_LOOKBACK_DAYS + 5)).date().isoformat()
    write_json_atomic(DAYS_STATE, sorted(x for x in done if x >= cutoff))
    pending = sum(1 for back in range(1, config.INSIDER_LOOKBACK_DAYS + 1)
                  if (now - timedelta(days=back)).date().weekday() < 5
                  and (now - timedelta(days=back)).date().isoformat() not in done)
    return out, {"days": [x.isoformat() for x in days], "filings": filings, "errors": errors, "days_pending": pending}


def _collect_stakes(rows: list[dict], cik2sym: dict[int, str], watch: dict[int, str], day: str) -> None:
    """13D/13G (Beteiligung > 5 %) von beobachteten Superinvestoren an Firmen im Universum."""
    by_file: dict[str, set[int]] = {}
    forms: dict[str, str] = {}
    for r in rows:
        by_file.setdefault(r["file"], set()).add(r["cik"])
        forms[r["file"]] = r["form"]
    store = {x["id"]: x for x in read_json(STAKES, [])}
    for f, ciks in by_file.items():
        mgr = [c for c in ciks if c in watch]
        iss = [c for c in ciks if c in cik2sym and c not in mgr]
        if not mgr or not iss:
            continue
        acc = f.rsplit("/", 1)[-1].replace(".txt", "")
        sid = acc
        store[sid] = {"id": sid, "manager": watch[mgr[0]], "manager_cik": mgr[0], "symbol": cik2sym[iss[0]],
                      "form": forms[f], "filed_at": day, "activist": "13D" in forms[f],
                      "amendment": forms[f].endswith("/A"),
                      "url": f"https://www.sec.gov/Archives/edgar/data/{iss[0]}/{acc.replace('-', '')}/{acc}-index.htm"}
    write_json_atomic(STAKES, sorted(store.values(), key=lambda x: x["filed_at"], reverse=True)[:500])


def load_stakes(days: int = 120, now=None) -> list[dict]:
    now = now or utcnow()
    cutoff = (now - timedelta(days=days)).date().isoformat()
    return [x for x in read_json(STAKES, []) if x["filed_at"] >= cutoff]


def cluster_buys(items: list[dict], days: int = 14, now=None) -> list[dict]:
    """Cluster-Kauf: mind. zwei verschiedene Insider kaufen am offenen Markt innerhalb von `days` Tagen."""
    now = now or utcnow()
    cutoff = (now - timedelta(days=days)).date().isoformat()
    by: dict[str, list[dict]] = {}
    for x in items:
        if x.get("transaction_kind") == "buy" and x.get("open_market") and (x.get("transaction_date") or "") >= cutoff:
            by.setdefault(x["symbol"], []).append(x)
    out = []
    for sym, xs in by.items():
        people = {x["insider"] for x in xs}
        if len(people) >= 2:
            out.append({"symbol": sym, "insiders": len(people), "transactions": len(xs),
                        "value": round(sum(x.get("value") or 0 for x in xs), 2),
                        "roles": sorted({x.get("role") or "" for x in xs} - {""})[:6],
                        "first": min(x["transaction_date"] for x in xs), "last": max(x["transaction_date"] for x in xs)})
    return sorted(out, key=lambda c: (-c["insiders"], -c["value"]))


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
