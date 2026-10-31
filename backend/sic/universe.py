"""Aktienuniversum (Lastenheft Kap. 3).

- Laedt Nasdaq 100, S&P 500, Russell 2000 und DAX 40 aus kostenlosen Quellen
- Plausibilitätsprüfung je Index; bei Fehlschlag bleibt der letzte gültige Stand
- Dedupliziert über das Yahoo-Symbol, speichert alle Indexzugehörigkeiten
- Austrittsregeln 3.4: Index-Austritt beendet nur die Zugehörigkeit; Universumsaustritt
  erst, wenn keine Zielindex-Zugehörigkeit mehr besteht oder ein Ausschlussgrund vorliegt
- Ausgeschiedene Titel werden archiviert, nie geloescht
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable

import pandas as pd

from . import config
from .util import http_get, iso, read_json, utcnow, write_json_atomic

log = logging.getLogger("sic.universe")
STATE_FILE = config.STATE_DIR / "universe.json"

EXCLUSION_REASONS = {"delisted", "not_tradable", "acquired", "dissolved", "ambiguous"}


@dataclass
class Member:
    symbol: str          # Yahoo-Symbol = eindeutige Kennung
    name: str
    sector: str | None = None


# ------------------------------------------------------------ Abruf -------
def _yahoo_symbol(raw: str, suffix: str) -> str:
    s = str(raw).strip().upper().replace(" ", "")
    if suffix and s.endswith(suffix.upper()):
        return s
    s = s.replace(".", "-") if not suffix else s.split(".")[0]
    return f"{s}{suffix}"


def _norm_col(c) -> str:
    """Spaltenname normalisieren: MultiIndex -> letzte Ebene, Fussnoten [14] entfernen, klein."""
    if isinstance(c, tuple):
        c = c[-1]
    return re.sub(r"\[[^\]]*\]", "", str(c)).strip().lower()


def _pick_table(tables: list[pd.DataFrame], symbol_cols: tuple[str, ...], min_rows: int) -> tuple[pd.DataFrame, object]:
    wanted = [x.lower() for x in symbol_cols]
    seen = []
    for t in tables:
        cols = {_norm_col(c): c for c in t.columns}
        seen.append(f"{len(t)} Zeilen: {list(cols)[:6]}")
        for sc in wanted:
            if sc in cols and len(t) >= min_rows:
                return t, cols[sc]
    raise ValueError(f"keine passende Tabelle gefunden (Kandidaten: {'; '.join(s for s in seen if not s.startswith('0 '))[:240]})")


def _first_col(t: pd.DataFrame, names: tuple[str, ...]):
    wanted = [n.lower() for n in names]
    cols = {_norm_col(c): c for c in t.columns}
    for n in wanted:
        if n in cols:
            return cols[n]
    return None


def fetch_wikipedia(code: str) -> list[Member]:
    cfg = config.INDEXES[code]
    html = http_get(cfg["source"]).text
    tables = pd.read_html(io.StringIO(html))
    t, sym_col = _pick_table(tables, ("Ticker", "Symbol", "Ticker symbol"), int(cfg["min_members"] * 0.9))
    name_col = _first_col(t, ("Company", "Security", "Name"))
    sector_col = _first_col(t, ("GICS Sector", "ICB Industry", "Prime Standard Sector", "Sector", "Industry"))
    out = []
    for _, row in t.iterrows():
        sym = row[sym_col]
        if not isinstance(sym, str) or not sym.strip():
            continue
        out.append(Member(
            symbol=_yahoo_symbol(sym, cfg["suffix"]),
            name=str(row[name_col]) if name_col is not None else sym,
            sector=str(row[sector_col]) if sector_col is not None and pd.notna(row[sector_col]) else None,
        ))
    return out


def fetch_ishares_csv(code: str) -> list[Member]:
    cfg = config.INDEXES[code]
    # Oeffentliche Download-Datei; iShares liefert sie nur mit browserueblichen Headern aus
    text = http_get(cfg["source"], headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) StockIntelligenceCockpit/1.1",
        "Accept": "text/csv,application/octet-stream,*/*"}).text.lstrip("\ufeff")
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.replace('"', "").strip().lower().startswith("ticker,")), None)
    if start is None:
        raise ValueError(f"Kopfzeile 'Ticker' nicht gefunden; Antwortbeginn: {text[:120]!r}")
    reader = csv.DictReader(lines[start:])
    out = []
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items() if k}
        if row.get("Asset Class") != "Equity":
            continue
        sym = row.get("Ticker", "")
        if not sym or not re.fullmatch(r"[A-Z0-9.\-]+", sym):
            continue
        out.append(Member(_yahoo_symbol(sym, ""), (row.get("Name") or sym).title(), row.get("Sector") or None))
    return out


FETCHERS: dict[str, Callable[[str], list[Member]]] = {"wikipedia": fetch_wikipedia, "ishares_csv": fetch_ishares_csv}


# --------------------------------------------------------- Plausibilität --
def plausible(code: str, members: list[Member]) -> tuple[bool, str]:
    cfg = config.INDEXES[code]
    n = len({m.symbol for m in members})
    if n < cfg["min_members"] or n > cfg["max_members"]:
        return False, f"{n} Mitglieder außerhalb [{cfg['min_members']}, {cfg['max_members']}]"
    if len(members) != n:
        dup = len(members) - n
        if dup > max(5, n * 0.02):  # Mehrfachklassen (z. B. GOOG/GOOGL) sind normal
            return False, f"{dup} doppelte Symbole"
    return True, "ok"


# ------------------------------------------------------------ Zustand -----
def load_state() -> dict:
    return read_json(STATE_FILE, {"securities": {}, "indexes": {}, "history": []})


def _open_memberships(sec: dict) -> list[dict]:
    return [m for m in sec["memberships"] if m.get("until") is None]


def _load_csv(name: str) -> list[dict]:
    p = config.IMPORT_DIR / name
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if not (r.get(next(iter(r), "")) or "").startswith("#")]


def apply_index(state: dict, code: str, members: list[Member], today: date) -> dict:
    """Wendet einen plausiblen Indexstand an. Gibt Änderungsstatistik zurück."""
    today_s = today.isoformat()
    secs = state["securities"]
    current = {m.symbol: m for m in members}
    added, removed = [], []

    for sym, m in current.items():
        sec = secs.get(sym)
        if sec is None:
            sec = secs[sym] = {
                "symbol": sym, "name": m.name, "sector": m.sector,
                "region": config.INDEXES[code]["region"], "currency": config.INDEXES[code]["currency"],
                "memberships": [], "status": "active", "status_reason": None,
                "first_seen": today_s, "archived_at": None,
            }
        sec["name"] = m.name or sec["name"]
        sec["sector"] = m.sector or sec.get("sector")
        if not any(ms["index"] == code and ms.get("until") is None for ms in sec["memberships"]):
            sec["memberships"].append({
                "index": code, "since": today_s, "until": None,
                # Wikipedia/iShares liefern kein offizielles Wirksamkeitsdatum -> Erkennungsdatum
                "date_basis": "detected" if state["indexes"].get(code) else "initial_load",
            })
            added.append(sym)

    for sym, sec in secs.items():
        for ms in sec["memberships"]:
            if ms["index"] == code and ms.get("until") is None and sym not in current:
                ms["until"] = today_s
                ms["exit_basis"] = "detected"
                removed.append(sym)

    cfg = config.INDEXES[code]
    state["indexes"][code] = {
        "code": code, "name": cfg["name"], "source": cfg["source"], "checked_at": iso(utcnow()),
        "members": len(current), "status": "ok", "message": None, "limitation": cfg.get("limitation"),
    }
    return {"added": added, "removed": removed}


def apply_scheduled_changes(state: dict, today: date) -> list[dict]:
    """index_changes.csv: offiziell angekündigte Änderungen. Vor Wirksamkeit 'bevorstehend',
    ab Wirksamkeitsdatum werden sie angewendet."""
    upcoming = []
    for r in _load_csv("index_changes.csv"):
        code, sym, action = r["index"].strip(), r["symbol"].strip().upper(), r["action"].strip().lower()
        eff = date.fromisoformat(r["effective_date"].strip())
        entry = {"index": code, "symbol": sym, "action": action, "effective_date": eff.isoformat(),
                 "source": r.get("source", "").strip(), "name": r.get("name", "").strip()}
        if eff > today:
            upcoming.append(entry)
            continue
        sec = state["securities"].get(sym)
        if action == "add":
            if sec is None:
                sec = state["securities"][sym] = {
                    "symbol": sym, "name": entry["name"] or sym, "sector": None,
                    "region": config.INDEXES[code]["region"], "currency": config.INDEXES[code]["currency"],
                    "memberships": [], "status": "active", "status_reason": None,
                    "first_seen": eff.isoformat(), "archived_at": None}
            if not any(m["index"] == code and m.get("until") is None for m in sec["memberships"]):
                sec["memberships"].append({"index": code, "since": eff.isoformat(), "until": None, "date_basis": "official"})
        elif action == "remove" and sec:
            for m in sec["memberships"]:
                if m["index"] == code and m.get("until") is None:
                    m["until"], m["exit_basis"] = eff.isoformat(), "official"
    return upcoming


def resolve_status(state: dict, today: date) -> None:
    """Regel 3.4: aktiv, solange mind. eine Zielindex-Zugehörigkeit besteht und kein Ausschlussgrund."""
    exclusions = {r["symbol"].strip().upper(): r for r in _load_csv("exclusions.csv")}
    for sym, sec in state["securities"].items():
        excl = exclusions.get(sym)
        if excl and excl.get("reason", "").strip() in EXCLUSION_REASONS:
            new, reason = "archived", excl["reason"].strip()
        elif _open_memberships(sec):
            new, reason = "active", None
        else:
            new, reason = "archived", "no_target_index"
        if sec["status"] != new:
            state["history"].append({"date": today.isoformat(), "symbol": sym, "from": sec["status"], "to": new, "reason": reason})
        sec["status"], sec["status_reason"] = new, reason
        sec["archived_at"] = (sec.get("archived_at") or today.isoformat()) if new == "archived" else None


def build_universe(today: date | None = None, fetch: bool = True,
                   overrides: dict[str, list[Member]] | None = None) -> dict:
    """Baut/aktualisiert das Universum. `overrides` erlaubt Tests ohne Netzwerk."""
    today = today or utcnow().date()
    state = load_state()
    report = {"indexes": {}, "upcoming": []}
    for code, cfg in config.INDEXES.items():
        try:
            if overrides and code in overrides:
                members = overrides[code]
            elif fetch:
                members = FETCHERS[cfg["kind"]](code)
            else:
                continue
            ok, msg = plausible(code, members)
            if not ok:
                raise ValueError(f"Plausibilitätsprüfung fehlgeschlagen: {msg}")
            report["indexes"][code] = apply_index(state, code, members, today)
        except Exception as exc:  # gültige Liste wird NICHT ueberschrieben
            exc = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            log.error("Index %s nicht aktualisiert: %s", code, exc)
            prev = state["indexes"].get(code, {"code": code, "name": cfg["name"], "source": cfg["source"], "members": 0})
            prev.update({"status": "error", "message": str(exc)[:300], "last_attempt": iso(utcnow())})
            state["indexes"][code] = prev
            report["indexes"][code] = {"error": str(exc)[:300]}
    report["upcoming"] = apply_scheduled_changes(state, today)
    resolve_status(state, today)
    state["history"] = state["history"][-5000:]
    state["upcoming_changes"] = report["upcoming"]
    state["built_at"] = iso(utcnow())
    write_json_atomic(STATE_FILE, state)
    return state


def active_symbols(state: dict) -> list[str]:
    return sorted(s for s, sec in state["securities"].items() if sec["status"] == "active")


def index_positions(state: dict) -> int:
    return sum(len(_open_memberships(sec)) for sec in state["securities"].values())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    st = build_universe()
    print(f"aktiv: {len(active_symbols(st))}, Indexpositionen: {index_positions(st)}")
