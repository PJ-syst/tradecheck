"""Per-Windows-user encrypted credentials, stored only under ignored data/."""

import base64
import ctypes
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data"


def _crypt(data, decrypt=False):
    if os.name != "nt":
        raise ValueError("Encrypted credential storage is supported on Windows; use server environment variables elsewhere.")

    class Blob(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    destination = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        method = crypt32.CryptUnprotectData
        method.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
        ok = method(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination))
    else:
        method = crypt32.CryptProtectData
        method.argtypes = [ctypes.POINTER(Blob), ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
        ok = method(ctypes.byref(source), "TradeCheck", None, None, None, 1, ctypes.byref(destination))
    if not ok:
        raise ValueError("Windows could not access encrypted credentials. Run setup as your Windows user.")
    try:
        return ctypes.string_at(destination.data, destination.length)
    finally:
        kernel32.LocalFree(destination.data)


def save(name, value):
    if name not in {"openai", "binance"}:
        raise ValueError("Unknown credential store.")
    encoded = base64.b64encode(_crypt(json.dumps(value).encode()))
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = ROOT / (name + ".credential.tmp")
    temporary.write_bytes(encoded)
    temporary.replace(ROOT / (name + ".credential"))


def load(name):
    if name not in {"openai", "binance"}:
        raise ValueError("Unknown credential store.")
    path = ROOT / (name + ".credential")
    if not path.exists():
        return {}
    try:
        result = json.loads(_crypt(base64.b64decode(path.read_bytes(), validate=True), decrypt=True))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, OSError):
        raise ValueError("Saved credentials could not be opened. Run setup again as your Windows user.") from None
