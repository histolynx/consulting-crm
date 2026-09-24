"""Credential storage for the Gmail login, entered in the GUI (never written to a plaintext file).

  remember=True  -> Windows Credential Manager (DPAPI-encrypted, bound to your Windows login;
                    visible under Control Panel → Credential Manager → Windows Credentials → "HIVE:gmail")
  remember=False -> this server process's memory only (gone on restart; background scheduled sync can't use it)

Stdlib only: talks to advapi32 Cred* APIs through ctypes.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

TARGET = "HIVE:gmail"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168

_session: dict[str, tuple[str, str]] = {}


class CredError(RuntimeError):
    pass


if os.name == "nt":
    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class _CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR), ("LastWritten", _FILETIME), ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_char)), ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
        ]

    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _adv.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    _adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
    _adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _adv.CredFree.argtypes = [ctypes.c_void_p]


def _require_windows() -> None:
    if os.name != "nt":
        raise CredError("Windows Credential Manager is only available on Windows")


def vault_write(user: str, password: str, target: str = TARGET) -> None:
    _require_windows()
    blob = password.encode("utf-16-le")
    buf = ctypes.create_string_buffer(blob, len(blob))
    cred = _CREDENTIALW()
    cred.Type = _CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.UserName = user
    cred.Comment = "HIVE Gmail app password (entered in the HIVE app)"
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    cred.Persist = _CRED_PERSIST_LOCAL_MACHINE
    if not _adv.CredWriteW(ctypes.byref(cred), 0):
        raise CredError(f"CredWrite failed (error {ctypes.get_last_error()})")


def vault_read(target: str = TARGET) -> tuple[str, str] | None:
    if os.name != "nt":
        return None
    p = ctypes.POINTER(_CREDENTIALW)()
    if not _adv.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        err = ctypes.get_last_error()
        if err == _ERROR_NOT_FOUND:
            return None
        raise CredError(f"CredRead failed (error {err})")
    try:
        c = p.contents
        pw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-16-le")
        return (c.UserName or "", pw)
    finally:
        _adv.CredFree(p)


def vault_delete(target: str = TARGET) -> bool:
    if os.name != "nt":
        return False
    if not _adv.CredDeleteW(target, _CRED_TYPE_GENERIC, 0):
        err = ctypes.get_last_error()
        if err == _ERROR_NOT_FOUND:
            return False
        raise CredError(f"CredDelete failed (error {err})")
    return True


# ---------- session (memory-only) ----------
def session_set(user: str, password: str) -> None:
    _session[TARGET] = (user, password)


def session_get() -> tuple[str, str] | None:
    return _session.get(TARGET)


def session_clear() -> None:
    _session.pop(TARGET, None)
