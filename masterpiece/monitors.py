"""Windows monitor detection and per-monitor wallpaper via IDesktopWallpaper (COM, pure ctypes).

IDesktopWallpaper (shobjidl_core.h) vtable, after IUnknown's 3 methods:
   3 SetWallpaper(LPCWSTR monitorID, LPCWSTR wallpaper)
   4 GetWallpaper(LPCWSTR monitorID, LPWSTR *wallpaper)
   5 GetMonitorDevicePathAt(UINT index, LPWSTR *monitorID)
   6 GetMonitorDevicePathCount(UINT *count)
   7 GetMonitorRECT(LPCWSTR monitorID, RECT *rect)
  10 SetPosition(DESKTOP_WALLPAPER_POSITION)
  11 GetPosition(DESKTOP_WALLPAPER_POSITION *)
  12 SetSlideshow(IShellItemArray *items)
  14 SetSlideshowOptions(DESKTOP_SLIDESHOW_OPTIONS options, UINT slideshowTick /* ms */)
"""

from __future__ import annotations

import ctypes
import os
import sys
from contextlib import contextmanager
from ctypes import POINTER, byref, c_uint, c_void_p, c_wchar_p, wintypes

IS_WINDOWS = sys.platform == "win32"

# DESKTOP_WALLPAPER_POSITION
POSITIONS = {"center": 0, "tile": 1, "stretch": 2, "fit": 3, "fill": 4, "span": 5}


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, s: str) -> "GUID":
        g = cls()
        ctypes.oledll.ole32.CLSIDFromString(c_wchar_p(s), byref(g))
        return g


CLSID_DesktopWallpaper = "{C2CF3110-460E-4fc1-B9D0-8A1C0C9CC4BD}"
IID_IDesktopWallpaper = "{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}"
CLSCTX_ALL = 0x17
HRESULT = ctypes.HRESULT if IS_WINDOWS else ctypes.c_long

if IS_WINDOWS:
    _P = ctypes.WINFUNCTYPE
    _SetWallpaper = _P(HRESULT, c_wchar_p, c_wchar_p)(3, "SetWallpaper")
    _GetWallpaper = _P(HRESULT, c_wchar_p, POINTER(c_void_p))(4, "GetWallpaper")
    _GetPathAt = _P(HRESULT, c_uint, POINTER(c_void_p))(5, "GetMonitorDevicePathAt")
    _GetPathCount = _P(HRESULT, POINTER(c_uint))(6, "GetMonitorDevicePathCount")
    _GetRect = _P(HRESULT, c_wchar_p, POINTER(wintypes.RECT))(7, "GetMonitorRECT")
    _SetPosition = _P(HRESULT, ctypes.c_int)(10, "SetPosition")
    _GetPosition = _P(HRESULT, POINTER(ctypes.c_int))(11, "GetPosition")
    _SetSlideshow = _P(HRESULT, c_void_p)(12, "SetSlideshow")
    _SetSlideshowOptions = _P(HRESULT, ctypes.c_int, c_uint)(14, "SetSlideshowOptions")
    _SetBackgroundColor = _P(HRESULT, wintypes.DWORD)(8, "SetBackgroundColor")
    _GetBackgroundColor = _P(HRESULT, POINTER(wintypes.DWORD))(9, "GetBackgroundColor")
    _GetSlideshow = _P(HRESULT, POINTER(c_void_p))(13, "GetSlideshow")
    _GetSlideshowOptions = _P(HRESULT, POINTER(ctypes.c_int), POINTER(c_uint))(15, "GetSlideshowOptions")
    _GetStatus = _P(HRESULT, POINTER(ctypes.c_int))(17, "GetStatus")
    # IShellItemArray / IShellItem
    _ArrGetCount = _P(HRESULT, POINTER(wintypes.DWORD))(7, "GetCount")
    _ArrGetItemAt = _P(HRESULT, wintypes.DWORD, POINTER(c_void_p))(8, "GetItemAt")
    _ItemGetDisplayName = _P(HRESULT, ctypes.c_int, POINTER(c_void_p))(5, "GetDisplayName")
    _Release = _P(ctypes.c_ulong)(2, "Release")

    # Physical pixels rather than DPI-scaled ones (per-monitor aware v2)
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(c_void_p(-4))
    except (AttributeError, OSError):
        pass


def _take_string(p: c_void_p) -> str:
    try:
        return ctypes.wstring_at(p.value) if p.value else ""
    finally:
        if p.value:
            ctypes.windll.ole32.CoTaskMemFree(p)


@contextmanager
def _desktop_wallpaper():
    if not IS_WINDOWS:
        raise OSError("Only supported on Windows")
    hr = ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    ptr = c_void_p()
    try:
        ctypes.oledll.ole32.CoCreateInstance(
            byref(GUID.parse(CLSID_DesktopWallpaper)), None, CLSCTX_ALL,
            byref(GUID.parse(IID_IDesktopWallpaper)), byref(ptr))
        yield ptr
    finally:
        if ptr.value:
            _Release(ptr)
        if hr in (0, 1):  # S_OK / S_FALSE -> we own this init
            ctypes.windll.ole32.CoUninitialize()


def list_monitors() -> list[dict]:
    """Active monitors: [{id, x, y, width, height, primary}] in physical pixels."""
    out = []
    with _desktop_wallpaper() as dw:
        count = c_uint()
        _GetPathCount(dw, byref(count))
        for i in range(count.value):
            p = c_void_p()
            if _GetPathAt(dw, i, byref(p)):
                continue
            mid = _take_string(p)
            r = wintypes.RECT()
            try:
                _GetRect(dw, mid, byref(r))
            except OSError:
                continue          # attached but inactive monitor
            w, h = r.right - r.left, r.bottom - r.top
            if w > 0 and h > 0:
                out.append({"id": mid, "x": r.left, "y": r.top, "width": w, "height": h,
                            "primary": r.left == 0 and r.top == 0})
    return out


