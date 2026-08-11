"""Brings the app window to the foreground (Windows-only, ctypes -- no new dependency).

Windows blocks SetForegroundWindow from background processes by default (the
"foreground lock"). The standard, widely used workaround is to synthesize a
harmless ALT keypress right before calling it -- Windows grants the foreground
switch to whichever process most recently generated input. If that still
doesn't take (locked down systems, some Windows builds), we fall back to
flashing the taskbar icon so the user at least notices.
"""
import ctypes

SW_RESTORE = 9
VK_MENU = 0x12  # ALT
KEYEVENTF_KEYUP = 0x0002


def _nudge_foreground_lock():
    ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)


def focus_window(title: str) -> bool:
    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    if not hwnd:
        return False

    ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
    _nudge_foreground_lock()
    brought_forward = bool(ctypes.windll.user32.SetForegroundWindow(hwnd))

    if not brought_forward:
        FLASHW_ALL, FLASHW_TIMERNOFG = 0x3, 0xC

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("hwnd", ctypes.c_void_p),
                ("dwFlags", ctypes.c_uint),
                ("uCount", ctypes.c_uint),
                ("dwTimeout", ctypes.c_uint),
            ]

        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, FLASHW_ALL | FLASHW_TIMERNOFG, 5, 0)
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))

    return True
