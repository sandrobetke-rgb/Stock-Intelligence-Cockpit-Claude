"""Aktiengeschäfte von US-Kongressmitgliedern (wie CapitolTrades), direkt aus den offiziellen
Offenlegungen nach dem STOCK Act:

- Repräsentantenhaus: Jahresindex (ZIP/XML) des House Clerk + PTR-PDFs je Meldung
- Senat: eFD-Datenbank (efdsearch.senate.gov), elektronische PTRs als HTML-Tabellen

Rechtlicher Hinweis (5 U.S.C. § 13107): Die Daten dürfen nicht für kommerzielle Zwecke, Kredit-
würdigkeitsprüfung oder Spendenwerbung verwendet werden – private Analyse ist zulässig.
Meldungen erfolgen bis zu 45 Tage nach dem Geschäft; Beträge sind nur als Bandbreite angegeben.
Handschriftliche/gescannte Meldungen können nicht ausgewertet werden und erscheinen nur als Link.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

import requests

from . import config
from .util import RateLimiter, iso, read_json, stable_id, utcnow, write_json_atomic

log = logging.getLogger("sic.congress")
HOUSE_INDEX = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{y}FD.zip"
HOUSE_PTR = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{y}/{doc}.pdf"
SENATE = "https://efdsearch.senate.gov"
LOOKBACK_DAYS = 90
MAX_NEW_DOCS = 150
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}
_rl = RateLimiter(2.0)
TX = {"P": "purchase", "S": "sale", "S (partial)": "sale_partial", "E": "exchange",
      "Purchase": "purchase", "Sale (Full)": "sale", "Sale (Partial)": "sale_partial", "Exchange": "exchange"}
OWNER = {"SP": "Ehepartner", "JT": "Gemeinsam", "DC": "Kind", "Self": "Selbst", "Spouse": "Ehepartner",
         "Joint": "Gemeinsam", "Child": "Kind"}


def _state():
    return config.STATE_DIR / "congress.json"


def _amount(s: str) -> tuple[float | None, float | None]:
    nums = [float(x.replace(",", "")) for x in re.findall(r"\$([\d,]+)", s or "")]
    if not nums:
        return None, None
    if (s or "").lower().startswith("over") or len(nums) == 1:
        return nums[0], None
    return nums[0], nums[1]


def _date(s: str) -> str | None:
    try:
        return datetime.strptime(s.strip(), "%m/%d/%Y").date().isoformat()
    except (ValueError, AttributeError):
        return None


# ------------------------------------------------------------------ Haus --
def parse_house_index(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for m in root.iter("Member"):
        g = lambda t: (m.findtext(t) or "").strip()  # noqa: E731
        if g("FilingType") != "P" or not g("DocID"):
            continue
        out.append({"doc_id": g("DocID"), "name": " ".join(x for x in (g("First"), g("Last"), g("Suffix")) if x),
                    "state_district": g("StateDst"), "year": g("Year"), "filed": _date(g("FilingDate"))})
    return out


PTR_RE = re.compile(
    r"(?:\b(SP|JT|DC)\s+)?(?P<asset>[^()\[\]]{2,160}?)\s*\((?P<ticker>[A-Z][A-Z0-9.\-]{0,7})\)\s*"
    r"\[(?P<atype>[A-Z]{2})\]\s*(?P<tx>S \(partial\)|P|S|E)\s+(?P<d1>\d{2}/\d{2}/\d{4})\s*(?P<d2>\d{2}/\d{2}/\d{4})\s*"
    r"(?P<amt>Over \$[\d,]+|\$[\d,]+\s*-\s*\$[\d,]+|\$[\d,]+)")


def _clean_asset(raw: str, owner: str | None) -> tuple[str, str | None]:
    """Entfernt Kopf-/Fußzeilenreste vor dem Wertpapiernamen und erkennt das Eigentümerkürzel."""
    a = raw.split("?")[-1]                                   # Tabellenkopf endet mit "Cap. Gains > $200?"
    a = re.sub(r"^.*(?:F S|S O|Filing Status|Description|Subholding Of)\s*:\s*\S+\s*", "", a)
    m = re.search(r"(?:^|\s)(SP|JT|DC)\s+(?!.*\s(?:SP|JT|DC)\s)(.*)$", a)
    if m:
        owner, a = m.group(1), m.group(2)
    return a.strip(" -:"), owner


def parse_house_ptr_text(text: str) -> list[dict]:
    t = re.sub(r"\s+", " ", (text or "").replace("\x00", " "))
    out = []
    for m in PTR_RE.finditer(t):
        if m.group("atype") not in ("ST", "OP"):
            continue
        lo, hi = _amount(m.group("amt"))
        asset, owner = _clean_asset(m.group("asset"), m.group(1))
        out.append({"owner": OWNER.get(owner or "", "Selbst"), "asset": asset,
                    "ticker": m.group("ticker").replace(".", "-"), "asset_type": "Option" if m.group("atype") == "OP" else "Aktie",
                    "tx": TX.get(m.group("tx"), m.group("tx")), "transaction_date": _date(m.group("d1")),
                    "notification_date": _date(m.group("d2")), "amount_min": lo, "amount_max": hi})
    return out


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


def fetch_house(known: set[str], now: datetime, sess: requests.Session) -> tuple[list[dict], list[dict], int]:
    since = (now - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    filings = []
    for y in sorted({now.year, (now - timedelta(days=LOOKBACK_DAYS)).year}):
        _rl.wait()
        r = sess.get(HOUSE_INDEX.format(y=y), timeout=60)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".xml"))
            filings += parse_house_index(z.read(name))
    filings = sorted([f for f in filings if (f["filed"] or "") >= since], key=lambda f: f["filed"] or "", reverse=True)
    trades, docs, errors = [], [], 0
    for f in [f for f in filings if f"H{f['doc_id']}" not in known][:MAX_NEW_DOCS]:
        url = HOUSE_PTR.format(y=f["year"], doc=f["doc_id"])
        doc = {"key": f"H{f['doc_id']}", "chamber": "Repräsentantenhaus", "politician": f["name"],
               "state": f["state_district"], "filed": f["filed"], "url": url, "parsed": 0}
        try:
            _rl.wait()
            r = sess.get(url, timeout=60)
            r.raise_for_status()
            rows = parse_house_ptr_text(_pdf_text(r.content))
            doc["parsed"] = len(rows)
            for x in rows:
                trades.append({**x, "chamber": "Repräsentantenhaus", "politician": f["name"], "state": f["state_district"],
                               "disclosure_date": f["filed"], "source_url": url, "doc": doc["key"]})
        except Exception as exc:  # noqa: BLE001
            errors += 1
            log.debug("House PTR %s: %s", url, exc)
            continue                       # beim nächsten Lauf erneut versuchen
        docs.append(doc)
    return trades, docs, errors


# ----------------------------------------------------------------- Senat --
def parse_senate_ptr_html(html: str) -> list[dict]:
    import pandas as pd

    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        return []
    out = []
    for t in tables:
        cols = {str(c).strip().lower(): c for c in t.columns}
        if "ticker" not in cols or "transaction date" not in cols:
            continue
        for _, r in t.iterrows():
            ticker = str(r[cols["ticker"]]).strip()
            atype = str(r[cols.get("asset type", cols["ticker"])]).strip()
            if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,7}", ticker) or ("Stock" not in atype and "Option" not in atype):
                continue
            lo, hi = _amount(str(r[cols.get("amount", cols["ticker"])]))
            typ = str(r[cols.get("type", cols["ticker"])]).strip()
            out.append({"owner": OWNER.get(str(r[cols.get("owner", cols["ticker"])]).strip(), "Selbst"),
                        "asset": str(r[cols.get("asset name", cols["ticker"])]).strip()[:160], "ticker": ticker.replace(".", "-"),
                        "asset_type": "Option" if "Option" in atype else "Aktie", "tx": TX.get(typ, typ.lower()),
                        "transaction_date": _date(str(r[cols["transaction date"]])), "notification_date": None,
                        "amount_min": lo, "amount_max": hi})
    return out


def fetch_senate(known: set[str], now: datetime, sess: requests.Session) -> tuple[list[dict], list[dict], int]:
    home = f"{SENATE}/search/home/"
    _rl.wait()
    r = sess.get(home, timeout=30)
    r.raise_for_status()
    m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text)
    if not m:
        raise ValueError("Senat: Zustimmungsformular nicht gefunden")
    _rl.wait()
    sess.post(home, data={"prohibition_agreement": "1", "csrfmiddlewaretoken": m.group(1)},
              headers={"Referer": home}, timeout=30).raise_for_status()
    token = sess.cookies.get("csrftoken") or m.group(1)
    since = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%m/%d/%Y 00:00:00")
    rows, start = [], 0
    while start < 1000:
        _rl.wait()
        r = sess.post(f"{SENATE}/search/report/data/", timeout=30,
                      headers={"Referer": f"{SENATE}/search/", "X-CSRFToken": token},
                      data={"start": str(start), "length": "100", "report_types": "[11]", "filer_types": "[]",
                            "submitted_start_date": since, "submitted_end_date": "", "candidate_state": "",
                            "senator_state": "", "office_id": "", "first_name": "", "last_name": "",
                            "csrfmiddlewaretoken": token})
        r.raise_for_status()
        data = r.json().get("data") or []
        rows += data
        if len(data) < 100:
            break
        start += 100
    trades, docs, errors, new = [], [], 0, 0
    for row in rows:
        first, last, _office, link, filed = (row + [""] * 5)[:5]
        hm = re.search(r'href="([^"]+)"', link or "")
        if not hm:
            continue
        url = SENATE + hm.group(1)
        key = "S" + hm.group(1).rstrip("/").rsplit("/", 1)[-1]
        if key in known:
            continue
        name = f"{first} {last}".strip().title()
        doc = {"key": key, "chamber": "Senat", "politician": name, "state": None, "filed": _date(filed), "url": url, "parsed": 0}
        if "/paper/" in url:
            docs.append(doc)               # gescannte Meldung: nur als Link
            continue
        if new >= MAX_NEW_DOCS:
            continue
        new += 1
        try:
            _rl.wait()
            pr = sess.get(url, timeout=30, headers={"Referer": f"{SENATE}/search/"})
            pr.raise_for_status()
            parsed = parse_senate_ptr_html(pr.text)
            doc["parsed"] = len(parsed)
            for x in parsed:
                trades.append({**x, "chamber": "Senat", "politician": name, "state": None,
                               "disclosure_date": doc["filed"], "source_url": url, "doc": key})
        except Exception as exc:  # noqa: BLE001
            errors += 1
            log.debug("Senate PTR %s: %s", url, exc)
            continue
        docs.append(doc)
    return trades, docs, errors


# --------------------------------------------------------------- Gesamt ---
def build(universe: set[str], fetch: bool = True, now: datetime | None = None) -> dict:
    now = now or utcnow()
    st = read_json(_state(), {"docs": [], "trades": []})
    known = {d["key"] for d in st["docs"]}
    status = []
    if fetch:
        for name, fn in (("Repräsentantenhaus", fetch_house), ("Senat", fetch_senate)):
            sess = requests.Session()
            sess.headers.update(BROWSER)
            try:
                t, d, err = fn(known, now, sess)
                st["trades"] += t
                st["docs"] += d
                known |= {x["key"] for x in d}
                status.append({"chamber": name, "status": "ok", "new_reports": len(d), "new_trades": len(t), "errors": err})
            except Exception as exc:  # noqa: BLE001
                log.warning("Kongress %s: %s", name, exc)
                status.append({"chamber": name, "status": "error", "message": str(exc)[:200]})
        cutoff = (now - timedelta(days=LOOKBACK_DAYS + 30)).date().isoformat()
        st["docs"] = [d for d in st["docs"] if (d.get("filed") or "9") >= cutoff]
        st["trades"] = [t for t in st["trades"] if (t.get("disclosure_date") or "9") >= cutoff]
        st["status"] = status
        st["fetched_at"] = iso(now)
        write_json_atomic(_state(), st)
    trades, seen = [], Counter()
    for t in st["trades"]:
        tx, disc = t.get("transaction_date"), t.get("disclosure_date")
        delay = (datetime.fromisoformat(disc) - datetime.fromisoformat(tx)).days if tx and disc else None
        base = stable_id(t["doc"], t["ticker"], tx, t["tx"], t.get("amount_min"), t.get("owner"))
        seen[base] += 1
        trades.append({"id": f"{base}-{seen[base]}",
                       "politician": t["politician"], "chamber": t["chamber"], "party": None, "state": t.get("state"),
                       "symbol": t["ticker"], "in_universe": t["ticker"] in universe, "asset": t["asset"],
                       "asset_type": t["asset_type"], "owner": t["owner"], "transaction_type": t["tx"],
                       "transaction_date": tx, "disclosure_date": disc, "reporting_delay_days": delay,
                       "amount_range": [t.get("amount_min"), t.get("amount_max")], "source_url": t["source_url"],
                       "note": "Offizielle STOCK-Act-Meldung; Wertbandbreite, bis 45 Tage Meldeverzug"})
    trades.sort(key=lambda x: (x["disclosure_date"] or "", x["transaction_date"] or ""), reverse=True)
    unparsed = [d for d in st["docs"] if not d.get("parsed")]
    return {"trades": trades, "status": st.get("status", []), "fetched_at": st.get("fetched_at"),
            "unparsed_reports": sorted(unparsed, key=lambda d: d.get("filed") or "", reverse=True)[:100]}
