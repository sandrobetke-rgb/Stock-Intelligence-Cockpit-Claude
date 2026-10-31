"""Maschinelle Übersetzung Englisch -> Deutsch (kostenlos, lokal im Pipeline-Lauf).

Nutzt das freie Argos-Translate-Modell en->de direkt über CTranslate2 + SentencePiece
(ohne PyTorch). Kein Konto, kein API-Schlüssel. Das Modell wird einmalig geladen und im
Cache-Ordner gehalten; bereits übersetzte Texte kommen aus translations.json.

Übersetzungen ergänzen das Original, ersetzen es nie: Bewertung, Zuordnung, Wirkungsrichtung
und Fact-Checking arbeiten weiterhin auf dem Originaltext.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import zipfile
from pathlib import Path

from . import config
from .util import http_get, read_json, write_json_atomic

log = logging.getLogger("sic.translate")

MODEL_INDEX = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
MAX_NEW_PER_RUN = 5000
CACHE_MAX = 30000

_EN = set("the a an and of to in for on with at by from is are was were be been has have will its it this that "
          "says said after over into amid as than more new up down shares stock stocks rate rates market".split())
_DE = set("der die das und des den dem ein eine ist sind wird wurde mit für auf von zu im nach bei".split())


def _cache_file() -> Path:
    return config.STATE_DIR / "translations.json"


def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def looks_english(text: str) -> bool:
    words = re.findall(r"[a-zA-ZäöüÄÖÜß]+", (text or "").lower())
    if len(words) < 3 or re.search(r"[äöüß]", text or ""):
        return False
    en = sum(w in _EN for w in words)
    de = sum(w in _DE for w in words)
    return en >= 1 and en > de


# ------------------------------------------------------------------ Modell --
def _model_dir() -> Path:
    return config.CACHE_DIR / "argos-en-de"


def ensure_model() -> Path:
    """Lädt das Argos-Paket en->de (ZIP) einmalig und entpackt es in den Cache."""
    target = _model_dir()
    if (target / "ready").exists():
        return target
    idx = http_get(MODEL_INDEX).json()
    pkg = next(p for p in idx if p.get("from_code") == "en" and p.get("to_code") == "de")
    data = http_get(pkg["links"][0]).content
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(target)
    (target / "ready").write_text(pkg.get("package_version", "?"))
    log.info("Übersetzungsmodell en->de %s geladen", pkg.get("package_version"))
    return target


def _find_parts(root: Path) -> tuple[Path, Path]:
    model = next(p.parent for p in root.rglob("model.bin"))
    sps = sorted(root.rglob("*.model"), key=lambda p: p.name != "sentencepiece.model")
    sp = sps[0]
    return model, sp


class Translator:
    def __init__(self, root: Path):
        import ctranslate2
        import sentencepiece as spm

        model_path, sp_path = _find_parts(root)
        self.tr = ctranslate2.Translator(str(model_path), device="cpu", compute_type="int8", inter_threads=2)
        self.sp = spm.SentencePieceProcessor(model_file=str(sp_path))

    def __call__(self, texts: list[str], batch: int = 32) -> list[str]:
        out: list[str] = []
        for i in range(0, len(texts), batch):
            chunk = texts[i:i + batch]
            toks = [self.sp.encode(t, out_type=str) for t in chunk]
            res = self.tr.translate_batch(toks, beam_size=2, max_decoding_length=256)
            out.extend(self.sp.decode(r.hypotheses[0]).strip() for r in res)
        return out


# --------------------------------------------------------------- Anwendung --
def translate_items(groups: list[tuple[list[dict], list[str]]], translator=None) -> dict:
    """groups: (Objekte, Felder). Setzt <feld>_de für englische Texte. Gibt Statistik zurück."""
    cache: dict[str, str] = read_json(_cache_file(), {})
    todo: dict[str, str] = {}
    for items, fields in groups:
        for it in items:
            for f in fields:
                t = (it.get(f) or "").strip()
                if t and looks_english(t) and _key(t) not in cache:
                    todo[_key(t)] = t
    new = list(todo.items())[:MAX_NEW_PER_RUN]
    if new:
        translator = translator or Translator(ensure_model())
        for (k, _), de in zip(new, translator([t for _, t in new])):
            cache[k] = de
    used = set()
    applied = 0
    for items, fields in groups:
        for it in items:
            for f in fields:
                t = (it.get(f) or "").strip()
                k = _key(t) if t else None
                if k and k in cache:
                    it[f + "_de"] = cache[k]
                    used.add(k)
                    applied += 1
    if len(cache) > CACHE_MAX:  # nicht mehr benötigte Einträge zuerst verwerfen
        cache = {k: v for k, v in cache.items() if k in used} | dict(list(cache.items())[-CACHE_MAX // 2:])
    write_json_atomic(_cache_file(), cache)
    return {"new": len(new), "applied": applied, "pending": max(0, len(todo) - len(new))}
