"""Hilfsfunktionen: Zeit, HTTP mit Retry/Rate-Limit, atomares Schreiben, Fingerprints."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

from . import config

log = logging.getLogger("sic")


# ----------------------------------------------------------------- Zeit ----
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_dt(value: Any) -> tuple[datetime | None, bool]:
    """Parst einen Zeitstempel. Rückgabe: (datetime UTC, date_only).

    date_only=True kennzeichnet reine Datumsangaben (Unsicherheit, Lastenheft 6.2).
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None, False
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc), False
    s = str(value).strip()
    if not s:
        return None, False
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc), True
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc), False
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc), False
    except (TypeError, ValueError):
        return None, False


# ----------------------------------------------------------------- HTTP ----
class RateLimiter:
    def __init__(self, per_second: float):
        self.min_interval = 1.0 / per_second
        self._last = 0.0

    def wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": config.USER_AGENT, "Accept-Encoding": "gzip, deflate"})
    return _session


def http_get(url: str, *, limiter: RateLimiter | None = None, **kw) -> requests.Response:
    """GET mit Wiederholungsversuchen und exponentiellem Backoff."""
    last_exc: Exception | None = None
    for attempt in range(1, config.HTTP_RETRIES + 1):
        if limiter:
            limiter.wait()
        try:
            r = session().get(url, timeout=config.HTTP_TIMEOUT, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:  # noqa: PERF203
            last_exc = exc
            log.warning("GET %s fehlgeschlagen (Versuch %d/%d): %s", url, attempt, config.HTTP_RETRIES, exc)
            time.sleep(min(2 ** attempt, 15))
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------- Dateien/JSON ----
def write_json_atomic(path: Path, data: Any) -> None:
    """Schreibt erst in eine Temp-Datei und ersetzt dann – nie halbfertige Dateien."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1, default=_json_default)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return iso(o)
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(f"nicht serialisierbar: {type(o)}")


def clean_number(x: Any) -> float | None:
    """NaN/Inf/None -> None (= unknown). Nie stillschweigend 0."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


# ------------------------------------------------------ Text/Fingerprint ----
_STOP = set("a an the and or of to in on for with by at from is are was be as its it this that der die das und oder von zu im in auf mit für ist".split())


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> set[str]:
    return {t for t in normalize_text(s).split() if t not in _STOP and len(t) > 1}


def fingerprint(s: str) -> str:
    """Duplikat-Fingerprint: sortierte Inhaltswörter -> SHA1 (Lastenheft 5)."""
    return hashlib.sha1(" ".join(sorted(tokens(s))).encode()).hexdigest()[:16]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def stable_id(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def chunked(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def domain_of(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1).lower() if m else ""
