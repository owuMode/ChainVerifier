# security/secrets.py
"""
Secrets — Windows DPAPI wrapper for per-user secret storage (spec §9).

Design:
  * Uses CryptProtectData / CryptUnprotectData with CRYPTPROTECT_UI_FORBIDDEN.
  * Per-user scope: same Windows account can decrypt; other accounts cannot.
  * Storage layout: one file per secret under <AppData>/runtime/secrets/.
  * File contents are the raw DPAPI blob (no format headers, no plaintext).
  * Never falls back to plaintext. If DPAPI is unavailable, we raise.

Why DPAPI and not Credential Manager:
  * DPAPI is the primitive underneath Credential Manager.
  * Credential Manager adds a UI surface we don't need yet.
  * DPAPI is a single-file, single-call round-trip — easy to audit.
  * Migration to Credential Manager later is a drop-in replacement of
    the two read/write methods without touching callers.

Interface:
  Secrets.set(namespace, key, value)   -> None
  Secrets.get(namespace, key)          -> str | None
  Secrets.delete(namespace, key)       -> None
  Secrets.list(namespace)              -> list[str]
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import re
from pathlib import Path
from typing import Optional

from applog.logger import get_logger

log = get_logger("security.secrets")


# ----------------------------------------------------------------------
# DPAPI ctypes bindings
# ----------------------------------------------------------------------
class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wt.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(_DataBlob),   # pDataIn
    wt.LPCWSTR,                  # szDataDescr
    ctypes.POINTER(_DataBlob),   # pOptionalEntropy
    ctypes.c_void_p,             # pvReserved
    ctypes.c_void_p,             # pPromptStruct
    wt.DWORD,                    # dwFlags
    ctypes.POINTER(_DataBlob),   # pDataOut
]
_crypt32.CryptProtectData.restype = wt.BOOL

_crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(_DataBlob),   # pDataIn
    ctypes.POINTER(wt.LPWSTR),   # ppszDataDescr
    ctypes.POINTER(_DataBlob),   # pOptionalEntropy
    ctypes.c_void_p,             # pvReserved
    ctypes.c_void_p,             # pPromptStruct
    wt.DWORD,                    # dwFlags
    ctypes.POINTER(_DataBlob),   # pDataOut
]
_crypt32.CryptUnprotectData.restype = wt.BOOL

_kernel32.LocalFree.argtypes = [wt.HLOCAL]
_kernel32.LocalFree.restype = wt.HLOCAL

CRYPTPROTECT_UI_FORBIDDEN = 0x01


class SecretsError(Exception):
    """Raised on any DPAPI or storage failure."""


# ----------------------------------------------------------------------
# Blob helpers
# ----------------------------------------------------------------------
def _bytes_to_blob(data: bytes) -> _DataBlob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(
        cbData=len(data),
        pbData=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
    )


def _blob_to_bytes(blob: _DataBlob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if blob.pbData:
            _kernel32.LocalFree(ctypes.cast(blob.pbData, wt.HLOCAL))


def _dpapi_protect(plaintext: bytes) -> bytes:
    blob_in = _bytes_to_blob(plaintext)
    blob_out = _DataBlob()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise SecretsError(f"CryptProtectData failed: {ctypes.get_last_error()}")
    return _blob_to_bytes(blob_out)


def _dpapi_unprotect(ciphertext: bytes) -> bytes:
    blob_in = _bytes_to_blob(ciphertext)
    blob_out = _DataBlob()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise SecretsError(f"CryptUnprotectData failed: {ctypes.get_last_error()}")
    return _blob_to_bytes(blob_out)


# ----------------------------------------------------------------------
# Filename safety
# ----------------------------------------------------------------------
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize(name: str) -> str:
    """
    Namespace and key components must be filesystem-safe.
    We replace disallowed characters — callers should still pass clean names.
    """
    cleaned = _SAFE_RE.sub("_", name)
    if not cleaned:
        raise SecretsError("empty secret identifier after sanitization")
    return cleaned


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
class Secrets:
    """
    Per-user secret store, DPAPI-backed.

    Storage: <secrets_dir>/<namespace>/<key>.bin
    Each file contains the raw DPAPI blob of the UTF-8 value.
    """

    def __init__(self, secrets_dir: Path) -> None:
        self._root = secrets_dir
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------
    def set(self, namespace: str, key: str, value: str) -> None:
        ns = _sanitize(namespace)
        k = _sanitize(key)
        target = self._path(ns, k)

        try:
            blob = _dpapi_protect(value.encode("utf-8"))
        except SecretsError:
            raise
        except Exception as exc:
            raise SecretsError(f"failed to protect secret: {exc}") from exc

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, target)
        log.info("secret stored", extra={"namespace": ns, "key": k})

    def get(self, namespace: str, key: str) -> Optional[str]:
        ns = _sanitize(namespace)
        k = _sanitize(key)
        target = self._path(ns, k)

        if not target.exists():
            return None

        try:
            blob = target.read_bytes()
            plaintext = _dpapi_unprotect(blob)
        except SecretsError:
            raise
        except Exception as exc:
            raise SecretsError(f"failed to unprotect secret: {exc}") from exc

        return plaintext.decode("utf-8")

    def delete(self, namespace: str, key: str) -> None:
        ns = _sanitize(namespace)
        k = _sanitize(key)
        target = self._path(ns, k)
        if target.exists():
            target.unlink()
            log.info("secret deleted", extra={"namespace": ns, "key": k})

    def list(self, namespace: str) -> list[str]:
        ns = _sanitize(namespace)
        folder = self._root / ns
        if not folder.exists():
            return []
        return sorted(p.stem for p in folder.glob("*.bin"))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _path(self, namespace: str, key: str) -> Path:
        return self._root / namespace / f"{key}.bin"