def layout() -> dict:
    """Monitors plus the bounding box of the whole desktop (what 'span' covers)."""
    try:
        mons = list_monitors()
    except OSError as e:
        return {"monitors": [], "span": None, "error": str(e)}
    if not mons:
        return {"monitors": [], "span": None}
    x0 = min(m["x"] for m in mons)
    y0 = min(m["y"] for m in mons)
    x1 = max(m["x"] + m["width"] for m in mons)
    y1 = max(m["y"] + m["height"] for m in mons)
    return {"monitors": mons, "span": {"width": x1 - x0, "height": y1 - y0}}


IID_IShellItem = "{43826d1e-e718-42ee-bc55-a1e261c37bfe}"
IID_IShellItemArray = "{b63ea76d-1f85-456f-a19c-48159efa858b}"
DSO_SHUFFLEIMAGES = 0x1


def set_slideshow(folder, *, interval_minutes: int = 60, shuffle: bool = True, span: bool = False) -> None:
    """Turn on Windows' own slideshow for `folder` (same as Settings > Personalisation >
    Background > Slideshow), with the given interval and shuffle."""
    if not IS_WINDOWS:
        raise OSError("Only supported on Windows")
    with _desktop_wallpaper() as dw:
        item, arr = c_void_p(), c_void_p()
        try:
            ctypes.oledll.shell32.SHCreateItemFromParsingName(
                c_wchar_p(str(folder)), None, byref(GUID.parse(IID_IShellItem)), byref(item))
            ctypes.oledll.shell32.SHCreateShellItemArrayFromShellItem(
                item, byref(GUID.parse(IID_IShellItemArray)), byref(arr))
            _SetPosition(dw, POSITIONS["span" if span else "fill"])
            _SetSlideshow(dw, arr)
            _SetSlideshowOptions(dw, DSO_SHUFFLEIMAGES if shuffle else 0,
                                 max(1, int(interval_minutes)) * 60_000)
        finally:
            for p in (arr, item):
                if p.value:
                    _Release(p)


DSS_SLIDESHOW = 0x2
SIGDN_FILESYSPATH = 0x80058000 - 0x100000000     # as signed int


def snapshot() -> dict:
    """The current desktop background, so it can be put back later."""
    with _desktop_wallpaper() as dw:
        pos, color, status = ctypes.c_int(), wintypes.DWORD(), ctypes.c_int()
        _GetPosition(dw, byref(pos))
        _GetBackgroundColor(dw, byref(color))
        try:
            _GetStatus(dw, byref(status))
        except OSError:
            status.value = 0
        walls = {}
        count = c_uint()
        _GetPathCount(dw, byref(count))
        for i in range(count.value):
            p = c_void_p()
            if _GetPathAt(dw, i, byref(p)):
                continue
            mid = _take_string(p)
            w = c_void_p()
            try:
                _GetWallpaper(dw, mid, byref(w))
                walls[mid] = _take_string(w)
            except OSError:
                walls[mid] = ""
        snap = {"position": pos.value, "color": color.value, "wallpapers": walls, "slideshow": None}
        if status.value & DSS_SLIDESHOW:
            arr = c_void_p()
            try:
                _GetSlideshow(dw, byref(arr))
                n = wintypes.DWORD()
                _ArrGetCount(arr, byref(n))
                if n.value:
                    item, name = c_void_p(), c_void_p()
                    _ArrGetItemAt(arr, 0, byref(item))
                    try:
                        _ItemGetDisplayName(item, SIGDN_FILESYSPATH, byref(name))
                        folder = _take_string(name)
                    finally:
                        _Release(item)
                    opts, tick = ctypes.c_int(), c_uint()
                    _GetSlideshowOptions(dw, byref(opts), byref(tick))
                    snap["slideshow"] = {"folder": folder, "options": opts.value, "tick": tick.value}
            except OSError:
                pass
            finally:
                if arr.value:
                    _Release(arr)
        return snap


def restore(snap: dict, files: dict[str, str]) -> None:
    """Put back a snapshot. `files` maps monitor id -> image to use (backup copies)."""
    ss = snap.get("slideshow")
    if ss and ss.get("folder") and os.path.isdir(ss["folder"]):
        set_slideshow(ss["folder"], interval_minutes=max(1, ss.get("tick", 1_800_000) // 60_000),
                      shuffle=bool(ss.get("options", 0) & DSO_SHUFFLEIMAGES),
                      span=snap.get("position") == POSITIONS["span"])
        return
    with _desktop_wallpaper() as dw:
        _SetBackgroundColor(dw, int(snap.get("color", 0)))
        _SetPosition(dw, int(snap.get("position", POSITIONS["fill"])))
        current = [m["id"] for m in list_monitors()]
        fallback = next(iter(files.values()), "")
        if snap.get("position") == POSITIONS["span"] and fallback:
            _SetWallpaper(dw, None, fallback)
            return
        for mid in current:
            path = files.get(mid) or fallback
            if path:
                _SetWallpaper(dw, mid, path)


def set_all(path: str, *, span: bool = False) -> None:
    """One image on every monitor ('fill'), or stretched across all of them ('span')."""
    with _desktop_wallpaper() as dw:
        _SetPosition(dw, POSITIONS["span" if span else "fill"])
        _SetWallpaper(dw, None, path)


def set_each(mapping: dict[str, str]) -> None:
    """{monitor_id: image_path} — a different image per monitor."""
    with _desktop_wallpaper() as dw:
        _SetPosition(dw, POSITIONS["fill"])
        for mid, path in mapping.items():
            _SetWallpaper(dw, mid, path)
