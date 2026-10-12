"""Small, pointer-safe Win32 bridge. No hooks, injection, or background typing."""
import ctypes
import os
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

HOTKEY_ID = 0x4D44
WM_HOTKEY = 0x0312


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD), ('wParamH', wintypes.WORD)]


class INPUT_UNION(ctypes.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT), ('hi', HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', wintypes.DWORD), ('data', INPUT_UNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def foreground() -> int:
    return user32.GetForegroundWindow() or 0


def external_window(hwnd: int) -> bool:
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value != os.getpid()


def window_title(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def register_hotkey(hwnd: int, key: str) -> bool:
    return bool(user32.RegisterHotKey(hwnd, HOTKEY_ID, 0x0002 | 0x0001 | 0x4000, ord(key)))


def unregister_hotkey(hwnd: int):
    user32.UnregisterHotKey(hwnd, HOTKEY_ID)


def restore_target(hwnd: int) -> bool:
    if not external_window(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    return foreground() == hwnd


def modifiers_down() -> bool:
    return any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C))


def paste(hwnd: int) -> bool:
    # Verify again immediately before input; never send into an unexpected window.
    if not external_window(hwnd) or foreground() != hwnd or modifiers_down():
        return False
    events = (INPUT * 4)()
    for event, key, flags in zip(events, (0x11, 0x56, 0x56, 0x11), (0, 0, 2, 2)):
        event.type = 1
        event.ki = KEYBDINPUT(key, 0, flags, 0, 0)
    sent = user32.SendInput(4, events, ctypes.sizeof(INPUT))
    if sent != 4:
        # Release synthetic keys if Windows accepted only part of the sequence.
        release = (INPUT * 2)()
        for event, key in zip(release, (0x56, 0x11)):
            event.type = 1
            event.ki = KEYBDINPUT(key, 0, 2, 0, 0)
        user32.SendInput(2, release, ctypes.sizeof(INPUT))
    return sent == 4
