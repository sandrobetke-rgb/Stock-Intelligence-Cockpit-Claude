"""Kurs- und Marktdaten (Lastenheft Kap. 12) und Fundamentaldaten-Abruf.

Technische Kennzahlen dienen nur dem Markt-Kontext und fliessen NICHT in Company Quality ein.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import numpy as np
import pandas as pd

from . import config
from .util import chunked, clean_number, iso, parse_dt, read_json, utcnow, write_json_atomic

log = logging.getLogger("sic.market")
FUND_CACHE = config.CACHE_DIR / "fundamentals"


# ------------------------------------------------------------ Kennzahlen --
def compute_metrics(df: pd.DataFrame) -> dict:
    """df: OHLCV eines Titels (Index = Datum). Gibt Marktkontext zurück; fehlend -> None."""
    out: dict = {"flags": []}
    df = df.dropna(subset=["Close"]) if "Close" in df else pd.DataFrame()
    if df.empty:
        out["flags"].append("no_price_data")
        return out
    close, high, low = df["Close"], df["High"], df["Low"]
    vol = df["Volume"] if "Volume" in df else pd.Series(dtype=float)
    n = len(close)
    out["last_close"] = clean_number(close.iloc[-1])
    out["price_date"] = close.index[-1].date().isoformat()

    def perf(k: int) -> float | None:
        return clean_number((close.iloc[-1] / close.iloc[-1 - k] - 1) * 100) if n > k else None

    out["perf_20d"] = perf(20)
    out["perf_63d"] = perf(63)
    # ADR20 (%): Mittel der Tagesrange relativ zum Tief über 20 Tage
    if n >= 20:
        out["adr20"] = clean_number(((high / low - 1) * 100).tail(20).mean())
    else:
        out["adr20"] = None
        out["flags"].append("short_history")
    if len(vol) >= 21 and vol.tail(21).iloc[:-1].mean() > 0:
        out["rvol"] = clean_number(vol.iloc[-1] / vol.tail(21).iloc[:-1].mean())
    else:
        out["rvol"] = None
    out["ema10"] = clean_number(close.ewm(span=10, adjust=False).mean().iloc[-1]) if n >= 10 else None
    out["ema21"] = clean_number(close.ewm(span=21, adjust=False).mean().iloc[-1]) if n >= 21 else None
    out["sma50"] = clean_number(close.rolling(50).mean().iloc[-1]) if n >= 50 else None
    out["sma200"] = clean_number(close.rolling(200).mean().iloc[-1]) if n >= 200 else None
    # Volatilität (annualisiert) für Risk Score
    rets = close.pct_change().dropna()
    out["volatility_ann"] = clean_number(rets.tail(63).std() * np.sqrt(252) * 100) if len(rets) >= 40 else None
    out["avg_dollar_volume_20d"] = clean_number((close * vol).tail(20).mean()) if len(vol) >= 20 else None
    # Datenlücken: fehlende Handelstage im letzten Monat (> 5 Kalendertage Abstand)
    gaps = close.index.to_series().diff().dt.days.tail(22)
    if (gaps > 5).any():
        out["flags"].append("data_gap")
    age = (utcnow().date() - close.index[-1].date()).days
    if age > 4:
        out["flags"].append("stale_price")
    # Volumen-/Kursauffaelligkeit für Market Intelligence
    if n > 21:
        ret_today = close.iloc[-1] / close.iloc[-2] - 1
        sd = rets.tail(63).std()
        out["move_zscore"] = clean_number(ret_today / sd) if sd and sd > 0 else None
    if {"Open", "High", "Low", "Volume"} <= set(df.columns):
        try:
            from .setups import evaluate
            out["swing"] = evaluate(df)
        except Exception as exc:  # noqa: BLE001
            log.debug("Swing-Auswertung: %s", exc)
    return out


def fetch_prices(symbols: list[str]) -> tuple[dict[str, dict], list[str]]:
    """Gebündelte Kursabfragen über yfinance (inoffizieller Zugang, Limits beachten)."""
    import yfinance as yf

    results: dict[str, dict] = {}
    errors: list[str] = []
    for batch in chunked(symbols, config.PRICE_BATCH_SIZE):
        try:
            data = yf.download(batch, period="2y", interval="1d", group_by="ticker",
                               auto_adjust=True, threads=True, progress=False)
        except Exception as exc:
            log.error("Kursbatch fehlgeschlagen: %s", exc)
            errors.extend(batch)
            continue
        for sym in batch:
            try:
                df = data[sym] if isinstance(data.columns, pd.MultiIndex) else data
                m = compute_metrics(df)
                if "no_price_data" in m["flags"]:
                    errors.append(sym)
                results[sym] = m
            except KeyError:
                errors.append(sym)
                results[sym] = {"flags": ["no_price_data"]}
    return results, errors


# ------------------------------------------------------- Fundamentaldaten --
def _row(df: pd.DataFrame | None, *names: str) -> list[float | None]:
    """Zeile aus yfinance-Abschluss (Spalten = Jahre, neu -> alt)."""
    if df is None or df.empty:
        return []
    for n in names:
        if n in df.index:
            return [clean_number(v) for v in df.loc[n].tolist()]
    return []


def extract_fundamentals(info: dict, fin: pd.DataFrame | None, bs: pd.DataFrame | None,
                         cf: pd.DataFrame | None) -> dict:
    """Normalisiert yfinance-Daten in ein quellenbelegtes Kennzahlenset."""
    rev = _row(fin, "Total Revenue", "Operating Revenue")
    op_inc = _row(fin, "Operating Income")
    net_inc = _row(fin, "Net Income", "Net Income Common Stockholders")
    int_exp = _row(fin, "Interest Expense")
    ebit = _row(fin, "EBIT")
    rnd = _row(fin, "Research And Development")
    ocf = _row(cf, "Operating Cash Flow")
    capex = _row(cf, "Capital Expenditure")
    fcf = _row(cf, "Free Cash Flow")
    buyback = _row(cf, "Repurchase Of Capital Stock")
    shares = _row(bs, "Ordinary Shares Number", "Share Issued")
    debt = _row(bs, "Total Debt")
    cash = _row(bs, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")
    equity = _row(bs, "Stockholders Equity", "Total Equity Groß Minority Interest")
    cur_a = _row(bs, "Current Assets")
    cur_l = _row(bs, "Current Liabilities")

    def g(xs, i=0):
        return xs[i] if len(xs) > i else None

    def cagr(xs, years):
        a, b = g(xs, 0), g(xs, years)
        if a is None or b is None or b <= 0 or a <= 0:
            return None
        return ((a / b) ** (1 / years) - 1) * 100

    def ratio(a, b, pct=True):
        if a is None or b in (None, 0):
            return None
        return a / b * (100 if pct else 1)

    years = min(3, max(len(rev) - 1, 0))
    f = {
        "revenue": g(rev),
        "revenue_cagr": cagr(rev, years) if years >= 2 else None,
        "revenue_cagr_years": years if years >= 2 else None,
        "revenue_growth_yoy": cagr(rev, 1),
        "operating_margin": ratio(g(op_inc), g(rev)),
        "operating_margin_prev": ratio(g(op_inc, 1), g(rev, 1)),
        "net_margin": ratio(g(net_inc), g(rev)),
        "debt_to_equity": ratio(g(debt), g(equity), pct=False) if (g(equity) or 0) > 0 else None,
        "net_debt": (g(debt) - g(cash)) if g(debt) is not None and g(cash) is not None else None,
        "current_ratio": ratio(g(cur_a), g(cur_l), pct=False),
        "interest_coverage": ratio(g(ebit), abs(g(int_exp)) if g(int_exp) else None, pct=False),
        "operating_cashflow": g(ocf),
        "free_cashflow": g(fcf) if g(fcf) is not None else (g(ocf) + g(capex) if g(ocf) is not None and g(capex) is not None else None),
        "fcf_margin": None,
        "capex_intensity": ratio(abs(g(capex)) if g(capex) is not None else None, g(rev)),
        "rnd_intensity": ratio(g(rnd), g(rev)),
        "roe": ratio(g(net_inc), g(equity)) if (g(equity) or 0) > 0 else None,
        "share_change_yoy": ratio((g(shares) or 0) - (g(shares, 1) or 0), g(shares, 1)) if g(shares) and g(shares, 1) else None,
        "buyback": g(buyback),
        "market_cap": clean_number(info.get("marketCap")),
        "market_cap_currency": info.get("currency") or info.get("financialCurrency"),
        "financial_currency": info.get("financialCurrency"),
        "trailing_pe": clean_number(info.get("trailingPE")),
        "forward_pe": clean_number(info.get("forwardPE")),
        "price_to_sales": clean_number(info.get("priceToSalesTrailing12Months")),
        "beta": clean_number(info.get("beta")),
        "gross_margin": clean_number(info["grossMargins"] * 100) if clean_number(info.get("grossMargins")) is not None else None,
        "revenue_growth_forward": clean_number(info["revenueGrowth"] * 100) if clean_number(info.get("revenueGrowth")) is not None else None,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "long_name": info.get("longName") or info.get("shortName"),
        "fiscal_year_end": None,
        "audit_risk": clean_number(info.get("auditRisk")),
        "next_earnings_ts": clean_number(info.get("earningsTimestampStart") or info.get("earningsTimestamp")),
        "earnings_is_estimate": bool(info.get("isEarningsDateEstimate")),
        "ex_dividend_ts": clean_number(info.get("exDividendDate")),
        "board_risk": clean_number(info.get("boardRisk")),
        "top_customer_share": None,  # nicht kostenlos verfügbar -> unknown / CSV-Import
    }
    if f["free_cashflow"] is not None and f["revenue"]:
        f["fcf_margin"] = f["free_cashflow"] / f["revenue"] * 100
    if fin is not None and not fin.empty:
        try:
            f["fiscal_year_end"] = pd.Timestamp(fin.columns[0]).date().isoformat()
        except Exception:  # noqa: BLE001
            pass
    return {k: (clean_number(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in f.items()}


def _cache_path(sym: str):
    return FUND_CACHE / f"{sym.replace('/', '_')}.json"


def load_fundamentals(sym: str) -> dict | None:
    return read_json(_cache_path(sym))


def refresh_fundamentals(symbols: list[str]) -> dict:
    """Gestaffelte Aktualisierung: älteste Caches zuerst, max. N pro Lauf."""
    import yfinance as yf

    now = utcnow()
    def age(sym):
        c = load_fundamentals(sym)
        if not c:
            return timedelta(days=10_000)
        dt, _ = parse_dt(c.get("fetched_at"))
        return now - dt if dt else timedelta(days=10_000)

    due = [s for s in symbols if age(s) > timedelta(days=config.FUNDAMENTALS_REFRESH_DAYS)]
    due.sort(key=age, reverse=True)
    stats = {"due": len(due), "refreshed": 0, "errors": []}
    for sym in due[: config.FUNDAMENTALS_MAX_PER_RUN]:
        try:
            t = yf.Ticker(sym)
            info = t.info or {}
            f = extract_fundamentals(info, t.financials, t.balance_sheet, t.cashflow)
            write_json_atomic(_cache_path(sym), {
                "symbol": sym, "fetched_at": iso(now), "source": "Yahoo Finance (yfinance)",
                "source_url": f"https://finance.yahoo.com/quote/{sym}/financials", "data": f})
            stats["refreshed"] += 1
        except Exception as exc:  # Datenfehler != Ausschluss (3.4)
            log.warning("Fundamentaldaten %s: %s", sym, exc)
            stats["errors"].append(sym)
    return stats
