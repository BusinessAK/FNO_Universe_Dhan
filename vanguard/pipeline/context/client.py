"""
NseClient (C1) — the one NSE HTTP client for the context layer.

Factored from poll_eod.py's proven pattern: bootstrap Akamai cookies by
visiting a real report page, then fetch archive CSVs with the same session.
The archive hosts 503 without the cookie dance (verified 2026-07-19).
Retries with exponential backoff + jitter; one client instance is shared
across all dataset fetchers in a run.
"""
from __future__ import annotations

import random
import time

import requests

BOOTSTRAP_URL = "https://www.nseindia.com/all-reports-derivatives"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


class FetchError(RuntimeError):
    """Terminal fetch failure after retries (or a definitive 404)."""

    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


class NseClient:
    def __init__(self, pace_secs: float = 2.0, retries: int = 3, timeout: float = 25.0):
        self.pace = pace_secs
        self.retries = retries
        self.timeout = timeout
        self._s: requests.Session | None = None
        self._last_req = 0.0

    def _session(self) -> requests.Session:
        if self._s is None:
            self._s = requests.Session()
            self._s.headers.update(HEADERS)
            try:
                self._s.get(BOOTSTRAP_URL, timeout=self.timeout)
            except requests.RequestException:
                pass                        # cookies help but their absence is not fatal
        return self._s

    def _throttle(self):
        wait = self.pace - (time.time() - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.time()

    def get_bytes(self, url: str) -> bytes:
        """Paced GET with backoff. 404 raises immediately (file not published
        — a holiday or a not-yet day, retrying won't help); other failures
        retry, re-bootstrapping cookies on 401/403/503."""
        last: Exception | None = None
        for attempt in range(self.retries):
            self._throttle()
            try:
                r = self._session().get(url, timeout=self.timeout)
                if r.status_code == 200:
                    return r.content
                if r.status_code == 404:
                    raise FetchError(f"404 not published: {url}", status=404)
                last = FetchError(f"HTTP {r.status_code}: {url}", status=r.status_code)
                if r.status_code in (401, 403, 503):
                    self._s = None          # cookie expiry — re-bootstrap next attempt
            except FetchError:
                raise
            except requests.RequestException as e:
                last = e
            time.sleep((2 ** attempt) + random.random())
        raise FetchError(f"failed after {self.retries} attempts: {url} ({last})",
                         status=getattr(last, "status", None))
