"""Unternehmenstermine: nächste Quartalszahlen (Earnings) und Ex-Dividende.

- USA: Nasdaq-Kalender (api.nasdaq.com, frei abrufbar; inoffizieller Zugang, Bedingungen prüfen),
  eine Abfrage je Kalendertag deckt den gesamten US-Markt ab
- Übrige (z. B. DAX): Termine aus den Yahoo-Fundamentaldaten (earningsTimestamp, exDividendDate)
Termine sind Ankündigungen bzw. Schätzungen der Quelle und werden als solche gekennzeichnet.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone

from . import config
from .util import RateLimiter, http_get, iso, read_json, utcnow, write_json_atomic

log = logging.getLogger("sic.corporate_events")
EARNINGS_URL = "https://api.nasdaq.com/api/calendar/earnings?date={d}"
DIVIDENDS_URL = "https://api.nasdaq.com/api/calendar/dividends?date={d}"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) StockIntelligenceCockpit/1.1",
           "Accept": "application/json, text/plain, */*"}
DAYS_AHEAD = 30
DAYS_BACK = 3
_rl = RateLimiter(2.0)
TIME_LABEL = {"time-pre-market": "vor Börseneröffnung", "time-after-hours": "nach Börsenschluss"}


def _state():
    return config.STATE_DIR / "corporate_events.json"


def _sym(s: str) -> str:
    return (s or "").strip().upper().replace(".", "-").replace("/", "-")


def _money(s) -> float | None:
    m = re.search(r"-?[\d.]+", str(s or "").replace(",", ""))
    if not m:
        return None
    v = float(m.group())
    return -abs(v) if "(" in str(s) else v


def parse_earnings(payload: dict, day: str) -> list[dict]:
    rows = ((payload.get("data") or {}).get("rows")) or []
    out = []
    for r in rows:
        if not r.get("symbol"):
            continue
        out.append({"symbol": _sym(r["symbol"]), "type": "earnings", "date": day,
                    "time": TIME_LABEL.get(r.get("time") or "", "Uhrzeit offen"),
                    "fiscal_quarter": r.get("fiscalQuarterEnding"), "eps_forecast": _money(r.get("epsForecast")),
                    "estimates": int(r["noOfEsts"]) if str(r.get("noOfEsts") or "").isdigit() else None,
                    "confirmed": True, "source": "Nasdaq-Earnings-Kalender",
                    "source_url": f"https://www.nasdaq.com/market-activity/stocks/{r['symbol'].lower()}/earnings"})
    return out


def parse_dividends(payload: dict) -> list[dict]:
    rows = (((payload.get("data") or {}).get("calendar") or {}).get("rows")) or []
    out = []
    for r in rows:
        ex = r.get("dividend_Ex_Date") or ""
        try:
            exd = datetime.strptime(ex, "%m/%d/%Y").date().isoformat()
        except ValueError:
            continue
        pay = r.get("payment_Date") or ""
        try:
            payd = datetime.strptime(pay, "%m/%d/%Y").date().isoformat()
        except ValueError:
            payd = None
        out.append({"symbol": _sym(r.get("symbol")), "type": "ex_dividend", "date": exd, "payment_date": payd,
                    "amount": _money(r.get("dividend_Rate")), "annual": _money(r.get("indicated_Annual_Dividend")),
                    "confirmed": True, "source": "Nasdaq-Dividendenkalender",
                    "source_url": f"https://www.nasdaq.com/market-activity/stocks/{(r.get('symbol') or '').lower()}/dividend-history"})
    return out


def from_fundamentals(symbol: str, f: dict | None, today: date) -> list[dict]:
    """Ausweichquelle (v. a. Nicht-US): Yahoo-Termine aus dem Fundamentaldaten-Cache."""
    out = []
    f = f or {}
    for key, typ in (("next_earnings_ts", "earnings"), ("ex_dividend_ts", "ex_dividend")):
        ts = f.get(key)
        if not ts:
            continue
        d = datetime.fromtimestamp(float(ts), tz=timezone.utc).date()
        if today - timedelta(days=DAYS_BACK) <= d <= today + timedelta(days=DAYS_AHEAD):
            out.append({"symbol": symbol, "type": typ, "date": d.isoformat(), "time": "Uhrzeit offen",
                        "confirmed": not f.get("earnings_is_estimate", False) if typ == "earnings" else True,
                        "source": "Yahoo Finance", "source_url": f"https://finance.yahoo.com/quote/{symbol}"})
    return out


def build(symbols: set[str], fundamentals: dict[str, dict], fetch: bool = True, now: datetime | None = None) -> dict[str, list[dict]]:
    """Gibt je Symbol die Termine im Fenster [heute-3, heute+30] zurück (sortiert)."""
    now = now or utcnow()
    today = now.date()
    cached = read_json(_state(), {"days": {}, "fetched_at": None})
    days = cached.get("days", {})
    if fetch:
        for off in range(-DAYS_BACK, DAYS_AHEAD + 1):
            d = today + timedelta(days=off)
            ds = d.isoformat()
            if d.weekday() >= 5:
                continue
            # Vergangene Tage nicht erneut laden; kommende täglich aktualisieren (Termine verschieben sich)
            if ds in days and d < today:
                continue
            try:
                e = parse_earnings(http_get(EARNINGS_URL.format(d=ds), headers=HEADERS, limiter=_rl).json(), ds)
                v = parse_dividends(http_get(DIVIDENDS_URL.format(d=ds), headers=HEADERS, limiter=_rl).json())
                days[ds] = e + [x for x in v if x["date"] == ds]
            except Exception as exc:  # noqa: BLE001
                log.warning("Terminkalender %s: %s", ds, exc)
        lo = (today - timedelta(days=DAYS_BACK + 2)).isoformat()
        days = {k: v for k, v in days.items() if k >= lo}
        write_json_atomic(_state(), {"days": days, "fetched_at": iso(now)})
    out: dict[str, list[dict]] = {}
    for ds, items in days.items():
        for it in items:
            if it["symbol"] in symbols:
                out.setdefault(it["symbol"], []).append(it)
    for sym in symbols:
        if sym not in out:   # Nicht-US oder fehlt im Nasdaq-Kalender
            extra = from_fundamentals(sym, (fundamentals.get(sym) or {}).get("data"), today)
            if extra:
                out[sym] = extra
    lo, hi = (today - timedelta(days=DAYS_BACK)).isoformat(), (today + timedelta(days=DAYS_AHEAD)).isoformat()
    for sym in list(out):
        seen, items = set(), []
        for it in sorted(out[sym], key=lambda x: x["date"]):
            k = (it["type"], it["date"])
            if lo <= it["date"] <= hi and k not in seen:
                seen.add(k)
                it["days_until"] = (date.fromisoformat(it["date"]) - today).days
                items.append(it)
        if items:
            out[sym] = items
        else:
            del out[sym]
    return out
