"""PRISM edition: which features this copy of PRISM ships with.

The full edition has everything. The partner edition, for machines you hand
to someone else, has the browser, privacy and developer tools, but not the
features that hold secrets or run code on the machine:

  terminal   the shell command runner
  vault      the password vault

The edition comes from deployment.json next to prism.py, or next to the
PRISM executable in a built app (git-ignored, so each install has its own):

    {"edition": "partner"}

No file, or "edition": "employee", means the full browser. Partner copies
are made by dropping that file into the folder before handing it over.
Disabled features are not just hidden: their Python side is never created
and their panel actions are refused.
"""

from __future__ import annotations

import json
import sys

from paths import APP_DIR

DEPLOYMENT_FILE = APP_DIR / "deployment.json"   # next to prism.py, or next to the PRISM executable

EDITIONS = ("employee", "partner")
PARTNER_DISABLED = frozenset({"terminal", "vault"})

_DEFAULTS = {
    "edition": "employee",
    "updateCheck": True,                  # look for new PRISM / Qt WebEngine releases
    "updateRepo": "norik-jusufi/Prism",   # GitHub repo whose version.py is the latest release
    "updateBranch": "main",
}


def _load() -> dict:
    conf = dict(_DEFAULTS)
    try:
        data = json.loads(DEPLOYMENT_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return conf
    except (OSError, ValueError) as exc:
        # A broken file must not silently turn a partner copy into the full
        # browser: fail closed to the partner edition and say why.
        print(f"[prism] deployment.json unreadable ({exc}); running the partner edition", file=sys.stderr)
        conf["edition"] = "partner"
        return conf
    if isinstance(data, dict):
        conf.update({k: v for k, v in data.items() if k in _DEFAULTS})
    if conf["edition"] not in EDITIONS:
        print(f"[prism] unknown edition {conf['edition']!r} in deployment.json; running the partner edition",
              file=sys.stderr)
        conf["edition"] = "partner"
    return conf


DEPLOYMENT = _load()
EDITION: str = DEPLOYMENT["edition"]
DISABLED: frozenset[str] = PARTNER_DISABLED if EDITION == "partner" else frozenset()


def enabled(feature: str) -> bool:
    return feature not in DISABLED
