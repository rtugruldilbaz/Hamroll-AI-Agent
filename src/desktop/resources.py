import ctypes
import sys
from pathlib import Path


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base.joinpath(*parts)


def get_app_icon_path() -> Path | None:
    path = resource_path("assets", "app.ico")
    return path if path.is_file() else None


def apply_dark_title_bar(window) -> None:
    if sys.platform != "win32":
        return

    try:
        window.update_idletasks()
        set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        )

        hwnd = ctypes.c_void_p(window.winfo_id())
        enabled = ctypes.c_int(1)
        caption = ctypes.c_uint(0x00100B09)
        title_text = ctypes.c_uint(0x00FBF7F5)

        for attribute, value in (
            (20, enabled),
            (35, caption),
            (36, title_text),
        ):
            set_attribute(
                hwnd,
                attribute,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
    except (AttributeError, OSError):
        pass
