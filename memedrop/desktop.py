"""Desktop integration boundary: Win32 in production, disabled in Linux tests."""
import sys

AVAILABLE = sys.platform == 'win32'

if AVAILABLE:
    from . import windows as backend
    from .windows import (HOTKEY_ID, WM_HOTKEY, external_window, foreground,
                          modifiers_down, paste, register_hotkey, restore_target,
                          unregister_hotkey, window_title)
else:
    backend = None
    HOTKEY_ID = 0x4D44
    WM_HOTKEY = 0x0312

    def foreground():
        return 0

    def external_window(hwnd):
        return False

    def window_title(hwnd):
        return ''

    def register_hotkey(hwnd, key):
        return False

    def unregister_hotkey(hwnd):
        pass

    def restore_target(hwnd):
        return False

    def modifiers_down():
        return False

    def paste(hwnd):
        return False
