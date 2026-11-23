"""Windows DPAPI: encrypt small secrets (API keys, tokens) with the current
Windows user's key, so only that Windows account can read them back.

Windows only; callers check CAN_SAVE and otherwise keep secrets in memory.
"""

from __future__ import annotations

import sys

CAN_SAVE = sys.platform == "win32"


def dpapi(data: bytes, protect: bool, entropy: bytes) -> bytes:
    """Encrypt (protect=True) or decrypt with the current Windows user's DPAPI key."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b: bytes):
        buf = ctypes.create_string_buffer(b, len(b))
        return Blob(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    inp, _keep1 = blob(data)
    ent, _keep2 = blob(entropy)
    out = Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out)):
        raise OSError("Windows couldn't " + ("encrypt" if protect else "decrypt") + " the secret")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)
