"""JSON-Export (Lastenheft Kap. 14/15).

Alle Endpunkte werden zuerst in ein Staging-Verzeichnis geschrieben und validiert.
Nur wenn ALLE Dateien gültig sind, werden sie veröffentlicht – sonst bleibt der
letzte gültige Stand erhalten.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path

import jsonschema

from . import config
from .util import write_json_atomic

log = logging.getLogger("sic.export")

_meta = {"type": "object", "required": ["generated_at", "schema_version"]}


def _list_of(required: list[str]) -> dict:
    return {"type": "array", "items": {"type": "object", "required": required}}


SCHEMAS: dict[str, dict] = {
    "summary.json": {**_meta, "required": [*_meta["required"], "mode", "universe", "coverage", "sources", "errors"]},
    "stocks.json": {**_meta, "required": [*_meta["required"], "stocks"],
                    "properties": {"stocks": _list_of(["symbol", "name", "status", "indexes", "quality", "risk",
                                                       "market_intelligence", "political"])}},
    "intelligence.json": {**_meta, "required": [*_meta["required"], "signals", "radar"],
                          "properties": {"signals": _list_of(["id", "symbols", "title", "url", "source",
                                                              "published_at", "captured_at", "verification",
                                                              "independence", "fingerprint"])}},
    "politics.json": {**_meta, "required": [*_meta["required"], "events", "trades", "scores"]},
    "trump-mentions.json": {**_meta, "required": [*_meta["required"], "rule", "mentions"],
                            "properties": {"mentions": _list_of(["id", "quote", "source_url", "statement_at",
                                                                 "mention_type", "direction", "verification", "bonus"])}},
    "market-events.json": {**_meta, "required": [*_meta["required"], "current", "upcoming"],
                           "properties": {"current": _list_of(["id", "kind", "title", "time", "timezone", "url",
                                                               "status", "verification", "direction"]),
                                          "upcoming": _list_of(["id", "kind", "title", "time", "timezone", "url",
                                                                "status", "verification"])}},
    "social.json": {**_meta, "required": [*_meta["required"], "stocks"]},
    "fact-checks.json": {**_meta, "required": [*_meta["required"], "status_counts", "checks"]},
    "insider.json": {**_meta, "required": [*_meta["required"], "insiders", "institutions", "political_trades", "cluster_buys"]},
    "alerts.json": {**_meta, "required": [*_meta["required"], "watchlist", "history"]},
    "quality-map.json": {**_meta, "required": [*_meta["required"], "q"]},
    "confluence.json": {**_meta, "required": [*_meta["required"], "rows"]},
    "report.json": {**_meta, "required": [*_meta["required"], "report_date", "candidates", "earnings", "macro"]},
    "swing.json": {**_meta, "required": [*_meta["required"], "setups", "filter", "entry", "candidates"]},
    "superinvestors.json": {**_meta, "required": [*_meta["required"], "managers", "stocks"],
                            "properties": {"managers": _list_of(["cik", "manager", "fund", "report_date", "filing_url", "positions"]),
                                           "stocks": _list_of(["cusip", "issuer", "holders", "buyers", "sellers", "managers"])}},
}


OPTIONAL = {"alerts.json", "swing.json", "confluence.json", "report.json", "quality-map.json"}   # entstehen erst im Live-Lauf


def publish(payloads: dict[str, dict], company_details: dict[str, dict], out_dir: Path | None = None) -> dict:
    out_dir = out_dir or config.OUTPUT_DIR
    errors = []
    for name, schema in SCHEMAS.items():
        if name not in payloads:
            if name not in OPTIONAL:
                errors.append(f"{name}: fehlt")
            continue
        try:
            jsonschema.validate(json.loads(json.dumps(payloads[name], default=str)), schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"{name}: {exc.message} @ {list(exc.absolute_path)[:4]}")
    if errors:
        log.error("Validierung fehlgeschlagen – nichts veröffentlicht: %s", errors)
        return {"published": False, "errors": errors}

    out_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=out_dir.parent, prefix=".staging-"))
    try:
        for name, data in payloads.items():
            write_json_atomic(staging / name, data)
        cdir = staging / "company"
        for sym, data in company_details.items():
            write_json_atomic(cdir / f"{sym}.json", data)
        # Veröffentlichen: Dateien einzeln atomar ersetzen, Company-Ordner tauschen
        for f in staging.glob("*.json"):
            f.replace(out_dir / f.name)
        target = out_dir / "company"
        if target.exists():
            old = out_dir / ".company-old"
            shutil.rmtree(old, ignore_errors=True)
            target.rename(old)
            cdir.rename(target)
            shutil.rmtree(old, ignore_errors=True)
        elif cdir.exists():
            cdir.rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"published": True, "errors": [], "files": sorted(payloads), "company_files": len(company_details)}
