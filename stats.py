"""PRISM statistics for the dashboard.

Totals are kept across restarts in stats.json (see storage.data_dir). Only
counters are saved, never browsing history: visited hosts stay in memory, and
only how many there were is written. The blocked-domains top list is saved
(tracker domains, trimmed to TOP_KEEP). Purge wipes everything, file included.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path

BUCKET_SECONDS = 15     # one chart bar = 15 s
BUCKETS = 40            # 40 bars = last 10 minutes
TOP_KEEP = 500          # blocked domains kept on disk
SAVE_EVERY = 30         # seconds between saves while browsing

COUNTERS = ("requests", "blocked", "stripped", "cookies_refused", "perms_denied",
            "pages", "https_pages", "searches", "fallbacks")


def base_domain(host: str) -> str:
    """ads.eu.doubleclick.net -> doubleclick.net (good enough for a top-list)."""
    labels = host.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in ("co", "com", "net", "org", "ac", "gov"):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


class SessionStats:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.session_started = time.time()
        self.reset()
        self.load()

    def reset(self) -> None:
        self.started = time.time()  # first record (all-time totals start here)
        self.requests = 0
        self.blocked = 0
        self.stripped = 0           # tracking params removed (navigations)
        self.cookies_refused = 0    # third-party cookies rejected
        self.perms_denied = 0       # camera / mic / location ... requests
        self.pages = 0              # main-frame navigations
        self.https_pages = 0
        self.searches = 0
        self.fallbacks = 0          # searches rerouted to the backup engine
        self.sites_before = 0       # sites visited in earlier sessions (count only)
        self.sites: set[str] = set()
        self.blocked_domains: Counter[str] = Counter()
        self.timeline: dict[int, list[int]] = {}   # bucket -> [requests, blocked]
        self._saved_key = None

    # --- persistence ------------------------------------------------------
    def load(self) -> None:
        if not self.path:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        try:
            for name in COUNTERS:
                setattr(self, name, int(data.get(name, 0)))
            self.started = float(data.get("started", self.started))
            self.sites_before = int(data.get("sites", 0))
            self.blocked_domains = Counter({str(k): int(v) for k, v in data.get("top", [])})
            oldest = int(time.time() // BUCKET_SECONDS) - BUCKETS
            self.timeline = {int(b): [int(r), int(k)] for b, r, k in data.get("timeline", []) if int(b) > oldest}
        except (TypeError, ValueError):
            self.reset()        # corrupt file: start over rather than crash
        self._saved_key = self._key()

    def _key(self) -> tuple:
        return tuple(getattr(self, n) for n in COUNTERS) + (len(self.sites), self.started)

    def save(self, force: bool = False) -> None:
        """Write totals to disk if anything changed since the last save."""
        if not self.path or (not force and self._key() == self._saved_key):
            return
        data = {name: getattr(self, name) for name in COUNTERS}
        data.update(started=self.started, sites=self.sites_before + len(self.sites),
                    top=self.blocked_domains.most_common(TOP_KEEP),
                    timeline=[[b, r, k] for b, (r, k) in sorted(self.timeline.items())])
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            return              # disk trouble must never break browsing
        self._saved_key = self._key()

    def wipe(self) -> None:
        """Purge: forget everything, on disk too."""
        self.reset()
        if self.path:
            try:
                self.path.unlink()
            except OSError:
                pass
        self._saved_key = self._key()

    def _bucket(self) -> list[int]:
        b = int(time.time() // BUCKET_SECONDS)
        slot = self.timeline.get(b)
        if slot is None:
            slot = self.timeline[b] = [0, 0]
            for old in [k for k in self.timeline if k < b - BUCKETS]:
                del self.timeline[old]
        return slot

    # --- events -----------------------------------------------------------
    def request(self) -> None:
        self.requests += 1
        self._bucket()[0] += 1

    def block(self, host: str, first_party: str = "") -> None:
        self.blocked += 1
        self._bucket()[1] += 1
        label = base_domain(host)
        if first_party and base_domain(first_party) == label:
            label = host    # a site's own tracker: show the exact host, not the site
        self.blocked_domains[label] += 1

    def page(self, host: str, https: bool, search: bool) -> None:
        self.pages += 1
        self.https_pages += https
        self.searches += search
        if host:
            self.sites.add(host)

    # --- snapshot for the dashboard ---------------------------------------
    def snapshot(self) -> dict:
        now_b = int(time.time() // BUCKET_SECONDS)
        timeline = [{"t": b * BUCKET_SECONDS * 1000,
                     "req": self.timeline.get(b, [0, 0])[0],
                     "blk": self.timeline.get(b, [0, 0])[1]}
                    for b in range(now_b - BUCKETS + 1, now_b + 1)]
        return {
            "started": int(self.session_started * 1000),   # uptime: this session
            "since": int(self.started * 1000),             # totals: since this date
            "requests": self.requests,
            "blocked": self.blocked,
            "stripped": self.stripped,
            "cookies": self.cookies_refused,
            "perms": self.perms_denied,
            "pages": self.pages,
            "httpsPages": self.https_pages,
            "searches": self.searches,
            "fallbacks": self.fallbacks,
            "sites": self.sites_before + len(self.sites),
            "top": self.blocked_domains.most_common(7),
            "timeline": timeline,
            "bucket": BUCKET_SECONDS,
        }
