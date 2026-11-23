"""PRISM local storage: settings, per-site rules and developer bookmarks.

Browsing data (history, cookies, cache) is never written to disk. What *is*
saved is only what the user explicitly configures:
  settings.json      permission defaults, per-site rules, DNS, custom blocks
  bookmarks.json     developer bookmarks (links, snippets, endpoints, notes)
  stats.json         dashboard counters (see stats.py; no visited sites)
  logins/<folder>/   cookies + site storage of containers set to "Remember logins"
  vault.prism        the encrypted password vault (see vault.py)
  design.json        Anthropic API key for the design review, DPAPI-encrypted (see designai.py)
All of it lives in %APPDATA%/Synterra/PRISM (or the platform equivalent).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from PyQt6.QtCore import QStandardPaths


def data_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    path = Path(base or Path.home() / ".prism")
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        # Saved logins, settings and the vault are nobody else's business:
        # keep the folder private to this user (Windows' %APPDATA% already is).
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def logins_dir() -> Path:
    """Disk profiles of containers with "Remember logins" on (one folder each)."""
    path = data_dir() / "logins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------------ settings

PERMISSION_TYPES = {
    # Qt PermissionType name -> (label, default policy)
    "MediaVideoCapture":         ("Camera", "ask"),
    "MediaAudioCapture":         ("Microphone", "ask"),
    "MediaAudioVideoCapture":    ("Camera + microphone", "ask"),
    "Geolocation":               ("Location", "ask"),
    "ClipboardReadWrite":        ("Clipboard", "ask"),
    "Notifications":             ("Notifications", "block"),
    "DesktopVideoCapture":       ("Screen sharing", "ask"),
    "DesktopAudioVideoCapture":  ("Screen + audio sharing", "ask"),
    "MouseLock":                 ("Pointer lock", "ask"),
    "LocalFontsAccess":          ("Local fonts (fingerprinting)", "block"),
}

# Providers must speak DoH over HTTP/1.1 (the resolver uses the standard
# library); Quad9 and Mullvad are HTTP/2-only and so not listed.
DNS_PROVIDERS = {
    "cloudflare": ("Cloudflare 1.1.1.1", "https://cloudflare-dns.com/dns-query"),
    "adguard":    ("AdGuard (blocks ads, trackers, malware)", "https://dns.adguard-dns.com/dns-query"),
    "google":     ("Google Public DNS", "https://dns.google/dns-query"),
}

DEFAULT_SETTINGS = {
    "permissionDefaults": {k: v[1] for k, v in PERMISSION_TYPES.items()},
    "sitePermissions": {},        # site -> {PermissionType: "allow"|"block"}
    "siteScripts": {},            # site -> {"js": bool, "thirdParty": "allow"|"block", "blockedHosts": [...]}
    "thirdPartyScriptsDefault": "allow",
    "dns": {"mode": "off", "provider": "cloudflare"},   # mode: off | secure | strict
    "protection": {"malware": True, "suspiciousScripts": True},
    "customBlocks": [],           # extra hosts the user never wants to reach
    "terminal": {"shell": "cmd", "cwd": ""},
    "rememberLogins": {},         # container id -> folder under logins/ (opt-in, standard containers only)
}


class Settings:
    def __init__(self) -> None:
        self.path = data_dir() / "settings.json"
        data = _read_json(self.path, {})
        self.data = json.loads(json.dumps(DEFAULT_SETTINGS))
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(self.data.get(key), dict):
                self.data[key].update(value)
            else:
                self.data[key] = value

    def __getitem__(self, key):
        return self.data[key]

    def save(self) -> None:
        _atomic_write(self.path, json.dumps(self.data, indent=2, sort_keys=True))

    # --- per-site script rules
    def scripts_for(self, site: str) -> dict:
        rule = self.data["siteScripts"].get(site, {})
        return {"js": rule.get("js", True),
                "thirdParty": rule.get("thirdParty", self.data["thirdPartyScriptsDefault"]),
                "blockedHosts": list(rule.get("blockedHosts", []))}

    def set_scripts(self, site: str, rule: dict) -> None:
        clean = {"js": bool(rule.get("js", True)),
                 "thirdParty": "block" if rule.get("thirdParty") == "block" else "allow",
                 "blockedHosts": sorted(set(rule.get("blockedHosts", [])))}
        default = {"js": True, "thirdParty": self.data["thirdPartyScriptsDefault"], "blockedHosts": []}
        if clean == default:
            self.data["siteScripts"].pop(site, None)
        else:
            self.data["siteScripts"][site] = clean
        self.save()

    # --- permissions
    def permission_policy(self, site: str, ptype: str) -> str:
        site_rule = self.data["sitePermissions"].get(site, {}).get(ptype)
        return site_rule or self.data["permissionDefaults"].get(ptype, "ask")

    def set_site_permission(self, site: str, ptype: str, policy: str | None) -> None:
        rules = self.data["sitePermissions"].setdefault(site, {})
        if policy in ("allow", "block"):
            rules[ptype] = policy
        else:
            rules.pop(ptype, None)
        if not rules:
            self.data["sitePermissions"].pop(site, None)
        self.save()


# ---------------------------------------------------------------- bookmarks

BOOKMARK_KINDS = ("link", "doc", "endpoint", "snippet", "note")


class DevBookmarks:
    def __init__(self) -> None:
        self.path = data_dir() / "bookmarks.json"
        self.items: list[dict] = _read_json(self.path, [])

    def save(self) -> None:
        _atomic_write(self.path, json.dumps(self.items, indent=2))

    def upsert(self, item: dict) -> dict:
        kind = item.get("kind") if item.get("kind") in BOOKMARK_KINDS else "link"
        clean = {
            "id": item.get("id") or uuid.uuid4().hex[:12],
            "kind": kind,
            "title": str(item.get("title", "")).strip()[:200] or "Untitled",
            "url": str(item.get("url", "")).strip()[:2000],
            "method": str(item.get("method", "GET")).upper()[:10],
            "content": str(item.get("content", ""))[:100_000],
            "lang": str(item.get("lang", "")).strip()[:30],
            "tags": [t.strip()[:30] for t in item.get("tags", []) if str(t).strip()][:12],
            "updated": int(time.time()),
        }
        for i, old in enumerate(self.items):
            if old["id"] == clean["id"]:
                clean["created"] = old.get("created", clean["updated"])
                self.items[i] = clean
                break
        else:
            clean["created"] = clean["updated"]
            self.items.insert(0, clean)
        self.save()
        return clean

    def delete(self, item_id: str) -> None:
        self.items = [i for i in self.items if i["id"] != item_id]
        self.save()
