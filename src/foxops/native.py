"""Optional Windows shell folder picker. Never required for the default data location."""

import ctypes
import sys
from ctypes import wintypes


def browse_folder() -> str | None:
    if sys.platform != "win32":
        raise ValueError(
            "Native folder selection is available in the Windows desktop app; otherwise enter an absolute folder path"
        )
    libraries = getattr(ctypes, "windll")
    shell, ole = libraries.shell32, libraries.ole32

    class BrowseInfo(ctypes.Structure):
        _fields_ = [
            ("owner", wintypes.HWND),
            ("root", ctypes.c_void_p),
            ("display", wintypes.LPWSTR),
            ("title", wintypes.LPCWSTR),
            ("flags", wintypes.UINT),
            ("callback", ctypes.c_void_p),
            ("parameter", wintypes.LPARAM),
            ("image", ctypes.c_int),
        ]

    ole.CoInitializeEx(None, 2)  # Dedicated picker worker, apartment-threaded.
    shell.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BrowseInfo)]
    shell.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    try:
        display = ctypes.create_unicode_buffer(260)
        libraries.user32.GetForegroundWindow.restype = wintypes.HWND
        info = BrowseInfo(
            libraries.user32.GetForegroundWindow(),
            None,
            ctypes.cast(display, wintypes.LPWSTR),
            "FoxSuite",
            0x41,
            None,
            0,
            0,
        )
        item = shell.SHBrowseForFolderW(ctypes.byref(info))
        if not item:
            return None
        try:
            path = ctypes.create_unicode_buffer(32768)
            if not shell.SHGetPathFromIDListW(item, path):
                raise ValueError("Choose an absolute data folder, not a drive root")
            return path.value
        finally:
            ole.CoTaskMemFree(item)
    finally:
        ole.CoUninitialize()
