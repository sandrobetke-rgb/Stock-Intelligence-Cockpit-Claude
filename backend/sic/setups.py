"""Swing-Setups nach Sandros Regelwerk (Tageskerzen, Auswertung nach Börsenschluss).

Abgebildet sind die vier TradingView-Screener S01–S04, der Abendfilter und die Einstiegs-/Stopp-
Regel als Plan für den nächsten Handelstag. Der eigentliche Einstieg (1H-Kerze schließt über dem
Vortageshoch ab 16:00 MEZ, max. 2 % darüber) wird weiterhin im Chart geprüft – das Cockpit liefert
nur die Kandidaten und die Preismarken. Kennzeichnung "approx" = Annäherung an einen TradingView-
Indikator, dessen exakte Formel nicht öffentlich ist (Trader XO).

Technische Kennzahlen fließen nicht in Company Quality ein.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .util import clean_number

# Regelwerk (Stand Memory/Projekt "Meine Aktienstrategie")
FILTER = {"rvol_min": 1.2, "rsi_max": 65, "atr_pct_min": 1.5, "atr_pct_max": 5.0}
ENTRY = {"max_above_trigger_pct": 2.0, "stop_atr": 1.5, "rrr": 2.0, "risk_pct": 1.0, "max_positions": 3}

SETUP_INFO = {
    "S01": {"name": "S01 Rebound", "text": "Überverkaufte Umkehr: RSI war in den letzten 5 Tagen unter 35, heute Hammer- oder bullische Engulfing-Kerze."},
    "S02": {"name": "S02 Rising Star", "text": "Frisch über EMA 200: Kurs > EMA 200 (max. 5 % darüber), Kurs < EMA 50, RSI 45–62, RelVol > 0,8, EMA 20 > SMA 50, Marktkap. > 1 Mrd., Volumen 30T > 1 Mio., Kurs > 10, Tag positiv."},
    "S03": {"name": "S03 Breakout", "text": "Nahe 52-Wochen-Hoch (0–5 % darunter), MACD über Signallinie, Volumen über Schnitt."},
    "S04": {"name": "S04 HHLL + OBV", "text": "Höhere Hochs und höhere Tiefs, steigendes OBV, Trend-Signal (EMA 12 > EMA 25, Annäherung an Trader XO), mehr als 5 % Abstand zum 52-Wochen-Hoch. Einstieg über dem letzten Higher High."},
}


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _candles(df: pd.DataFrame) -> dict:
    o, h, l, c = (float(df[k].iloc[-1]) for k in ("Open", "High", "Low", "Close"))
    po, pc = float(df["Open"].iloc[-2]), float(df["Close"].iloc[-2])
    body, rng = abs(c - o), max(h - l, 1e-9)
    lower, upper = min(o, c) - l, h - max(o, c)
    hammer = rng > 0 and lower >= 2 * body and upper <= max(body, rng * 0.15) and body / rng <= 0.35
    engulf = c > o and pc < po and c >= po and o <= pc
    return {"hammer": bool(hammer), "bull_engulfing": bool(engulf), "green": c > o}


def _swing_points(s: pd.Series, k: int = 3, mode: str = "high") -> list[float]:
    """Lokale Hoch-/Tiefpunkte (k Kerzen links und rechts)."""
    v = s.values
    pts = []
    for i in range(k, len(v) - k):
        win = v[i - k:i + k + 1]
        if (mode == "high" and v[i] == win.max()) or (mode == "low" and v[i] == win.min()):
            pts.append(float(v[i]))
    return pts


def evaluate(df: pd.DataFrame, market_cap: float | None = None) -> dict | None:
    """Technik-Kennzahlen, Setup-Treffer und Einstiegsplan für den nächsten Handelstag."""
    df = df.dropna(subset=["Close", "High", "Low", "Open"])
    if len(df) < 60:
        return None
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"].fillna(0)
    last = float(close.iloc[-1])
    ema = {n: float(_ema(close, n).iloc[-1]) for n in (12, 20, 25, 50, 200)}
    sma50 = float(close.rolling(50).mean().iloc[-1])
    rsi = _rsi(close)
    atr = float(_atr(df).iloc[-1])
    macd = _ema(close, 12) - _ema(close, 26)
    sig = _ema(macd, 9)
    obv = (np.sign(close.diff().fillna(0)) * vol).cumsum()
    hi52 = float(high.tail(252).max())
    vol20 = float(vol.iloc[-21:-1].mean()) if len(vol) > 21 else None
    vol30 = float(vol.tail(30).mean())
    rvol = float(vol.iloc[-1]) / vol20 if vol20 else None
    chg = (last / float(close.iloc[-2]) - 1) * 100
    cdl = _candles(df)
    sh, sl = _swing_points(high.tail(60), 3, "high"), _swing_points(low.tail(60), 3, "low")
    hh = len(sh) >= 2 and sh[-1] > sh[-2]
    hl = len(sl) >= 2 and sl[-1] > sl[-2]
    last_hh = sh[-1] if sh else None
    t = {
        "close": last, "change_pct": chg, "ema20": ema[20], "ema50": ema[50], "ema200": ema[200], "sma50": sma50,
        "rsi14": float(rsi.iloc[-1]), "rsi_min5": float(rsi.tail(5).min()), "atr14": atr, "atr_pct": atr / last * 100,
        "rvol": rvol, "vol30": vol30, "dist_ema200_pct": (last / ema[200] - 1) * 100,
        "dist_52w_high_pct": (1 - last / hi52) * 100, "high_52w": hi52, "macd_above_signal": bool(macd.iloc[-1] > sig.iloc[-1]),
        "obv_rising": bool(obv.iloc[-1] > _ema(obv, 20).iloc[-1] and obv.iloc[-1] > obv.iloc[-11]),
        "xo_bull_approx": ema[12] > ema[25], "higher_high": hh, "higher_low": hl, "last_higher_high": last_hh,
        **cdl, "day_high": float(high.iloc[-1]), "day_low": float(low.iloc[-1]),
        "history_ok": len(df) >= 220,   # EMA 200 braucht Vorlauf
    }
    mc = market_cap
    crit = {
        "S01": {
            "RSI zuletzt < 35": t["rsi_min5"] < 35,
            "Umkehrkerze (Hammer/Engulfing)": t["hammer"] or t["bull_engulfing"],
        },
        "S02": {
            "Kurs > EMA 200": last > ema[200],
            "max. 5 % über EMA 200": 0 <= t["dist_ema200_pct"] <= 5,
            "Kurs < EMA 50": last < ema[50],
            "RSI 45–62": 45 <= t["rsi14"] <= 62,
            "RelVol > 0,8": (rvol or 0) > 0.8,
            "EMA 20 > SMA 50": ema[20] > sma50,
            "Marktkap. > 1 Mrd.": mc is None or mc > 1e9,
            "Volumen 30T > 1 Mio.": vol30 > 1e6,
            "Kurs > 10": last > 10,
            "Tag positiv": chg > 0,
        },
        "S03": {
            "0–5 % unter 52W-Hoch": 0 <= t["dist_52w_high_pct"] <= 5,
            "MACD > Signal": t["macd_above_signal"],
            "Volumen über Schnitt": (rvol or 0) > 1.0,
        },
        "S04": {
            "Higher High": hh, "Higher Low": hl, "OBV steigend": t["obv_rising"],
            "Trend-Signal (EMA12>EMA25)": t["xo_bull_approx"], "> 5 % unter 52W-Hoch": t["dist_52w_high_pct"] > 5,
        },
    }
    hits = [k for k, c in crit.items() if all(c.values())]
    flt = {
        "Tag grün": chg > 0,
        f"RelVol ≥ {FILTER['rvol_min']}": (rvol or 0) >= FILTER["rvol_min"],
        f"RSI ≤ {FILTER['rsi_max']}": t["rsi14"] <= FILTER["rsi_max"],
        f"ATR% {FILTER['atr_pct_min']}–{FILTER['atr_pct_max']}": FILTER["atr_pct_min"] <= t["atr_pct"] <= FILTER["atr_pct_max"],
        "über EMA 200": last > ema[200],
    }
    # Einstiegsplan (nächster Handelstag): Auslöser = heutiges Hoch (S04: letztes Higher High)
    trigger = last_hh if ("S04" in hits and last_hh) else t["day_high"]
    entry_max = trigger * (1 + ENTRY["max_above_trigger_pct"] / 100)
    stop = trigger - ENTRY["stop_atr"] * atr
    risk_ps = trigger - stop
    plan = {"trigger": trigger, "entry_max": entry_max, "stop": stop, "risk_per_share": risk_ps,
            "target_1": trigger + ENTRY["rrr"] * risk_ps, "trigger_basis": "letztes Higher High" if trigger != t["day_high"] else "Tageshoch (Vortageshoch für morgen)"}
    clean = lambda d: {k: (clean_number(v) if isinstance(v, (float, np.floating)) else v) for k, v in d.items()}  # noqa: E731
    return {"tech": clean(t), "criteria": crit, "hits": hits, "near": {k: sum(c.values()) / len(c) for k, c in crit.items()},
            "filter": flt, "filter_pass": all(flt.values()), "plan": clean(plan)}
