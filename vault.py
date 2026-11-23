"""PRISM local password vault.

One file (vault.prism) in the PRISM data folder:
    {"v": 1, "kdf": {"n","r","p","salt"}, "nonce": b64, "data": b64}
The key is derived from the master password with scrypt (N=2^17, r=8, p=1,
the OWASP recommendation; vaults made with older, weaker settings are
upgraded the next time they are unlocked) and the entries are sealed with
AES-256-GCM, so the file is unreadable and
tamper-evident without the master password. The master password itself is
never stored. Entries only exist decrypted in memory while the vault is
unlocked; it locks again after a period of inactivity.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import string
import time
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from storage import data_dir

KDF = {"n": 2 ** 17, "r": 8, "p": 1}
AUTO_LOCK_SECONDS = 5 * 60


class VaultError(Exception):
    pass


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(password.encode("utf-8"))


def generate_password(length: int = 20, symbols: bool = True) -> str:
    alphabet = string.ascii_letters + string.digits + ("!@#$%^&*-_=+?" if symbols else "")
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(max(8, min(128, length))))
        # at least one of each class, so it passes common site rules
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw)
                and (not symbols or any(not c.isalnum() for c in pw))):
            return pw


class Vault:
    def __init__(self) -> None:
        self.path = data_dir() / "vault.prism"
        self._key: bytes | None = None
        self._salt: bytes | None = None
        self._kdf: dict = dict(KDF)          # parameters self._key was derived with
        self.entries: list[dict] = []
        self.last_used = 0.0

    # --- state
    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def unlocked(self) -> bool:
        return self._key is not None

    def touch(self) -> None:
        self.last_used = time.time()

    def expired(self) -> bool:
        return self.unlocked and time.time() - self.last_used > AUTO_LOCK_SECONDS

    # --- lifecycle
    def create(self, password: str) -> None:
        if self.exists:
            raise VaultError("A vault already exists.")
        if len(password) < 10:
            raise VaultError("Use a master password of at least 10 characters.")
        self._rekey(password)
        self.entries = []
        self._write()
        self.touch()

    def unlock(self, password: str) -> None:
        try:
            blob = json.loads(self.path.read_text(encoding="utf-8"))
            kdf = {k: int(blob["kdf"][k]) for k in ("n", "r", "p")}
            salt = _unb64(blob["kdf"]["salt"])
            key = _derive(password, salt, **kdf)
            plain = AESGCM(key).decrypt(_unb64(blob["nonce"]), _unb64(blob["data"]), b"prism-vault-v1")
        except InvalidTag:
            raise VaultError("Wrong master password.") from None
        except (OSError, ValueError, KeyError) as exc:
            raise VaultError(f"Vault file is unreadable: {exc}") from None
        self._key, self._salt, self._kdf = key, salt, kdf
        self.entries = json.loads(plain.decode("utf-8"))
        if any(kdf[k] < KDF[k] for k in KDF):     # made with weaker settings: upgrade now
            self._rekey(password)
            self._write()
        self.touch()

    def lock(self) -> None:
        self._key = None
        self._salt = None
        self.entries = []

    def change_password(self, old: str, new: str) -> None:
        if len(new) < 10:
            raise VaultError("Use a master password of at least 10 characters.")
        self.unlock(old)
        self._rekey(new)
        self._write()

    def _rekey(self, password: str) -> None:
        """New salt and key from password, with the current KDF settings."""
        self._salt = os.urandom(16)
        self._kdf = dict(KDF)
        self._key = _derive(password, self._salt, **self._kdf)

    def _write(self) -> None:
        if self._key is None or self._salt is None:
            raise VaultError("Vault is locked.")
        nonce = os.urandom(12)
        sealed = AESGCM(self._key).encrypt(nonce, json.dumps(self.entries).encode("utf-8"), b"prism-vault-v1")
        # Always the parameters the key was really derived with.
        blob = {"v": 1, "kdf": {**self._kdf, "salt": _b64(self._salt)}, "nonce": _b64(nonce), "data": _b64(sealed)}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(blob), encoding="utf-8")
        os.replace(tmp, self.path)

    # --- entries
    def _need(self) -> None:
        if not self.unlocked:
            raise VaultError("Vault is locked.")
        self.touch()

    def upsert(self, entry: dict) -> dict:
        self._need()
        clean = {
            "id": entry.get("id") or uuid.uuid4().hex[:12],
            "site": str(entry.get("site", "")).strip().lower()[:200],
            "username": str(entry.get("username", ""))[:300],
            "password": str(entry.get("password", ""))[:500],
            "notes": str(entry.get("notes", ""))[:4000],
            "updated": int(time.time()),
        }
        if not clean["site"]:
            raise VaultError("Enter the site this login is for.")
        for i, old in enumerate(self.entries):
            if old["id"] == clean["id"]:
                self.entries[i] = clean
                break
        else:
            self.entries.append(clean)
        self._write()
        return clean

    def delete(self, entry_id: str) -> None:
        self._need()
        self.entries = [e for e in self.entries if e["id"] != entry_id]
        self._write()

    def get(self, entry_id: str) -> dict | None:
        self._need()
        return next((e for e in self.entries if e["id"] == entry_id), None)

    def for_site(self, host: str) -> list[dict]:
        self._need()
        host = host.lower()
        return [e for e in self.entries
                if host == e["site"] or host.endswith("." + e["site"]) or e["site"].endswith("." + host)]

    def listing(self) -> list[dict]:
        """Entries without the passwords: safe to send to the UI."""
        self._need()
        return [{k: v for k, v in e.items() if k != "password"} | {"hasPassword": bool(e["password"])}
                for e in sorted(self.entries, key=lambda e: (e["site"], e["username"]))]
