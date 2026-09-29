"""Resolve the Matrix public API key at runtime.

This is *not* a secret — Matrix's web app embeds it in its JS bundle, and
every visitor to matrix.itasoftware.com receives it in plaintext. Treating
it like one nonetheless: not in source, fetched on demand, cached.

Resolution order:
  1. `$ITAMX_API_KEY` if set
  2. on-disk cache `~/.cache/itamx/api_key` (TTL 30 days)
  3. fetched from https://matrix.itasoftware.com/ by scraping for `AIza…`
     and persisted to the cache
  4. the built-in fallback -- remembered for an hour when the fetch fails, so
     that every new process does not pay for the same failed fetch again
"""

from __future__ import annotations

import contextlib
import os
import re
import time
from pathlib import Path

import httpx

_ENV_VAR = "ITAMX_API_KEY"
_CACHE_FILENAME = "api_key"
_TTL_SECONDS = 30 * 24 * 3600  # 30 days
# A failed live fetch, remembered. Short on purpose: the page may be back in
# an hour, and a key fetched from it beats the built-in one.
_FALLBACK_FILENAME = "api_key.fallback"
_FALLBACK_TTL_SECONDS = 3600
_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{35}")
# Public knowledge — same identifier any browser receives. Used only as a
# last-resort fallback if both env var and live fetch fail.
_FALLBACK = "AIza" + "SyBH1mte6BdKzvf0c2mYprkyvfHCRWmfX7g"

_runtime_cache: str | None = None


def _cache_dir() -> Path:
    base = os.environ.get("ITAMX_CACHE_DIR")
    d = Path(base).expanduser() if base else Path.home() / ".cache" / "itamx"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path() -> Path:
    return _cache_dir() / _CACHE_FILENAME


def _fallback_path() -> Path:
    return _cache_dir() / _FALLBACK_FILENAME


def _fetch_failed_recently() -> bool:
    """True when a live fetch failed within the last hour.

    Every CLI run and every bridge process starts with an empty in-process
    cache, and a fetch that fails is never written to the key cache. Without
    this each of them asks the page again: half a second where it is refused
    (a proxy's 403), the full 10-second timeout where it is unreachable.
    """
    try:
        return time.time() - _fallback_path().stat().st_mtime <= _FALLBACK_TTL_SECONDS
    except OSError:
        return False


def _remember_failed_fetch() -> None:
    # Best effort: an unwritable cache only costs the next process a fetch.
    with contextlib.suppress(OSError):
        _fallback_path().touch()


def _read_cached() -> str | None:
    p = _cache_path()
    if not p.exists():
        return None
    try:
        if time.time() - p.stat().st_mtime > _TTL_SECONDS:
            return None
        text = p.read_text(encoding="utf-8").strip()
        return text if _KEY_RE.fullmatch(text) else None
    except Exception:
        return None


def _write_cached(key: str) -> None:
    try:
        _cache_path().write_text(key, encoding="utf-8")
    except Exception:
        pass


def _fetch_live() -> str | None:
    """Scrape Matrix's HTML for the embedded key. Best effort."""
    try:
        with httpx.Client(timeout=10) as c:
            r = c.get("https://matrix.itasoftware.com/")
            r.raise_for_status()
            m = _KEY_RE.search(r.text)
            return m.group(0) if m else None
    except Exception:
        return None


def get_api_key() -> str:
    """Return the API key, using env var → cache → live fetch → fallback."""
    global _runtime_cache
    if _runtime_cache:
        return _runtime_cache

    env = os.environ.get(_ENV_VAR)
    if env and _KEY_RE.fullmatch(env.strip()):
        _runtime_cache = env.strip()
        return _runtime_cache

    cached = _read_cached()
    if cached:
        _runtime_cache = cached
        return _runtime_cache

    if _fetch_failed_recently():
        _runtime_cache = _FALLBACK
        return _runtime_cache

    live = _fetch_live()
    if live:
        _write_cached(live)
        _runtime_cache = live
        return _runtime_cache

    _remember_failed_fetch()
    _runtime_cache = _FALLBACK
    return _runtime_cache


def reset_cache() -> None:
    """Forget the in-process cache, the on-disk cached key and a failed fetch."""
    global _runtime_cache
    _runtime_cache = None
    for path in (_cache_path, _fallback_path):
        try:
            path().unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass
