"""Download the community ad/tracker lists into blocklists/downloaded and the
malware / phishing / cryptominer lists into blocklists/downloaded/security.

Usage:  python update_blocklists.py          (from source)
        PRISM --update-blocklists           (built app; lists go to the data folder)
PRISM picks the files up on its next start.
"""

from __future__ import annotations

import sys
import urllib.request

from paths import SOURCE_DIR, user_blocklists_dir

# From source: blocklists/downloaded. Built app (PRISM --update-blocklists): the per-user data folder.
DEST = user_blocklists_dir() or SOURCE_DIR / "blocklists" / "downloaded"
SECURITY_DEST = DEST / "security"

LISTS = {
    # Unified hosts: adware + malware (StevenBlack)
    "stevenblack-hosts.txt": "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
    # AdGuard DNS filter: ads + trackers in ||domain^ form
    "adguard-dns.txt": "https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt",
}

# Network protection: pages on these domains get a warning page instead.
SECURITY_LISTS = {
    # abuse.ch URLhaus malware domains, as a hosts file (malware-filter project)
    "urlhaus-malware.txt": "https://malware-filter.gitlab.io/malware-filter/urlhaus-filter-hosts.txt",
    # Phishing Army: phishing domains (extended list)
    "phishing-army.txt": "https://phishing.army/download/phishing_army_blocklist_extended.txt",
    # NoCoin: in-browser cryptominers
    "nocoin-miners.txt": "https://raw.githubusercontent.com/hoshsadiq/adblock-nocoin-list/master/hosts.txt",
}


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    SECURITY_DEST.mkdir(parents=True, exist_ok=True)
    failed = 0
    jobs = [(DEST, n, u) for n, u in LISTS.items()] + [(SECURITY_DEST, n, u) for n, u in SECURITY_LISTS.items()]
    for folder, name, url in jobs:
        print(f"> fetching {name} ...", end=" ", flush=True)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "prism-blocklist-updater"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            (folder / name).write_bytes(data)
            print(f"ok ({len(data) // 1024} KB)")
        except Exception as exc:  # noqa: BLE001 - report and continue
            failed += 1
            print(f"FAILED: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
