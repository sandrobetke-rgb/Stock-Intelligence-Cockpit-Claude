"""Marktampel: Rückenwind oder Gegenwind für neue Long-Swing-Trades.

Kostenlose Daten (Yahoo Finance über yfinance, ohne Schlüssel):
- S&P 500 (^GSPC), Nasdaq 100 (^NDX), DAX (^GDAXI): Kurs über/unter EMA 200, EMA 50 steigend?
- VIX (^VIX): Angstbarometer – unter 20 ruhig, 20–30 nervös, über 30 Stress.
- Zinskurve 10 Jahre minus 3 Monate (^TNX − ^IRX): negativ = invertiert, historisch Rezessionsvorbote.
- Marktbreite aus dem eigenen Universum: Anteil der Aktien über EMA 200.

Jede Ampel liefert grün (2), gelb (1) oder rot (0). Gesamt: ≥ 75 % der Punkte grün, ≥ 45 % gelb, sonst rot.
Das ist eine Einordnung des Umfelds, keine Prognose und keine Handelsempfehlung.
"""
from __future__ import annotations

import logging

from . import config
from .util import iso, read_json, utcnow, write_json_atomic

log = logging.getLogger("sic.regime")
INDEXES = {"^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^GDAXI": "DAX"}
EXTRA = {"^VIX": "VIX", "^TNX": "US-Rendite 10 J.", "^IRX": "US-Rendite 3 M."}
LEVEL = {2: "green", 1: "yellow", 0: "red"}


def _path():
    return config.STATE_DIR / "regime.json"


def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def fetch() -> dict:
    import yfinance as yf

    out = {}
    data = yf.download(list(INDEXES) + list(EXTRA), period="1y", interval="1d", group_by="ticker",
                       auto_adjust=True, progress=False, threads=True)
    for t in list(INDEXES) + list(EXTRA):
        try:
            c = data[t]["Close"].dropna()
            if len(c) < 30:
                continue
            row = {"close": float(c.iloc[-1]), "date": c.index[-1].date().isoformat(),
                   "change_pct": float((c.iloc[-1] / c.iloc[-2] - 1) * 100)}
            if t in INDEXES and len(c) >= 200:
                e50, e200 = _ema(c, 50), _ema(c, 200)
                row.update({"ema50": float(e50.iloc[-1]), "ema200": float(e200.iloc[-1]),
                            "dist_ema200_pct": float((c.iloc[-1] / e200.iloc[-1] - 1) * 100),
                            "ema50_rising": bool(e50.iloc[-1] > e50.iloc[-6]),
                            "perf_20d_pct": float((c.iloc[-1] / c.iloc[-21] - 1) * 100)})
            out[t] = row
        except Exception as exc:  # noqa: BLE001
            log.warning("Marktampel %s: %s", t, exc)
    return out


def _index_light(r: dict) -> tuple[int, str]:
    if "ema200" not in r:
        return 1, "zu wenig Historie"
    above, rising = r["close"] > r["ema200"], r["ema50_rising"]
    if above and rising:
        return 2, f"über EMA 200 ({r['dist_ema200_pct']:+.1f} %), EMA 50 steigt"
    if above or rising:
        return 1, f"{'über' if above else 'unter'} EMA 200 ({r['dist_ema200_pct']:+.1f} %), EMA 50 {'steigt' if rising else 'fällt'}"
    return 0, f"unter EMA 200 ({r['dist_ema200_pct']:+.1f} %), EMA 50 fällt"


def evaluate(raw: dict, stocks: list[dict], now=None) -> dict:
    lights = []
    for t, name in INDEXES.items():
        if t in raw:
            lv, why = _index_light(raw[t])
            lights.append({"key": t, "name": name, "level": LEVEL[lv], "points": lv, "value": raw[t]["close"],
                           "date": raw[t]["date"], "text": why, "weight": 2 if t == "^GSPC" else 1})
    if "^VIX" in raw:
        v = raw["^VIX"]["close"]
        lv = 2 if v < 20 else 1 if v <= 30 else 0
        lights.append({"key": "^VIX", "name": "VIX (Angstbarometer)", "level": LEVEL[lv], "points": lv, "value": v,
                       "date": raw["^VIX"]["date"], "weight": 1,
                       "text": "ruhig (unter 20)" if lv == 2 else "nervös (20–30)" if lv == 1 else "Stress (über 30)"})
    if "^TNX" in raw and "^IRX" in raw:
        spread = raw["^TNX"]["close"] - raw["^IRX"]["close"]
        lv = 2 if spread > 0.25 else 1 if spread > -0.25 else 0
        lights.append({"key": "curve", "name": "Zinskurve 10 J. − 3 M.", "level": LEVEL[lv], "points": lv, "value": round(spread, 2),
                       "date": raw["^TNX"]["date"], "weight": 1,
                       "text": "normal (lange Zinsen höher)" if lv == 2 else "flach" if lv == 1 else "invertiert – historisch Rezessionsvorbote"})
    act = [s for s in stocks if s.get("status") == "active" and (s.get("swing") or {}).get("tech", {}).get("dist_ema200_pct") is not None]
    if len(act) > 200:
        share = 100 * sum(1 for s in act if s["swing"]["tech"]["dist_ema200_pct"] > 0) / len(act)
        lv = 2 if share >= 60 else 1 if share >= 40 else 0
        lights.append({"key": "breadth", "name": "Marktbreite (eigenes Universum)", "level": LEVEL[lv], "points": lv,
                       "value": round(share, 1), "date": None, "weight": 2,
                       "text": f"{share:.0f} % der Aktien über EMA 200" + (" – breiter Aufwärtstrend" if lv == 2 else " – gemischt" if lv == 1 else " – die Mehrheit fällt")})
    tot = sum(2 * x["weight"] for x in lights)
    got = sum(x["points"] * x["weight"] for x in lights)
    ratio = got / tot if tot else None
    overall = None if ratio is None else "green" if ratio >= 0.75 else "yellow" if ratio >= 0.45 else "red"
    label = {"green": "Rückenwind", "yellow": "Gemischt", "red": "Gegenwind", None: "unbekannt"}[overall]
    hint = {"green": "Umfeld spricht für Long-Swings: normale Positionsgröße.",
            "yellow": "Gemischtes Umfeld: nur die besten Setups, eher kleinere Positionen.",
            "red": "Gegenwind: neue Long-Trades nur sehr selektiv, kleinere Positionen oder pausieren.",
            None: "Keine Daten."}[overall]
    return {"generated_at": iso(now or utcnow()), "overall": overall, "label": label, "hint": hint,
            "score_pct": round(100 * ratio) if ratio is not None else None, "lights": lights}


def build(stocks: list[dict], fetch_new: bool, now=None) -> tuple[dict, dict | None]:
    raw, stat = read_json(_path(), {}), None
    if fetch_new:
        try:
            new = fetch()
            if new:
                raw = new
                write_json_atomic(_path(), raw)
            stat = {"source": "Marktampel (Yahoo Finance)", "status": "ok" if new else "error", "count": len(new)}
        except Exception as exc:  # noqa: BLE001
            stat = {"source": "Marktampel (Yahoo Finance)", "status": "error", "error": str(exc)[:200]}
    return evaluate(raw, stocks, now), stat
