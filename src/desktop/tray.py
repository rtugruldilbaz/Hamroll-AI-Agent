import os
import threading

from desktop.resources import get_app_icon_path


class TrayController:
    def __init__(
        self,
        root,
        labels,
        open_window,
        open_local_admin,
        open_web,
        open_settings,
        exit_app,
        title="AI Agent",
    ):
        self.root = root
        self.labels = labels
        self.open_window = open_window
        self.open_local_admin = open_local_admin
        self.open_web = open_web
        self.open_settings = open_settings
        self.exit_app = exit_app
        self.title = str(title or "AI Agent")[:127]
        self.thread = None
        self.hwnd = None
        self.ready = threading.Event()
        self.started = False

    def _dispatch(self, callback):
        self.root.after(0, callback)

    def start(self):
        if self.started:
            return True

        if os.name != "nt":
            return False

        self.ready.clear()
        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
        )
        self.thread.start()
        self.ready.wait(timeout=3)
        return self.started

    def stop(self):
        if os.name != "nt":
            return

        hwnd = self.hwnd

        if hwnd:
            try:
                import ctypes

                ctypes.windll.user32.PostMessageW(
                    hwnd,
                    0x0010,
                    0,
                    0,
                )
            except Exception:
                pass

        self.started = False
        self.hwnd = None
        self.thread = None

    def _run(self):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32

        LRESULT = ctypes.c_ssize_t
        WPARAM = ctypes.c_size_t
        LPARAM = ctypes.c_ssize_t
        UINT_PTR = ctypes.c_size_t

        WM_DESTROY = 0x0002
        WM_CLOSE = 0x0010
        WM_COMMAND = 0x0111
        WM_USER = 0x0400
        WM_TRAY = WM_USER + 20
        WM_LBUTTONDBLCLK = 0x0203
        WM_RBUTTONUP = 0x0205

        NIM_ADD = 0x00000000
        NIM_DELETE = 0x00000002
        NIF_MESSAGE = 0x00000001
        NIF_ICON = 0x00000002
        NIF_TIP = 0x00000004

        TPM_RIGHTBUTTON = 0x0002
        TPM_BOTTOMALIGN = 0x0020

        MF_STRING = 0x0000
        MF_SEPARATOR = 0x0800

        ID_OPEN = 1001
        ID_LOCAL_ADMIN = 1002
        ID_OPEN_WEB = 1003
        ID_WEB_SETTINGS = 1004
        ID_EXIT = 1005

        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT,
            wintypes.HWND,
            wintypes.UINT,
            WPARAM,
            LPARAM,
        )

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uTimeoutOrVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
            ]

        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            WPARAM,
            LPARAM,
        ]
        user32.DefWindowProcW.restype = LRESULT

        user32.CreatePopupMenu.argtypes = []
        user32.CreatePopupMenu.restype = wintypes.HMENU

        user32.AppendMenuW.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            UINT_PTR,
            wintypes.LPCWSTR,
        ]
        user32.AppendMenuW.restype = wintypes.BOOL

        user32.TrackPopupMenu.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]
        user32.TrackPopupMenu.restype = wintypes.BOOL

        user32.GetCursorPos.argtypes = [
            ctypes.POINTER(wintypes.POINT),
        ]
        user32.GetCursorPos.restype = wintypes.BOOL

        user32.SetForegroundWindow.argtypes = [
            wintypes.HWND,
        ]
        user32.SetForegroundWindow.restype = wintypes.BOOL

        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND

        user32.DestroyWindow.argtypes = [
            wintypes.HWND,
        ]
        user32.DestroyWindow.restype = wintypes.BOOL

        user32.DestroyMenu.argtypes = [
            wintypes.HMENU,
        ]
        user32.DestroyMenu.restype = wintypes.BOOL

        user32.LoadIconW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
        ]
        user32.LoadIconW.restype = wintypes.HICON

        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.LoadImageW.restype = wintypes.HANDLE

        user32.DestroyIcon.argtypes = [
            wintypes.HICON,
        ]
        user32.DestroyIcon.restype = wintypes.BOOL

        user32.RegisterClassW.argtypes = [
            ctypes.POINTER(WNDCLASSW),
        ]
        user32.RegisterClassW.restype = wintypes.ATOM

        user32.TranslateMessage.argtypes = [
            ctypes.POINTER(wintypes.MSG),
        ]
        user32.TranslateMessage.restype = wintypes.BOOL

        user32.DispatchMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
        ]
        user32.DispatchMessageW.restype = LRESULT

        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.GetMessageW.restype = wintypes.BOOL

        shell32.Shell_NotifyIconW.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(NOTIFYICONDATAW),
        ]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL

        kernel32.GetModuleHandleW.argtypes = [
            wintypes.LPCWSTR,
        ]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

        user32.PostQuitMessage.argtypes = [
            ctypes.c_int,
        ]
        user32.PostQuitMessage.restype = None

        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040

        icon_path = get_app_icon_path()
        icon_owned = False
        icon = None

        if icon_path is not None:
            loaded_icon = user32.LoadImageW(
                None,
                str(icon_path),
                IMAGE_ICON,
                32,
                32,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )

            if loaded_icon:
                icon = wintypes.HICON(loaded_icon)
                icon_owned = True

        if not icon:
            icon = user32.LoadIconW(
                None,
                ctypes.cast(
                    ctypes.c_void_p(32512),
                    wintypes.LPCWSTR,
                ),
            )

        menu = user32.CreatePopupMenu()

        user32.AppendMenuW(
            menu,
            MF_STRING,
            ID_OPEN,
            self.labels["open"],
        )
        user32.AppendMenuW(
            menu,
            MF_STRING,
            ID_LOCAL_ADMIN,
            self.labels["local_admin"],
        )
        user32.AppendMenuW(
            menu,
            MF_STRING,
            ID_OPEN_WEB,
            self.labels["open_web"],
        )
        user32.AppendMenuW(
            menu,
            MF_STRING,
            ID_WEB_SETTINGS,
            self.labels["web_settings"],
        )
        user32.AppendMenuW(
            menu,
            MF_SEPARATOR,
            0,
            None,
        )
        user32.AppendMenuW(
            menu,
            MF_STRING,
            ID_EXIT,
            self.labels["exit"],
        )

        notify_data = NOTIFYICONDATAW()

        def show_menu(hwnd):
            point = wintypes.POINT()
            user32.GetCursorPos(
                ctypes.byref(point)
            )
            user32.SetForegroundWindow(hwnd)
            user32.TrackPopupMenu(
                menu,
                TPM_RIGHTBUTTON | TPM_BOTTOMALIGN,
                point.x,
                point.y,
                0,
                hwnd,
                None,
            )

        @WNDPROC
        def wnd_proc(hwnd, message, wparam, lparam):
            if message == WM_TRAY:
                if lparam == WM_LBUTTONDBLCLK:
                    self._dispatch(self.open_window)
                    return 0

                if lparam == WM_RBUTTONUP:
                    show_menu(hwnd)
                    return 0

            if message == WM_COMMAND:
                command_id = int(wparam) & 0xFFFF

                if command_id == ID_OPEN:
                    self._dispatch(self.open_window)
                elif command_id == ID_LOCAL_ADMIN:
                    self._dispatch(self.open_local_admin)
                elif command_id == ID_OPEN_WEB:
                    self._dispatch(self.open_web)
                elif command_id == ID_WEB_SETTINGS:
                    self._dispatch(self.open_settings)
                elif command_id == ID_EXIT:
                    self._dispatch(self.exit_app)

                return 0

            if message == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0

            if message == WM_DESTROY:
                shell32.Shell_NotifyIconW(
                    NIM_DELETE,
                    ctypes.byref(notify_data),
                )
                user32.PostQuitMessage(0)
                return 0

            return user32.DefWindowProcW(
                hwnd,
                message,
                wparam,
                lparam,
            )

        self._wnd_proc = wnd_proc

        class_name = f"AI_Agent_Tray_{id(self)}"
        instance = kernel32.GetModuleHandleW(None)

        window_class = WNDCLASSW()
        window_class.lpfnWndProc = wnd_proc
        window_class.hInstance = instance
        window_class.hIcon = icon
        window_class.lpszClassName = class_name

        if not user32.RegisterClassW(
            ctypes.byref(window_class)
        ):
            self.ready.set()
            return

        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "AI Agent Tray",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            instance,
            None,
        )

        if not hwnd:
            self.ready.set()
            return

        self.hwnd = hwnd

        notify_data.cbSize = ctypes.sizeof(
            NOTIFYICONDATAW
        )
        notify_data.hWnd = hwnd
        notify_data.uID = 1
        notify_data.uFlags = (
            NIF_MESSAGE
            | NIF_ICON
            | NIF_TIP
        )
        notify_data.uCallbackMessage = WM_TRAY
        notify_data.hIcon = icon
        notify_data.szTip = self.title

        added = shell32.Shell_NotifyIconW(
            NIM_ADD,
            ctypes.byref(notify_data),
        )

        if not added:
            user32.DestroyWindow(hwnd)
            self.ready.set()
            return

        self.started = True
        self.ready.set()

        message = wintypes.MSG()

        while user32.GetMessageW(
            ctypes.byref(message),
            None,
            0,
            0,
        ) > 0:
            user32.TranslateMessage(
                ctypes.byref(message)
            )
            user32.DispatchMessageW(
                ctypes.byref(message)
            )

        user32.DestroyMenu(menu)

        if icon_owned and icon:
            user32.DestroyIcon(icon)

        self.started = False
        self.hwnd = None
