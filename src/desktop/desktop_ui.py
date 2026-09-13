import queue
import socket
import threading
import os
import webbrowser
import tkinter as tk
from tkinter import StringVar, filedialog, messagebox, ttk

import requests

from config.app_settings import (
    DEFAULT_AGENT_NAME,
    DEFAULT_EMBEDDING_MODEL,
    get_language,
    load_secrets,
    load_settings,
    save_secrets,
    update_settings,
)
from config.i18n import translate
from desktop.resources import get_app_icon_path
from desktop.tray import TrayController
from speech.hotkey_listener import (
    get_voice_status,
    parse_hotkey,
    refresh_voice_hotkey,
    set_local_admin_active,
    set_voice_message_handler,
)
from speech.recorder import start_recording, stop_recording
from speech.transcriber import transcribe_audio
from web.database import (
    clear_all_web_history,
    clear_guest_usage,
    get_all_web_messages,
    get_user_by_id,
    get_user_by_username,
    get_web_admin,
    save_web_admin_credentials,
)

BG = "#090b10"
SIDEBAR = "#0b0f16"
SIDEBAR_ALT = "#171c26"
SIDEBAR_MUTED = "#7f8898"
SURFACE = "#151922"
SURFACE_ALT = "#1b202a"
TEXT = "#f5f7fb"
MUTED = "#99a2b1"
BORDER = "#2a303c"
ACCENT = "#4969c9"
ACCENT_HOVER = "#5878da"
SUCCESS_BG = "#143325"
SUCCESS_TEXT = "#8ee0b1"
WARNING_BG = "#3a2a14"
WARNING_TEXT = "#f1bf73"
DANGER_BG = "#351b1f"
DANGER_TEXT = "#ff9eaa"
PASSWORD_MASK = "••••••••"
SECRET_MASK = "••••••••••••••••"


def _t(key, **values):
    return translate(get_language(), key, **values)


def _model_installed(requested, installed_models):
    requested = str(requested or "").strip().casefold()
    if not requested:
        return False

    for installed in installed_models:
        installed = str(installed or "").strip().casefold()
        if installed == requested:
            return True
        if ":" not in requested and installed.split(":", 1)[0] == requested:
            return True

    return False


class DesktopUI:
    def __init__(
        self,
        agent,
        start_web,
        stop_web,
        web_running,
        start_telegram,
        stop_telegram,
        telegram_status,
    ):
        self.agent = agent
        self.start_web = start_web
        self.stop_web = stop_web
        self.web_running = web_running
        self.start_telegram = start_telegram
        self.stop_telegram = stop_telegram
        self.telegram_status = telegram_status
        self.root = tk.Tk()
        self.root.title(DEFAULT_AGENT_NAME)
        self.root.geometry("1160x780")
        self.root.minsize(1000, 700)
        self.root.configure(bg=BG)

        self.language = StringVar()
        self.agent_name = StringVar()
        self.ollama_status = StringVar()
        self.hotkey_capture = False
        self.hotkey_modifiers = set()
        self.local_admin_window = None
        self.system_history_window = None
        self.local_admin_voice_target = None
        self.voice_messages = queue.Queue()
        self.status_labels = {}
        self.tray = None
        self.exiting = False

        self.root.protocol("WM_DELETE_WINDOW", self._exit_application)
        set_voice_message_handler(self.voice_messages.put)
        self.root.after(100, self._poll_voice_messages)

        self._apply_window_icon(self.root)
        self._configure_ttk()
        self._load_values()
        self._sync_window_identity()
        self._build()
        self._test_ollama_async()

    def _apply_window_icon(self, window):
        icon_path = get_app_icon_path()

        if icon_path is None:
            return

        try:
            window.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass

    def _sync_window_identity(self):
        name = self.agent_name.get().strip() or DEFAULT_AGENT_NAME
        self.root.title(name)

    def _get_lan_ip(self):
        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )

        try:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
        except OSError:
            try:
                address = socket.gethostbyname(
                    socket.gethostname()
                )
            except OSError:
                address = ""
        finally:
            sock.close()

        if not address or address.startswith("127."):
            return ""

        return address

    def _web_display_address(self, settings=None):
        settings = settings or load_settings()
        port = settings["web"]["port"]

        if settings["web"]["access"] == "lan":
            lan_ip = self._get_lan_ip()

            if lan_ip:
                return f"http://{lan_ip}:{port}"

            return _t("desktop_lan_address_unavailable")

        return f"http://127.0.0.1:{port}"

    def _configure_ttk(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Modern.TCombobox",
            padding=8,
            fieldbackground=SURFACE,
            background=SURFACE,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            arrowcolor=TEXT,
            selectbackground=ACCENT,
            selectforeground="#ffffff",
        )
        style.map(
            "Modern.TCombobox",
            fieldbackground=[("readonly", SURFACE)],
            foreground=[("readonly", TEXT)],
            bordercolor=[("focus", ACCENT), ("!focus", BORDER)],
            lightcolor=[("focus", ACCENT), ("!focus", BORDER)],
            darkcolor=[("focus", ACCENT), ("!focus", BORDER)],
            arrowcolor=[("active", "#ffffff"), ("!active", TEXT)],
        )

        style.configure(
            "Dark.Vertical.TScrollbar",
            background="#252b36",
            troughcolor="#0d1118",
            bordercolor="#0d1118",
            darkcolor="#252b36",
            lightcolor="#252b36",
            arrowcolor=MUTED,
            relief="flat",
            width=12,
            arrowsize=10,
        )
        style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", "#343c4a"), ("pressed", "#3d4656")],
            arrowcolor=[("active", TEXT), ("!active", MUTED)],
        )

    def _load_values(self):
        settings = load_settings()
        self.language.set("Türkçe (TR)" if settings["general"]["language"] == "tr" else "English (EN)")
        self.agent_name.set(settings["general"].get("agent_name") or DEFAULT_AGENT_NAME)

    def _button(self, parent, text, command, primary=False, variant=None):
        if variant is None:
            variant = "primary" if primary else "secondary"

        palette = {
            "primary": (ACCENT, "#ffffff", ACCENT_HOVER, "#6079c9"),
            "secondary": ("#1d2738", "#d8e2f2", "#26344b", "#34445e"),
            "neutral": ("#171c26", "#e5e9f0", "#202735", "#303846"),
            "danger": ("#341b1f", "#ffadb6", "#432228", "#603039"),
        }
        bg, fg, hover, border = palette.get(variant, palette["secondary"])

        button = tk.Button(
            parent,
            text=text,
            command=command,
            font=("Segoe UI Semibold", 9),
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=15,
            pady=9,
            highlightthickness=1,
            highlightbackground=border,
            highlightcolor=border,
        )
        button.bind("<Enter>", lambda event: button.configure(bg=hover))
        button.bind("<Leave>", lambda event: button.configure(bg=bg))
        return button

    def _info_button(self, parent, text):
        button = tk.Label(
            parent,
            text="i",
            width=2,
            height=1,
            bg="#1d2738",
            fg="#a9c2ff",
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#34445e",
        )

        tooltip = tk.Toplevel(self.root)
        tooltip.withdraw()
        tooltip.overrideredirect(True)
        tooltip.configure(bg=BORDER)

        body = tk.Frame(tooltip, bg=SURFACE)
        body.pack(padx=1, pady=1)
        tk.Label(
            body,
            text=text,
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI", 9),
            justify="left",
            wraplength=360,
            padx=12,
            pady=9,
        ).pack()

        def show(event=None):
            x = button.winfo_rootx() + button.winfo_width() + 8
            y = button.winfo_rooty() - 4
            tooltip.geometry(f"+{x}+{y}")
            tooltip.deiconify()
            tooltip.lift()

        def hide(event=None):
            tooltip.withdraw()

        button.bind("<Enter>", show)
        button.bind("<Leave>", hide)
        button.bind("<Button-1>", show)
        return button

    def _entry(self, parent, variable, show=None):
        return tk.Entry(
            parent,
            textvariable=variable,
            show=show,
            font=("Segoe UI", 10),
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )

    def _sidebar_button(self, parent, text, command, active=False):
        return tk.Button(
            parent,
            text=text,
            command=command,
            anchor="w",
            font=("Segoe UI", 9, "bold" if active else "normal"),
            bg=SIDEBAR_ALT if active else SIDEBAR,
            fg="#ffffff" if active else "#d1d5db",
            activebackground=SIDEBAR_ALT,
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=12,
            pady=10,
        )

    def _build(self):
        for child in self.root.winfo_children():
            if not isinstance(child, tk.Toplevel):
                child.destroy()
        self.status_labels = {}

        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True)

        sidebar = tk.Frame(shell, bg=SIDEBAR, width=225)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand = tk.Frame(sidebar, bg=SIDEBAR)
        brand.pack(fill="x", padx=22, pady=(24, 20))
        tk.Label(
            brand,
            textvariable=self.agent_name,
            bg=SIDEBAR,
            fg="#ffffff",
            font=("Segoe UI", 16, "bold"),
            wraplength=170,
            justify="left",
            anchor="w",
        ).pack(fill="x", anchor="w")
        tk.Label(brand, text=_t("desktop_control_center"), bg=SIDEBAR, fg=SIDEBAR_MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))

        nav = tk.Frame(sidebar, bg=SIDEBAR)
        nav.pack(fill="x", padx=14)
        self._sidebar_button(nav, _t("desktop_overview"), self._scroll_top, active=True).pack(fill="x", pady=2)
        self._sidebar_button(nav, _t("desktop_local_admin_chat"), self._open_local_admin).pack(fill="x", pady=2)
        self._sidebar_button(nav, _t("desktop_open_web"), self._open_web).pack(fill="x", pady=2)
        self._sidebar_button(nav, _t("desktop_web_settings"), self._open_settings).pack(fill="x", pady=2)

        hint = tk.Frame(sidebar, bg=SIDEBAR_ALT)
        hint.pack(side="bottom", fill="x", padx=14, pady=16)
        tk.Label(
            hint,
            text=_t("desktop_advanced_settings_short"),
            bg=SIDEBAR_ALT,
            fg="#d1d5db",
            font=("Segoe UI", 8),
            wraplength=170,
            justify="left",
        ).pack(anchor="w", padx=12, pady=12)

        main = tk.Frame(shell, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        topbar = tk.Frame(main, bg=SURFACE, height=96, highlightthickness=1, highlightbackground=BORDER)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        heading = tk.Frame(topbar, bg=SURFACE)
        heading.pack(side="left", padx=28, pady=16)
        tk.Label(heading, text=_t("desktop_dashboard"), bg=SURFACE, fg=TEXT, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(heading, text=_t("desktop_dashboard_help"), bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), wraplength=720, justify="left").pack(anchor="w", pady=(4, 0))

        language_combo = ttk.Combobox(
            topbar,
            textvariable=self.language,
            values=("Türkçe (TR)", "English (EN)"),
            state="readonly",
            width=16,
            style="Modern.TCombobox",
        )
        language_combo.pack(side="right", padx=28, pady=28)
        language_combo.bind("<<ComboboxSelected>>", self._change_language)

        body = tk.Frame(main, bg=BG)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview, style="Dark.Vertical.TScrollbar")
        content = tk.Frame(self.canvas, bg=BG)
        content.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        window_id = self.canvas.create_window((0, 0), window=content, anchor="nw")
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window_id, width=event.width))
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        def scroll_dashboard(event):
            widget = event.widget

            while widget is not None:
                if widget is self.canvas:
                    self.canvas.yview_scroll(
                        int(-event.delta / 120),
                        "units",
                    )
                    return "break"

                widget = getattr(
                    widget,
                    "master",
                    None,
                )

            return None

        self.canvas.bind_all(
            "<MouseWheel>",
            scroll_dashboard,
        )

        inner = tk.Frame(content, bg=BG)
        inner.pack(fill="both", expand=True, padx=28, pady=24)

        self._build_identity(inner)

        row1 = tk.Frame(inner, bg=BG)
        row1.pack(fill="x")
        row1.columnconfigure(0, weight=1, uniform="r1")
        row1.columnconfigure(1, weight=1, uniform="r1")
        self._build_ollama(row1)
        self._build_web(row1)

        row2 = tk.Frame(inner, bg=BG)
        row2.pack(fill="x")
        row2.columnconfigure(0, weight=1, uniform="r2")
        row2.columnconfigure(1, weight=1, uniform="r2")
        self._build_admin(row2)
        self._build_telegram(row2)

        row3 = tk.Frame(inner, bg=BG)
        row3.pack(fill="x")
        row3.columnconfigure(0, weight=1, uniform="r3")
        row3.columnconfigure(1, weight=1, uniform="r3")
        self._build_voice(row3)
        self._build_quick_access(row3)

        self._refresh_statuses()

    def _scroll_top(self):
        self.canvas.yview_moveto(0)

    def _card(self, parent, title, subtitle=None, grid=None):
        card = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        if grid is None:
            card.pack(fill="x", pady=(0, 14))
        else:
            row, column, padx = grid
            card.grid(row=row, column=column, sticky="nsew", padx=padx, pady=(0, 14))

        head = tk.Frame(card, bg=SURFACE)
        head.pack(fill="x", padx=18, pady=(16, 10))
        tk.Label(head, text=title, bg=SURFACE, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        if subtitle:
            tk.Label(
                head,
                text=subtitle,
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI", 9),
                wraplength=390,
                justify="left",
            ).pack(anchor="w", pady=(4, 0))

        content = tk.Frame(card, bg=SURFACE)
        content.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        return content

    def _badge(self, parent, key):
        label = tk.Label(parent, bg="#202633", fg=MUTED, font=("Segoe UI", 8, "bold"), padx=9, pady=3)
        label.pack(side="right")
        self.status_labels[key] = label
        return label

    def _set_badge(self, key, text, state):
        label = self.status_labels.get(key)
        if label is None:
            return
        palette = {
            "success": (SUCCESS_BG, SUCCESS_TEXT),
            "warning": (WARNING_BG, WARNING_TEXT),
            "error": (DANGER_BG, DANGER_TEXT),
            "idle": ("#202633", MUTED),
        }
        bg, fg = palette[state]
        label.configure(text=text, bg=bg, fg=fg)

    def _info_line(self, parent, label, value, secret=False):
        row = tk.Frame(parent, bg=SURFACE)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        tk.Label(
            row,
            text=PASSWORD_MASK if secret else value,
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI", 9, "bold"),
            wraplength=250,
            justify="right",
        ).pack(side="right")

    def _build_identity(self, parent):
        box = self._card(parent, _t("desktop_general"), _t("desktop_general_help"))
        row = tk.Frame(box, bg=SURFACE)
        row.pack(fill="x")
        tk.Label(row, textvariable=self.agent_name, bg=SURFACE, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(side="left")
        self._button(row, _t("desktop_edit"), self._open_name_dialog).pack(side="right")

    def _build_ollama(self, parent):
        settings = load_settings()
        box = self._card(parent, "Ollama", _t("desktop_ollama_summary_help"), grid=(0, 0, (0, 7)))
        top = tk.Frame(box, bg=SURFACE)
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text=_t("desktop_status"), bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        self._badge(top, "ollama")
        self._info_line(box, _t("desktop_chat_model"), settings["model"]["chat_model"])
        self._info_line(box, _t("desktop_embedding_model"), DEFAULT_EMBEDDING_MODEL)
        actions = tk.Frame(box, bg=SURFACE)
        actions.pack(fill="x", pady=(10, 0))
        self._button(actions, _t("desktop_check_connection"), self._test_ollama_async, variant="secondary").pack(side="left")
        self._button(actions, _t("desktop_configure"), self._open_ollama_dialog, variant="primary").pack(side="right")

    def _build_web(self, parent):
        box = self._card(parent, _t("desktop_web"), _t("desktop_web_card_help"), grid=(0, 1, (7, 0)))
        top = tk.Frame(box, bg=SURFACE)
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text=_t("desktop_status"), bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        self._badge(top, "web")
        settings = load_settings()
        access_label = (
            _t("desktop_web_access_lan")
            if settings["web"]["access"] == "lan"
            else _t("desktop_web_access_local")
        )
        self._info_line(
            box,
            _t("desktop_network_access"),
            access_label,
        )
        self._info_line(
            box,
            _t("desktop_address"),
            self._web_display_address(settings),
        )

        actions = tk.Frame(box, bg=SURFACE)
        actions.pack(fill="x", pady=(10, 0))

        self.web_action_button = self._button(
            actions,
            "",
            self._toggle_web,
            variant="neutral",
        )
        self.web_action_button.pack(side="left")

        self._button(
            actions,
            _t("desktop_network_settings"),
            self._open_web_network_dialog,
            variant="secondary",
        ).pack(side="left", padx=(8, 0))

        self._button(
            actions,
            _t("desktop_open_web"),
            self._open_web,
            variant="primary",
        ).pack(side="right")

    def _build_admin(self, parent):
        admin = get_web_admin()
        box = self._card(parent, _t("desktop_administrator"), _t("desktop_admin_summary_help"), grid=(0, 0, (0, 7)))
        top = tk.Frame(box, bg=SURFACE)
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text=_t("desktop_status"), bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        self._badge(top, "admin")
        self._info_line(box, _t("desktop_username"), admin[1] if admin else "-")
        self._info_line(box, _t("desktop_password"), "", secret=bool(admin))
        self._button(
            box,
            _t("desktop_change_credentials") if admin else _t("desktop_create_admin"),
            self._open_admin_dialog,
            primary=True,
        ).pack(anchor="e", pady=(10, 0))

    def _build_telegram(self, parent):
        box = self._card(parent, "Telegram", _t("desktop_telegram_summary_help"), grid=(0, 1, (7, 0)))
        top = tk.Frame(box, bg=SURFACE)
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text=_t("desktop_status"), bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        self._badge(top, "telegram")
        secrets_data = load_secrets()
        self._info_line(
            box,
            "Bot Token",
            SECRET_MASK if secrets_data.get("telegram_bot_token") else _t("desktop_not_configured"),
        )
        self._info_line(
            box,
            "Authorized User ID",
            PASSWORD_MASK if secrets_data.get("telegram_user_id") else _t("desktop_not_configured"),
        )
        self._button(box, _t("desktop_configure"), self._open_telegram_dialog, variant="primary").pack(anchor="e", pady=(10, 0))

    def _build_voice(self, parent):
        settings = load_settings()
        box = self._card(parent, _t("desktop_voice_control"), _t("desktop_voice_summary_help"), grid=(0, 0, (0, 7)))
        top = tk.Frame(box, bg=SURFACE)
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text=_t("desktop_status"), bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        self._badge(top, "voice")
        self._info_line(box, _t("desktop_hotkey"), settings["voice"]["hotkey"].upper())
        self._button(box, _t("desktop_configure"), self._open_voice_dialog, variant="primary").pack(anchor="e", pady=(10, 0))

    def _build_quick_access(self, parent):
        box = self._card(parent, _t("desktop_quick_actions"), _t("desktop_quick_actions_help"), grid=(0, 1, (7, 0)))

        self._button(
            box,
            _t("desktop_local_admin_chat"),
            self._open_local_admin,
            variant="primary",
        ).pack(fill="x", pady=(0, 8))

        tray_row = tk.Frame(box, bg=SURFACE)
        tray_row.pack(fill="x", pady=(0, 8))
        self._button(
            tray_row,
            _t("desktop_run_in_background"),
            self._send_to_tray,
            variant="secondary",
        ).pack(side="left", fill="x", expand=True)
        self._info_button(
            tray_row,
            _t("desktop_tray_info"),
        ).pack(side="right", padx=(7, 0), pady=7)

        self._button(
            box,
            _t("desktop_web_settings"),
            self._open_settings,
            variant="neutral",
        ).pack(fill="x")

    def _change_language(self, event=None):
        language = "en" if self.language.get().startswith("English") else "tr"
        update_settings({"general": {"language": language}})
        self._build()
        self._test_ollama_async()

    def _open_modal(self, title, width=560, height=480):
        window = tk.Toplevel(self.root)
        window.title(title)
        self._apply_window_icon(window)
        window.geometry(f"{width}x{height}")
        window.minsize(width, height)
        window.configure(bg=BG)
        window.transient(self.root)
        window.grab_set()
        card = tk.Frame(window, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="both", expand=True, padx=18, pady=18)
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=22, pady=22)
        return window, inner

    def _modal_field(self, parent, label, variable, show=None, helper=None):
        tk.Label(parent, text=label, bg=SURFACE, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        entry = self._entry(parent, variable, show=show)
        entry.pack(fill="x", ipady=8, pady=(5, 3))
        if helper:
            tk.Label(parent, text=helper, bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), wraplength=470, justify="left").pack(anchor="w", pady=(0, 10))
        else:
            tk.Frame(parent, bg=SURFACE, height=8).pack()
        return entry

    def _open_name_dialog(self):
        window, body = self._open_modal(_t("desktop_agent_name"), 520, 300)
        value = StringVar(value=self.agent_name.get())
        tk.Label(body, text=_t("desktop_agent_name"), bg=SURFACE, fg=TEXT, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(body, text=_t("desktop_agent_name_help"), bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), wraplength=450, justify="left").pack(anchor="w", pady=(5, 16))
        self._modal_field(body, _t("desktop_agent_name"), value)

        def save():
            name = value.get().strip() or DEFAULT_AGENT_NAME
            update_settings({"general": {"agent_name": name}})
            self.agent_name.set(name)
            self._sync_window_identity()
            window.destroy()

        self._button(body, _t("desktop_save"), save, variant="primary").pack(anchor="e", pady=(8, 0))

    def _open_ollama_dialog(self):
        settings = load_settings()
        window, body = self._open_modal("Ollama", 620, 540)
        host = StringVar(value=settings["model"]["ollama_host"])
        model = StringVar(value=settings["model"]["chat_model"])
        status = StringVar(value="")

        tk.Label(body, text="Ollama", bg=SURFACE, fg=TEXT, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(body, text=_t("desktop_ollama_dialog_help"), bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), wraplength=530, justify="left").pack(anchor="w", pady=(5, 16))
        self._modal_field(body, _t("desktop_ollama_host"), host)
        self._modal_field(body, _t("desktop_chat_model"), model)
        self._info_line(body, _t("desktop_embedding_model"), DEFAULT_EMBEDDING_MODEL)
        tk.Label(body, textvariable=status, bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), wraplength=500, justify="left").pack(anchor="w", pady=(10, 8))

        actions = tk.Frame(body, bg=SURFACE)
        actions.pack(fill="x", pady=(8, 0))

        def install_missing():
            status.set(_t("desktop_installing"))

            def worker():
                try:
                    response = requests.get(f"{host.get().strip().rstrip('/')}/api/tags", timeout=5)
                    response.raise_for_status()
                    installed = [
                        str(item.get("name") or item.get("model"))
                        for item in response.json().get("models", [])
                        if isinstance(item, dict) and (item.get("name") or item.get("model"))
                    ]
                    missing = []
                    chat_name = model.get().strip()
                    if not _model_installed(chat_name, installed):
                        missing.append(chat_name)
                    if not _model_installed(DEFAULT_EMBEDDING_MODEL, installed):
                        missing.append(DEFAULT_EMBEDDING_MODEL)
                    for name in missing:
                        import subprocess
                        result = subprocess.run(["ollama", "pull", name], capture_output=True, text=True, timeout=7200, check=False)
                        if result.returncode != 0:
                            self.root.after(0, lambda: status.set(_t("desktop_install_failed")))
                            return
                    self.root.after(0, lambda: status.set(_t("desktop_installed")))
                    self.root.after(0, self._test_ollama_async)
                except (requests.RequestException, OSError):
                    self.root.after(0, lambda: status.set(_t("desktop_install_failed")))

            threading.Thread(target=worker, daemon=True).start()

        def save():
            if not model.get().strip():
                status.set(_t("desktop_chat_model_required"))
                return
            update_settings({"model": {"ollama_host": host.get().strip().rstrip("/"), "chat_model": model.get().strip()}})
            window.destroy()
            self._build()
            self._test_ollama_async()

        install_group = tk.Frame(actions, bg=SURFACE)
        install_group.pack(side="left")
        self._button(
            install_group,
            _t("desktop_install_models"),
            install_missing,
            variant="secondary",
        ).pack(side="left")
        self._info_button(
            install_group,
            _t("desktop_install_models_info", model=DEFAULT_EMBEDDING_MODEL),
        ).pack(side="left", padx=(6, 0), pady=7)
        self._button(actions, _t("desktop_save_changes"), save, variant="primary").pack(side="right")

    def _open_web_network_dialog(self):
        settings = load_settings()
        window, body = self._open_modal(
            _t("desktop_network_settings"),
            620,
            540,
        )

        access_labels = {
            _t("desktop_web_access_local"): "local",
            _t("desktop_web_access_lan"): "lan",
        }
        selected_access = StringVar(
            value=(
                _t("desktop_web_access_lan")
                if settings["web"]["access"] == "lan"
                else _t("desktop_web_access_local")
            )
        )
        port = StringVar(
            value=str(settings["web"]["port"])
        )
        preview = StringVar(
            value=self._web_display_address(settings)
        )
        status = StringVar(value="")

        footer = tk.Frame(
            body,
            bg=SURFACE_ALT,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        footer.pack(
            side="bottom",
            fill="x",
            pady=(14, 0),
        )

        footer_actions = tk.Frame(
            footer,
            bg=SURFACE_ALT,
        )
        footer_actions.pack(
            fill="x",
            padx=12,
            pady=10,
        )

        self._button(
            footer_actions,
            _t("desktop_cancel"),
            window.destroy,
            variant="neutral",
        ).pack(side="right")

        content = tk.Frame(
            body,
            bg=SURFACE,
        )
        content.pack(
            side="top",
            fill="both",
            expand=True,
        )

        tk.Label(
            content,
            text=_t("desktop_network_settings"),
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")

        tk.Label(
            content,
            text=_t("desktop_network_settings_help"),
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 9),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(5, 16))

        tk.Label(
            content,
            text=_t("desktop_network_access"),
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")

        access_box = ttk.Combobox(
            content,
            textvariable=selected_access,
            values=tuple(access_labels),
            state="readonly",
            style="Modern.TCombobox",
        )
        access_box.pack(fill="x", pady=(5, 12))

        self._modal_field(
            content,
            _t("desktop_web_port"),
            port,
        )

        preview_card = tk.Frame(
            content,
            bg=SURFACE_ALT,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        preview_card.pack(
            fill="x",
            pady=(4, 12),
        )

        tk.Label(
            preview_card,
            text=_t("desktop_connection_address"),
            bg=SURFACE_ALT,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(
            anchor="w",
            padx=12,
            pady=(10, 2),
        )

        tk.Label(
            preview_card,
            textvariable=preview,
            bg=SURFACE_ALT,
            fg=TEXT,
            font=("Segoe UI", 10, "bold"),
        ).pack(
            anchor="w",
            padx=12,
            pady=(0, 10),
        )

        tk.Label(
            content,
            text=_t("desktop_lan_security_help"),
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 9),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        tk.Label(
            content,
            textvariable=status,
            bg=SURFACE,
            fg=DANGER_TEXT,
            font=("Segoe UI", 9),
            wraplength=510,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        def refresh_preview(event=None):
            try:
                port_value = int(port.get().strip())
            except ValueError:
                preview.set("-")
                return

            if not 1024 <= port_value <= 65535:
                preview.set("-")
                return

            if access_labels.get(selected_access.get()) == "lan":
                lan_ip = self._get_lan_ip()
                preview.set(
                    f"http://{lan_ip}:{port_value}"
                    if lan_ip
                    else _t("desktop_lan_address_unavailable")
                )
            else:
                preview.set(
                    f"http://127.0.0.1:{port_value}"
                )

        access_box.bind(
            "<<ComboboxSelected>>",
            refresh_preview,
        )
        port.trace_add(
            "write",
            lambda *args: refresh_preview(),
        )

        def finish_save(success):
            self._build()
            self._test_ollama_async()

            if not success:
                messagebox.showerror(
                    self.agent_name.get() or DEFAULT_AGENT_NAME,
                    _t("desktop_web_restart_failed"),
                )

        def save():
            access = access_labels.get(
                selected_access.get()
            )

            if access not in {"local", "lan"}:
                status.set(
                    _t("desktop_network_access_invalid")
                )
                return

            try:
                port_value = int(
                    port.get().strip()
                )
            except ValueError:
                status.set(
                    _t("desktop_web_port_invalid")
                )
                return

            if not 1024 <= port_value <= 65535:
                status.set(
                    _t("desktop_web_port_invalid")
                )
                return

            was_running = self.web_running()

            update_settings(
                {
                    "web": {
                        "access": access,
                        "port": port_value,
                    }
                }
            )
            window.destroy()

            if not was_running:
                finish_save(True)
                return

            def worker():
                stopped = bool(
                    self.stop_web()
                )
                started = False

                if stopped:
                    started = bool(
                        self.start_web(
                            load_settings(),
                            open_browser=False,
                        )
                    )

                self.root.after(
                    0,
                    lambda: finish_save(
                        stopped and started
                    ),
                )

            threading.Thread(
                target=worker,
                daemon=True,
            ).start()

        self._button(
            footer_actions,
            _t("desktop_apply"),
            save,
            variant="primary",
        ).pack(side="right", padx=(0, 8))

    def _open_admin_dialog(self):
        current = get_web_admin()
        window, body = self._open_modal(_t("desktop_administrator"), 560, 500)
        username = StringVar(value=current[1] if current else "")
        password = StringVar(value="")
        confirm = StringVar(value="")
        status = StringVar(value="")

        tk.Label(body, text=_t("desktop_administrator"), bg=SURFACE, fg=TEXT, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        helper = _t("desktop_admin_existing_modal_help") if current else _t("desktop_admin_new_modal_help")
        tk.Label(body, text=helper, bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), wraplength=480, justify="left").pack(anchor="w", pady=(5, 16))
        self._modal_field(body, _t("desktop_username"), username)
        self._modal_field(body, _t("desktop_new_password") if current else _t("desktop_password"), password, show="*")
        self._modal_field(body, _t("desktop_confirm_password"), confirm, show="*")
        tk.Label(body, textvariable=status, bg=SURFACE, fg=DANGER_TEXT, font=("Segoe UI", 9), wraplength=470, justify="left").pack(anchor="w", pady=(4, 8))

        def save():
            name = username.get().strip()
            pwd = password.get()
            conf = confirm.get()
            if len(name) < 3:
                status.set(_t("username_too_short"))
                return
            if not current and len(pwd) < 6:
                status.set(_t("password_too_short"))
                return
            if pwd and len(pwd) < 6:
                status.set(_t("password_too_short"))
                return
            if pwd != conf:
                status.set(_t("desktop_passwords_do_not_match"))
                return
            existing = get_user_by_username(name)
            if existing and (not current or int(existing[0]) != int(current[0])):
                status.set(_t("username_in_use"))
                return
            try:
                save_web_admin_credentials(name, pwd)
            except ValueError as error:
                status.set(str(error))
                return
            window.destroy()
            self._build()
            self._test_ollama_async()

        self._button(body, _t("desktop_save_admin") if current else _t("desktop_create_admin"), save, variant="primary").pack(anchor="e", pady=(8, 0))

    def _open_telegram_dialog(self):
        settings = load_settings()
        secrets_data = load_secrets()
        window, body = self._open_modal("Telegram", 600, 550)
        enabled = StringVar(
            value=_t("desktop_enabled")
            if settings["telegram"]["enabled"]
            else _t("desktop_disabled")
        )
        token = StringVar(value=secrets_data.get("telegram_bot_token", ""))
        user_id = StringVar(value=secrets_data.get("telegram_user_id", ""))
        status = StringVar(value="")

        tk.Label(
            body,
            text="Telegram",
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        tk.Label(
            body,
            text=_t("desktop_telegram_modal_help"),
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 9),
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(5, 16))

        tk.Label(
            body,
            text=_t("desktop_service_state"),
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")
        state_box = ttk.Combobox(
            body,
            textvariable=enabled,
            values=(
                _t("desktop_enabled"),
                _t("desktop_disabled"),
            ),
            state="readonly",
            style="Modern.TCombobox",
        )
        state_box.pack(fill="x", pady=(5, 12))

        def secret_field(label, variable):
            tk.Label(
                body,
                text=label,
                bg=SURFACE,
                fg=TEXT,
                font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w")

            row = tk.Frame(body, bg=SURFACE)
            row.pack(fill="x", pady=(5, 4))

            entry = self._entry(
                row,
                variable,
                show="•",
            )
            entry.pack(
                side="left",
                fill="x",
                expand=True,
                ipady=8,
            )

            visible = {"value": False}

            def toggle():
                visible["value"] = not visible["value"]
                entry.configure(
                    show=""
                    if visible["value"]
                    else "•"
                )
                button.configure(
                    text=_t("desktop_hide")
                    if visible["value"]
                    else _t("desktop_show")
                )

            button = self._button(
                row,
                _t("desktop_show"),
                toggle,
                variant="neutral",
            )
            button.pack(side="right", padx=(8, 0))

            tk.Label(
                body,
                text=_t("desktop_local_secret_help"),
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI", 9),
                wraplength=500,
                justify="left",
            ).pack(anchor="w", pady=(0, 10))

        secret_field("Bot Token", token)
        secret_field("Authorized User ID", user_id)

        tk.Label(
            body,
            textvariable=status,
            bg=SURFACE,
            fg=DANGER_TEXT,
            font=("Segoe UI", 9),
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(2, 8))

        def save():
            new_token = token.get().strip()
            new_id = user_id.get().strip()
            is_enabled = enabled.get() == _t("desktop_enabled")

            if new_id and not new_id.isdigit():
                status.set(_t("telegram_id_invalid"))
                return

            if is_enabled and not new_token:
                status.set(_t("telegram_token_required"))
                return

            if is_enabled and not new_id:
                status.set(_t("telegram_id_required"))
                return

            save_secrets(
                {
                    "telegram_bot_token": new_token,
                    "telegram_user_id": new_id,
                }
            )
            update_settings(
                {
                    "telegram": {
                        "enabled": is_enabled,
                    }
                }
            )
            window.destroy()
            self._build()
            self._test_ollama_async()

            def apply_connection():
                stopped = self.stop_telegram()

                if stopped and is_enabled:
                    self.start_telegram(self.agent)

                self.root.after(0, self._refresh_statuses)

            threading.Thread(
                target=apply_connection,
                daemon=True,
            ).start()

        self._button(
            body,
            _t("desktop_save_telegram"),
            save,
            variant="primary",
        ).pack(anchor="e", pady=(8, 0))

    def _open_voice_dialog(self):
        settings = load_settings()
        window, body = self._open_modal(_t("desktop_voice_control"), 580, 540)
        enabled = StringVar(value=_t("desktop_enabled") if settings["voice"]["enabled"] else _t("desktop_disabled"))
        hotkey = StringVar(value=settings["voice"]["hotkey"].upper())
        scope_values = {
            _t("desktop_voice_scope_global"): "global",
            _t("desktop_voice_scope_local"): "local_admin",
        }
        selected_scope = next(
            label
            for label, value in scope_values.items()
            if value == settings["voice"]["scope"]
        )
        scope = StringVar(value=selected_scope)
        status = StringVar(value=_t("desktop_hotkey_capture_help"))

        tk.Label(body, text=_t("desktop_voice_control"), bg=SURFACE, fg=TEXT, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(body, text=_t("desktop_voice_modal_help"), bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), wraplength=490, justify="left").pack(anchor="w", pady=(5, 16))

        tk.Label(body, text=_t("desktop_service_state"), bg=SURFACE, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        state_box = ttk.Combobox(body, textvariable=enabled, values=(_t("desktop_enabled"), _t("desktop_disabled")), state="readonly", style="Modern.TCombobox")
        state_box.pack(fill="x", pady=(5, 12))

        tk.Label(body, text=_t("desktop_voice_scope"), bg=SURFACE, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        scope_box = ttk.Combobox(body, textvariable=scope, values=tuple(scope_values), state="readonly", style="Modern.TCombobox")
        scope_box.pack(fill="x", pady=(5, 12))

        tk.Label(body, text=_t("desktop_hotkey"), bg=SURFACE, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        row = tk.Frame(body, bg=SURFACE)
        row.pack(fill="x", pady=(5, 4))
        hotkey_entry = self._entry(row, hotkey)
        hotkey_entry.pack(side="left", fill="x", expand=True, ipady=8)

        def stop_capture():
            self.hotkey_capture = False
            self.root.unbind_all("<KeyPress>")
            self.root.unbind_all("<KeyRelease>")

        def on_press(event):
            key = event.keysym
            modifier_map = {
                "Control_L": "Ctrl", "Control_R": "Ctrl", "Shift_L": "Shift", "Shift_R": "Shift",
                "Alt_L": "Alt", "Alt_R": "Alt", "Meta_L": "Cmd", "Meta_R": "Cmd", "Win_L": "Cmd", "Win_R": "Cmd",
            }
            if key in modifier_map:
                self.hotkey_modifiers.add(modifier_map[key])
                return "break"
            aliases = {"space": "Space", "Return": "Enter", "Escape": "Esc", "Tab": "Tab", "BackSpace": "Backspace", "Delete": "Delete", "Home": "Home", "End": "End", "Prior": "Page_Up", "Next": "Page_Down", "Insert": "Insert", "Left": "Left", "Right": "Right", "Up": "Up", "Down": "Down"}
            normalized = aliases.get(key, key)
            if len(normalized) == 1:
                normalized = normalized.upper()
            order = ["Ctrl", "Alt", "Shift", "Cmd"]
            modifiers = [name for name in order if name in self.hotkey_modifiers]
            value = "+".join(modifiers + [normalized])
            try:
                parse_hotkey(value)
            except ValueError:
                status.set(_t("desktop_hotkey_invalid"))
                return "break"
            hotkey.set(value)
            status.set(_t("desktop_hotkey_captured", hotkey=value))
            stop_capture()
            return "break"

        def on_release(event):
            modifier_map = {"Control_L": "Ctrl", "Control_R": "Ctrl", "Shift_L": "Shift", "Shift_R": "Shift", "Alt_L": "Alt", "Alt_R": "Alt", "Meta_L": "Cmd", "Meta_R": "Cmd", "Win_L": "Cmd", "Win_R": "Cmd"}
            if event.keysym in modifier_map:
                self.hotkey_modifiers.discard(modifier_map[event.keysym])
            return "break"

        def capture():
            self.hotkey_capture = True
            self.hotkey_modifiers.clear()
            status.set(_t("desktop_hotkey_listening"))
            self.root.bind_all("<KeyPress>", on_press)
            self.root.bind_all("<KeyRelease>", on_release)

        self._button(row, _t("desktop_capture_hotkey"), capture, variant="secondary").pack(side="right", padx=(8, 0))
        tk.Label(body, textvariable=status, bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), wraplength=480, justify="left").pack(anchor="w", pady=(0, 12))

        def save():
            try:
                parse_hotkey(hotkey.get().strip())
            except ValueError:
                status.set(_t("desktop_hotkey_invalid"))
                return
            is_enabled = enabled.get() == _t("desktop_enabled")
            update_settings({"voice": {
                "enabled": is_enabled,
                "hotkey": hotkey.get().strip(),
                "scope": scope_values[scope.get()],
            }})
            refresh_voice_hotkey(self.agent)
            stop_capture()
            window.destroy()
            self._build()
            self._test_ollama_async()

        window.protocol("WM_DELETE_WINDOW", lambda: (stop_capture(), window.destroy()))
        self._button(body, _t("desktop_save_voice"), save, variant="primary").pack(anchor="e", pady=(8, 0))

    def _test_ollama_async(self):
        settings = load_settings()
        host = settings["model"]["ollama_host"].rstrip("/")
        model = settings["model"]["chat_model"]
        self._set_badge("ollama", _t("desktop_checking"), "idle")

        def worker():
            try:
                response = requests.get(f"{host}/api/tags", timeout=5)
                response.raise_for_status()
                models = [
                    str(item.get("name") or item.get("model"))
                    for item in response.json().get("models", [])
                    if isinstance(item, dict) and (item.get("name") or item.get("model"))
                ]
                chat_ok = _model_installed(model, models)
                embedding_ok = _model_installed(DEFAULT_EMBEDDING_MODEL, models)
                if chat_ok and embedding_ok:
                    text, state = _t("desktop_ready"), "success"
                elif not chat_ok and not embedding_ok:
                    text, state = _t("desktop_models_missing_short"), "error"
                elif not chat_ok:
                    text, state = _t("desktop_chat_missing_short"), "error"
                else:
                    text, state = _t("desktop_embedding_missing_short"), "error"
            except requests.RequestException:
                text, state = _t("desktop_offline"), "error"
            self.root.after(0, lambda: self._set_badge("ollama", text, state))

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_web(self):
        target_enabled = not self.web_running()
        self.web_action_button.configure(state="disabled")
        self._set_badge(
            "web",
            _t("desktop_starting")
            if target_enabled
            else _t("desktop_stopping"),
            "warning",
        )

        def worker():
            if target_enabled:
                success = bool(
                    self.start_web(
                        load_settings(),
                        open_browser=False,
                    )
                )
            else:
                success = bool(self.stop_web())

            if success:
                update_settings(
                    {
                        "web": {
                            "enabled": target_enabled,
                        }
                    }
                )

            self.root.after(
                0,
                lambda: self._web_toggle_finished(
                    target_enabled,
                    success,
                ),
            )

        threading.Thread(
            target=worker,
            daemon=True,
        ).start()

    def _web_toggle_finished(self, target_enabled, success):
        if not success:
            self._set_badge(
                "web",
                _t("desktop_web_action_failed"),
                "error",
            )

        self.web_action_button.configure(state="normal")
        self._refresh_statuses()

    def _refresh_statuses(self):
        settings = load_settings()
        secrets_data = load_secrets()
        admin = get_web_admin()

        if self.web_running():
            self._set_badge("web", _t("desktop_running"), "success")
            self.web_action_button.configure(
                text=_t("desktop_disable"),
                bg="#341b1f",
                fg="#ffadb6",
                activebackground="#432228",
                activeforeground="#ffc0c7",
                highlightbackground="#603039",
                highlightcolor="#603039",
            )
        else:
            self._set_badge("web", _t("desktop_stopped"), "idle")
            self.web_action_button.configure(
                text=_t("desktop_enable"),
                bg="#eef4ff",
                fg="#254fa3",
                activebackground="#e2ebff",
                activeforeground="#254fa3",
                highlightbackground="#34445e",
                highlightcolor="#cbd9f5",
            )

        self._set_badge("admin", _t("desktop_configured") if admin else _t("desktop_not_configured"), "success" if admin else "warning")
        telegram_ready = bool(secrets_data.get("telegram_bot_token") and secrets_data.get("telegram_user_id"))
        if not settings["telegram"]["enabled"]:
            self._set_badge("telegram", _t("desktop_inactive"), "idle")
        elif self.telegram_status() == "running":
            self._set_badge("telegram", _t("desktop_active"), "success")
        elif self.telegram_status() == "starting":
            self._set_badge("telegram", _t("desktop_starting"), "warning")
            self.root.after(500, self._refresh_statuses)
        elif telegram_ready:
            self._set_badge("telegram", _t("desktop_connection_failed_plain"), "error")
        else:
            self._set_badge("telegram", _t("desktop_not_configured"), "warning")
        voice_status = get_voice_status()
        if voice_status == "running":
            self._set_badge("voice", _t("desktop_active"), "success")
        elif voice_status == "waiting":
            self._set_badge("voice", _t("desktop_voice_waiting"), "warning")
        else:
            self._set_badge("voice", _t("desktop_inactive"), "idle")

    def _ensure_web(self):
        settings = load_settings()

        if not self.web_running():
            if not self.start_web(
                settings,
                open_browser=False,
            ):
                return None

            update_settings(
                {
                    "web": {
                        "enabled": True,
                    }
                }
            )

        return f"http://127.0.0.1:{settings['web']['port']}"

    def _open_web(self):
        url = self._ensure_web()

        if url:
            webbrowser.open(url)
        else:
            messagebox.showerror(
                "AI Agent",
                _t("desktop_web_start_failed"),
            )

    def _open_settings(self):
        url = self._ensure_web()

        if url:
            webbrowser.open(f"{url}/settings")
        else:
            messagebox.showerror(
                "AI Agent",
                _t("desktop_web_start_failed"),
            )

    def _tray_labels(self):
        return {
            "open": _t("desktop_tray_open"),
            "local_admin": _t("desktop_local_admin_chat"),
            "open_web": _t("desktop_open_web"),
            "web_settings": _t("desktop_web_settings"),
            "exit": _t("desktop_tray_exit"),
        }

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _send_to_tray(self):
        if self.tray is None:
            self.tray = TrayController(
                self.root,
                self._tray_labels(),
                self._show_window,
                self._open_local_admin,
                self._open_web,
                self._open_settings,
                self._exit_application,
                title=self.agent_name.get(),
            )

        if not self.tray.start():
            self.tray = None
            messagebox.showerror(
                "AI Agent",
                _t("desktop_tray_dependency_missing"),
            )
            return

        self.root.withdraw()

    def _exit_application(self):
        if self.exiting:
            return

        self.exiting = True
        set_voice_message_handler(None)

        if self.tray is not None:
            self.tray.stop()

        self.root.destroy()

    def _poll_voice_messages(self):
        if self.exiting:
            return

        while True:
            try:
                text = self.voice_messages.get_nowait()
            except queue.Empty:
                break

            if self.local_admin_voice_target is None:
                if load_settings()["voice"]["scope"] != "global":
                    continue
                self._open_local_admin()

            if self.local_admin_voice_target is not None:
                self.local_admin_voice_target(text)

        self.root.after(100, self._poll_voice_messages)

    def _open_local_admin(self):
        if (
            self.local_admin_window is not None
            and self.local_admin_window.winfo_exists()
        ):
            self.local_admin_window.deiconify()
            self.local_admin_window.lift()
            self.local_admin_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.local_admin_window = window
        set_local_admin_active(True)
        self._refresh_statuses()

        def close_window():
            if not window.winfo_exists():
                return

            self.local_admin_window = None
            self.local_admin_voice_target = None
            set_local_admin_active(False)

            if (
                self.system_history_window is not None
                and self.system_history_window.winfo_exists()
            ):
                self.system_history_window.destroy()

            self.system_history_window = None
            window.destroy()
            self._refresh_statuses()

        window.protocol("WM_DELETE_WINDOW", close_window)
        window.title(
            f"{self.agent_name.get()} - {_t('desktop_local_admin_chat')}"
        )
        self._apply_window_icon(window)
        window.geometry("900x680")
        window.minsize(760, 560)
        window.configure(bg="#090b10")

        header = tk.Frame(
            window,
            bg="#0f1219",
            height=92,
            highlightthickness=1,
            highlightbackground="#242a36",
        )
        header.pack(fill="x")
        header.pack_propagate(False)

        title_box = tk.Frame(
            header,
            bg="#0f1219",
        )
        title_box.pack(
            side="left",
            padx=26,
            pady=16,
        )

        monitor_button = tk.Button(
            header,
            text=(
                "Sistem ve Geçmiş"
                if get_language() == "tr"
                else "System and History"
            ),
            command=lambda: self._open_system_history(
                window
            ),
            font=("Segoe UI Semibold", 9),
            bg="#1d2738",
            fg="#d8e2f2",
            activebackground="#26344b",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=14,
            pady=9,
            highlightthickness=1,
            highlightbackground="#34445e",
        )
        monitor_button.pack(
            side="right",
            padx=24,
            pady=27,
        )
        tk.Label(
            title_box,
            text=_t("desktop_local_admin_chat"),
            bg="#0f1219",
            fg="#f5f7fb",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text=_t("desktop_local_admin_chat_help"),
            bg="#0f1219",
            fg="#8f96a6",
            font=("Segoe UI", 9),
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        body = tk.Frame(
            window,
            bg="#090b10",
        )
        body.pack(
            fill="both",
            expand=True,
        )

        canvas = tk.Canvas(
            body,
            bg="#090b10",
            highlightthickness=0,
            bd=0,
        )
        scrollbar = tk.Scrollbar(
            body,
            orient="vertical",
            command=canvas.yview,
            bg="#252b36",
            troughcolor="#0d1118",
            activebackground="#343c4a",
            relief="flat",
            bd=0,
            highlightthickness=0,
            width=11,
        )
        canvas.configure(
            yscrollcommand=scrollbar.set,
        )
        canvas.pack(
            side="left",
            fill="both",
            expand=True,
        )
        scrollbar.pack(
            side="right",
            fill="y",
        )

        def draw_background(event=None):
            canvas.delete("background")

            width = max(
                canvas.winfo_width(),
                900,
            )
            height = max(
                canvas.winfo_height(),
                700,
            )
            bands = 72

            for index in range(bands):
                ratio = index / max(
                    bands - 1,
                    1,
                )
                red = int(
                    17 * (1 - ratio)
                    + 7 * ratio
                )
                green = int(
                    20 * (1 - ratio)
                    + 8 * ratio
                )
                blue = int(
                    28 * (1 - ratio)
                    + 11 * ratio
                )
                color = (
                    f"#{red:02x}"
                    f"{green:02x}"
                    f"{blue:02x}"
                )
                y1 = int(
                    height * index / bands
                )
                y2 = int(
                    height * (index + 1) / bands
                ) + 1

                canvas.create_rectangle(
                    0,
                    y1,
                    width,
                    y2,
                    fill=color,
                    outline=color,
                    tags="background",
                )

            canvas.create_oval(
                -260,
                -250,
                520,
                430,
                fill="#19172f",
                outline="",
                stipple="gray50",
                tags="background",
            )
            canvas.create_oval(
                width - 420,
                -180,
                width + 220,
                420,
                fill="#102631",
                outline="",
                stipple="gray50",
                tags="background",
            )
            canvas.create_oval(
                width * 0.28,
                height - 100,
                width * 0.88,
                height + 520,
                fill="#21152b",
                outline="",
                stipple="gray50",
                tags="background",
            )
            canvas.tag_lower(
                "background"
            )

        draw_background()

        messages = []
        bubble_widgets = []
        resize_job = {"id": None}

        def scroll_chat(event):
            canvas.yview_scroll(
                int(-event.delta / 120),
                "units",
            )
            return "break"

        def render_messages():
            canvas.configure(bg="#090b10")
            for widget in bubble_widgets:
                widget.destroy()
            bubble_widgets.clear()
            canvas.delete("message")

            width = max(
                canvas.winfo_width(),
                720,
            )
            y = 28

            for text, own in messages:
                bubble_bg = (
                    "#313746"
                    if own
                    else "#181c25"
                )
                bubble_border = (
                    "#454c5d"
                    if own
                    else "#2b303c"
                )
                bubble = tk.Frame(
                    canvas,
                    bg=bubble_bg,
                    highlightthickness=1,
                    highlightbackground=bubble_border,
                )
                bubble_widgets.append(bubble)

                message_label = tk.Label(
                    bubble,
                    text=text,
                    bg=bubble_bg,
                    fg="#f7f8fb" if own else "#e7e9ee",
                    font=("Segoe UI", 10),
                    wraplength=min(
                        570,
                        int(width * 0.66),
                    ),
                    justify="left",
                    padx=15,
                    pady=11,
                )
                message_label.pack()
                bubble.bind(
                    "<MouseWheel>",
                    scroll_chat,
                )
                message_label.bind(
                    "<MouseWheel>",
                    scroll_chat,
                )

                bubble.update_idletasks()
                bubble_height = bubble.winfo_reqheight()
                x = width - 28 if own else 28
                anchor = "ne" if own else "nw"

                canvas.create_window(
                    x,
                    y,
                    window=bubble,
                    anchor=anchor,
                    tags="message",
                )
                y += bubble_height + 14

            canvas.configure(
                scrollregion=(
                    0,
                    0,
                    width,
                    max(
                        y + 40,
                        canvas.winfo_height(),
                    ),
                )
            )
            window.after(
                20,
                lambda: canvas.yview_moveto(1.0),
            )

        def schedule_render(event=None):
            if resize_job["id"] is not None:
                window.after_cancel(
                    resize_job["id"]
                )
            resize_job["id"] = window.after(
                80,
                render_messages,
            )

        def handle_canvas_resize(event=None):
            draw_background()
            schedule_render()

        canvas.bind(
            "<Configure>",
            handle_canvas_resize,
        )
        canvas.bind(
            "<MouseWheel>",
            scroll_chat,
        )

        tool_values = {
            _t("desktop_tool_auto"): None,
            _t("desktop_tool_create"): "create",
            _t("desktop_tool_read"): "read",
            _t("desktop_tool_write"): "write",
            _t("desktop_tool_search"): "search-files",
            _t("desktop_tool_list"): "list",
            _t("desktop_tool_open"): "open",
            _t("desktop_tool_rename"): "rename",
            _t("desktop_tool_move"): "move",
            _t("desktop_tool_delete"): "delete",
            _t("desktop_tool_telegram_message"): "telegram-message",
            _t("desktop_tool_telegram_file"): "telegram-file",
            _t("desktop_tool_rag"): "rag",
            _t("desktop_tool_history"): "history",
        }
        tool_choice = StringVar(value=_t("desktop_tool_auto"))
        tool_bar = tk.Frame(window, bg="#090b10")
        tool_bar.pack(fill="x", padx=22, pady=(12, 8))
        tk.Label(
            tool_bar,
            text=_t("desktop_tools"),
            bg="#090b10",
            fg="#8f96a6",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=(0, 10))
        tool_panel = tk.Frame(
            window,
            bg="#11151d",
            highlightthickness=1,
            highlightbackground="#2a303c",
        )

        def hide_tools():
            tool_panel.pack_forget()
            tool_toggle.configure(
                text=f"{tool_choice.get()}  ▾"
            )

        def select_tool(label):
            tool_choice.set(label)
            hide_tools()

        def toggle_tools():
            if tool_panel.winfo_manager():
                hide_tools()
                return

            tool_panel.pack(
                after=tool_bar,
                fill="x",
                padx=22,
                pady=(0, 8),
            )
            tool_toggle.configure(
                text=f"{tool_choice.get()}  ▴"
            )

        tool_toggle = tk.Button(
            tool_bar,
            text=f"{tool_choice.get()}  ▾",
            command=toggle_tools,
            font=("Segoe UI", 9),
            bg="#171c26",
            fg="#e5e9f2",
            activebackground="#232a37",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            cursor="hand2",
            anchor="w",
            padx=13,
            pady=8,
        )
        tool_toggle.pack(
            side="left",
            fill="x",
            expand=True,
        )

        for column in range(4):
            tool_panel.grid_columnconfigure(
                column,
                weight=1,
            )

        for index, label in enumerate(tool_values):
            tk.Button(
                tool_panel,
                text=label,
                command=lambda value=label: select_tool(value),
                font=("Segoe UI", 9),
                bg="#171c26",
                fg="#dce1eb",
                activebackground="#26344b",
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
                cursor="hand2",
                anchor="w",
                padx=10,
                pady=8,
            ).grid(
                row=index // 4,
                column=index % 4,
                sticky="ew",
                padx=4,
                pady=4,
            )

        composer_outer = tk.Frame(
            window,
            bg="#090b10",
        )
        composer_outer.pack(
            fill="x",
            padx=22,
            pady=(0, 22),
        )
        composer = tk.Frame(
            composer_outer,
            bg="#14171f",
            highlightthickness=1,
            highlightbackground="#2b303c",
        )
        composer.pack(
            fill="x",
            padx=1,
            pady=1,
        )

        entry = tk.Entry(
            composer,
            font=("Segoe UI", 11),
            bg="#14171f",
            fg="#f5f7fb",
            disabledbackground="#14171f",
            disabledforeground="#aeb6c5",
            insertbackground="#f5f7fb",
            relief="flat",
            bd=0,
        )
        entry.pack(
            side="left",
            fill="x",
            expand=True,
            ipady=14,
            padx=(16, 10),
        )

        def add_message(text, own=False):
            messages.append(
                (
                    str(text),
                    own,
                )
            )
            render_messages()

        def finish(response):
            add_message(
                response,
                own=False,
            )
            entry.configure(
                state="normal",
            )
            send_button.configure(
                state="normal",
            )
            entry.focus_set()

        def send(event=None, message=None):
            message = (
                entry.get().strip()
                if message is None
                else str(message).strip()
            )

            if not message:
                return

            entry.delete(
                0,
                "end",
            )
            add_message(
                message,
                own=True,
            )
            entry.configure(
                state="disabled",
            )
            send_button.configure(
                state="disabled",
            )
            selected_tool = tool_values[tool_choice.get()]

            def worker():
                try:
                    response = self.agent.run(
                        message,
                        source="terminal",
                        selected_tool=selected_tool,
                    )
                except Exception as error:
                    response = (
                        f"{_t('request_failed')} "
                        f"({type(error).__name__})"
                    )

                window.after(
                    0,
                    lambda: finish(response),
                )

            threading.Thread(
                target=worker,
                daemon=True,
            ).start()

        voice_state = {"recording": False}

        def transcribe_path(path, remove_after=False):
            try:
                if os.path.getsize(path) > 25 * 1024 * 1024:
                    raise ValueError("Audio file exceeds the 25 MB limit.")
                text = transcribe_audio(path, get_language())
                if text:
                    def insert_transcript():
                        entry.configure(state="normal")
                        entry.delete(0, "end")
                        entry.insert(0, text)
                        entry.focus_set()

                    window.after(0, insert_transcript)
                else:
                    window.after(0, lambda: add_message(
                        "Ses algılanamadı." if get_language() == "tr" else "No speech detected.",
                        own=False,
                    ))
            except Exception as error:
                window.after(0, lambda: add_message(
                    f"Ses işlenemedi ({type(error).__name__}).",
                    own=False,
                ))
            finally:
                try:
                    if remove_after:
                        os.remove(path)
                except OSError:
                    pass

        def toggle_voice_recording():
            if not voice_state["recording"]:
                if not start_recording():
                    add_message(
                        "Mikrofon kaydı başlatılamadı." if get_language() == "tr" else "Microphone recording could not start.",
                        own=False,
                    )
                    return
                voice_state["recording"] = True
                voice_button.configure(
                    text="■",
                    bg="#7e3038",
                    activebackground="#99404a",
                )
                return

            path = stop_recording()
            voice_state["recording"] = False
            voice_button.configure(
                text="🎙",
                bg="#29344a",
                activebackground="#364763",
            )
            if path:
                threading.Thread(
                    target=transcribe_path,
                    args=(path, True),
                    daemon=True,
                ).start()

        def upload_voice_file():
            path = filedialog.askopenfilename(
                parent=window,
                title="Ses dosyası seç" if get_language() == "tr" else "Select audio file",
                filetypes=[
                    ("Audio files", "*.wav *.mp3 *.m4a *.webm *.ogg"),
                    ("All files", "*.*"),
                ],
            )
            if path:
                threading.Thread(
                    target=transcribe_path,
                    args=(path, False),
                    daemon=True,
                ).start()

        voice_menu = tk.Menu(
            window,
            tearoff=False,
            bg="#171c26",
            fg="#e5e9f2",
            activebackground="#26344b",
            activeforeground="#ffffff",
        )
        voice_menu.add_command(
            label="Kaydı başlat / durdur" if get_language() == "tr" else "Start / stop recording",
            command=toggle_voice_recording,
        )
        voice_menu.add_command(
            label="Ses dosyası gönder" if get_language() == "tr" else "Upload audio file",
            command=upload_voice_file,
        )

        def open_voice_menu():
            voice = load_settings().get("voice", {})
            if not voice.get("enabled", False):
                messagebox.showinfo(
                    "Voice Control",
                    (
                        "Voice Control kapalı. Ayarlardan etkinleştirin."
                        if get_language() == "tr"
                        else "Voice Control is disabled. Enable it in Settings."
                    ),
                    parent=window,
                )
                return
            if voice_state["recording"]:
                toggle_voice_recording()
                return
            voice_menu.tk_popup(
                voice_button.winfo_rootx(),
                voice_button.winfo_rooty() - 74,
            )

        voice_button = tk.Button(
            composer,
            text="🎙",
            command=open_voice_menu,
            font=("Segoe UI", 12, "bold"),
            bg="#29344a",
            fg="#e5e9f2",
            activebackground="#364763",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=10,
            pady=7,
        )
        voice_button.pack(side="right", padx=(0, 6), pady=9)

        def refresh_voice_button():
            if not window.winfo_exists():
                return
            voice = load_settings().get("voice", {})
            enabled = bool(voice.get("enabled", False))
            hotkey = str(voice.get("hotkey", "f8")).upper()
            if not enabled and voice_state["recording"]:
                toggle_voice_recording()
            voice_button.configure(
                state="normal",
                text="■" if voice_state["recording"] else "🎙",
                bg="#29344a" if enabled else "#1b202a",
                fg="#e5e9f2" if enabled else "#657083",
                activebackground="#364763" if enabled else "#1b202a",
                cursor="hand2",
            )
            voice_menu.entryconfigure(
                0,
                label=(
                    f"Kaydı başlat / durdur ({hotkey})"
                    if get_language() == "tr"
                    else f"Start / stop recording ({hotkey})"
                ),
            )
            window.after(500, refresh_voice_button)

        refresh_voice_button()

        send_button = tk.Button(
            composer,
            text=_t("desktop_send"),
            command=send,
            font=("Segoe UI Semibold", 9),
            bg="#737b89",
            fg="#11141c",
            activebackground="#8a93a2",
            activeforeground="#11141c",
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=17,
            pady=10,
        )
        send_button.pack(
            side="right",
            padx=(0, 10),
            pady=9,
        )

        entry.bind(
            "<Return>",
            send,
        )
        self.local_admin_voice_target = lambda text: send(message=text)
        entry.focus_set()
        if self.agent.reset_conversation(
            source="terminal"
        ):
            add_message(
                _t("desktop_local_admin_welcome"),
                own=False,
            )
        else:
            add_message(
                (
                    "Agent halen bir isteği işliyor. Ayrıntıyı "
                    "Sistem ve Geçmiş ekranından izleyebilirsiniz."
                    if get_language() == "tr"
                    else "The Agent is still processing a request. "
                    "You can inspect it in System and History."
                ),
                own=False,
            )

    def _open_system_history(self, parent):
        if (
            self.system_history_window is not None
            and self.system_history_window.winfo_exists()
        ):
            self.system_history_window.deiconify()
            self.system_history_window.lift()
            self.system_history_window.focus_force()
            return

        window = tk.Toplevel(parent)
        self.system_history_window = window
        window.title(
            "Sistem ve Geçmiş"
            if get_language() == "tr"
            else "System and History"
        )
        window.geometry("980x700")
        window.minsize(820, 560)
        window.configure(bg=BG)
        self._apply_window_icon(window)

        state = {
            "page": "monitor",
            "history": "all",
            "after": None,
        }
        history_buttons = {}

        def ui(tr, en):
            return tr if get_language() == "tr" else en

        def close_window():
            if state["after"] is not None:
                try:
                    window.after_cancel(state["after"])
                except tk.TclError:
                    pass
            self.system_history_window = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_window)

        header = tk.Frame(
            window,
            bg="#0f1219",
            height=90,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text=ui("Local Admin Merkezi", "Local Admin Center"),
            bg="#0f1219",
            fg=TEXT,
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w", padx=26, pady=(16, 2))
        tk.Label(
            header,
            text=ui(
                "Konuşma kayıtları ve canlı sistem durumu",
                "Conversation records and live system status",
            ),
            bg="#0f1219",
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=26)

        nav = tk.Frame(window, bg=BG)
        nav.pack(fill="x", padx=22, pady=(16, 8))
        content = tk.Frame(
            window,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        content.pack(
            fill="both",
            expand=True,
            padx=22,
            pady=(0, 22),
        )
        filters = tk.Frame(content, bg=SURFACE)
        clear_bar = tk.Frame(content, bg=SURFACE)
        text_frame = tk.Frame(content, bg=SURFACE)
        clear_bar.pack(side="bottom", fill="x", padx=12, pady=12)
        text_frame.pack(fill="both", expand=True)
        output = tk.Text(
            text_frame,
            bg="#0d1016",
            fg="#dfe4ee",
            insertbackground=TEXT,
            selectbackground="#34445e",
            relief="flat",
            bd=0,
            wrap="word",
            font=("Consolas", 10),
            padx=18,
            pady=16,
            state="disabled",
        )
        scrollbar = tk.Scrollbar(
            text_frame,
            command=output.yview,
            bg=SURFACE_ALT,
            activebackground="#333a48",
            troughcolor="#0d1016",
            relief="flat",
            bd=0,
            width=11,
        )
        output.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        output.pack(side="left", fill="both", expand=True)

        def set_output(value):
            output.configure(state="normal")
            output.delete("1.0", "end")
            output.insert("1.0", value)
            output.configure(state="disabled")

        def user_name(user_id):
            if user_id is None:
                return ui("Guest", "Guest")
            try:
                row = get_user_by_id(user_id)
            except Exception:
                row = None
            if not row:
                return f"user_id={user_id}"
            return f"{row[1]} ({row[3]}, id={row[0]})"

        def source_name(source, user_id=None):
            if source == "terminal":
                return "Local Admin"
            if source == "telegram":
                suffix = f" · id={user_id}" if user_id is not None else ""
                return f"Telegram{suffix}"
            if source == "web":
                return f"Web · {user_name(user_id)}"
            return str(source or ui("Bilinmiyor", "Unknown"))

        event_names = {
            "request_started": ui("istek başladı", "request started"),
            "request_finished": ui("istek tamamlandı", "request finished"),
            "request_error": ui("istek hatası", "request error"),
            "request_blocked": ui("meşgul olduğu için reddedildi", "blocked while busy"),
            "connection_active": ui("bağlantı etkin", "connection active"),
            "connection_error": ui("bağlantı hatası", "connection error"),
            "connection_stopped": ui("bağlantı durdu", "connection stopped"),
            "message_error": ui("mesaj hatası", "message error"),
        }

        def render_monitor():
            if state["page"] != "monitor" or not window.winfo_exists():
                return
            snapshot = self.agent.get_system_snapshot()
            active = snapshot.get("active")
            lines = []

            if active:
                lines.extend((
                    ui("● AGENT MEŞGUL", "● AGENT BUSY"),
                    f"{ui('Kaynak', 'Source')}: "
                    f"{source_name(active['source'], active.get('user_id'))}",
                    f"{ui('Geçen süre', 'Elapsed')}: {active['elapsed']:.1f} sn",
                ))
            else:
                lines.append(ui("● AGENT BOŞTA", "● AGENT IDLE"))

            lines.extend(("", ui("SON SİSTEM OLAYLARI", "RECENT SYSTEM EVENTS"), ""))
            events = snapshot.get("events", [])
            if not events:
                lines.append(ui("Henüz sistem olayı yok.", "No system events yet."))

            for item in reversed(events):
                label = event_names.get(item["event"], item["event"])
                line = (
                    f"[{item['time']}] "
                    f"[{source_name(item['source'], item.get('user_id'))}] {label}"
                )
                if "elapsed" in item:
                    line += f" · {item['elapsed']:.1f} sn"
                if item.get("detail"):
                    line += f" · {item['detail']}"
                lines.append(line)

            set_output("\n".join(lines))
            state["after"] = window.after(750, render_monitor)

        def render_history():
            selected = state["history"]
            sections = []

            if selected in {"all", "terminal", "telegram"}:
                try:
                    rows = self.agent.memory.get_recent_messages(limit=200)
                except Exception as error:
                    rows = []
                    sections.append(
                        f"[MemoryError] {type(error).__name__}"
                    )

                rows = list(reversed(rows))

                for source in ("terminal", "telegram"):
                    if selected not in {"all", source}:
                        continue
                    source_rows = [row for row in rows if row[1] == source]
                    sections.append(
                        f"=== {source_name(source).upper()} ==="
                    )
                    if not source_rows:
                        sections.append(ui("Kayıt yok.", "No records."))
                    for role, _source, message in source_rows:
                        sections.append(f"{role}: {message}")
                    sections.append("")

            if selected in {"all", "web"}:
                sections.append("=== WEB ===")
                try:
                    web_rows = get_all_web_messages(limit=200)
                except Exception as error:
                    web_rows = []
                    sections.append(f"[WebDatabaseError] {type(error).__name__}")
                web_rows = list(reversed(web_rows))
                if not web_rows:
                    sections.append(ui("Kayıt yok.", "No records."))
                for user_id, role, message in web_rows:
                    sections.append(f"[{user_name(user_id)}] {role}: {message}")

            set_output("\n".join(sections).strip())

        def clear_history(source):
            labels = {
                "terminal": ui("Local Admin geçmişi", "Local Admin history"),
                "telegram": ui("Telegram geçmişi", "Telegram history"),
                "web": ui("Web geçmişi", "Web history"),
                "guest": ui("Guest kullanım sayacı", "Guest usage counter"),
            }
            label = labels[source]
            if not messagebox.askyesno(
                ui("Kayıtlar silinsin mi?", "Delete records?"),
                ui(
                    f"{label} kalıcı olarak silinecek. Devam edilsin mi?",
                    f"{label} will be permanently deleted. Continue?",
                ),
                parent=window,
            ):
                return

            if source == "web":
                clear_all_web_history()
            elif source == "guest":
                clear_guest_usage()
            else:
                self.agent.memory.clear_messages(source=source)

            render_history()

        def clear_events():
            if state["after"] is not None:
                try:
                    window.after_cancel(state["after"])
                except tk.TclError:
                    pass
                state["after"] = None
            self.agent.clear_system_events()
            render_monitor()

        def select_history(value):
            state["history"] = value
            for name, button in history_buttons.items():
                selected = name == value
                button.configure(
                    bg="#26344b" if selected else SURFACE_ALT,
                    fg="#ffffff" if selected else "#b8c0cf",
                )
            render_history()

        action_button = tk.Button(
            nav,
            font=("Segoe UI", 9),
            bg=SURFACE_ALT,
            fg="#cbd2de",
            activebackground="#29303d",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=13,
            pady=8,
        )
        action_button.pack(side="right")

        tab_buttons = {}

        def select_page(page):
            if state["after"] is not None:
                try:
                    window.after_cancel(state["after"])
                except tk.TclError:
                    pass
                state["after"] = None

            state["page"] = page
            for name, button in tab_buttons.items():
                selected = name == page
                button.configure(
                    bg="#26344b" if selected else SURFACE_ALT,
                    fg="#ffffff" if selected else "#b8c0cf",
                )

            if page == "history":
                filters.pack(
                    before=text_frame,
                    fill="x",
                    padx=12,
                    pady=(12, 0),
                )
                action_button.configure(
                    text=ui("Yenile", "Refresh"),
                    command=render_history,
                )
                render_history()
            else:
                filters.pack_forget()
                action_button.configure(
                    text=ui("Olayları Temizle", "Clear Events"),
                    command=clear_events,
                )
                render_monitor()

        for page, label in (
            ("monitor", ui("Sistem Monitörü", "System Monitor")),
            ("history", ui("Konuşma Geçmişi", "Conversation History")),
        ):
            button = tk.Button(
                nav,
                text=label,
                command=lambda value=page: select_page(value),
                font=("Segoe UI Semibold", 9),
                bg=SURFACE_ALT,
                fg="#b8c0cf",
                activebackground="#26344b",
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
                cursor="hand2",
                padx=15,
                pady=9,
            )
            button.pack(side="left", padx=(0, 8))
            tab_buttons[page] = button

        for value, label in (
            ("all", ui("Tümü", "All")),
            ("terminal", "Local Admin"),
            ("telegram", "Telegram"),
            ("web", "Web"),
        ):
            button = tk.Button(
                filters,
                text=label,
                command=lambda item=value: select_history(item),
                font=("Segoe UI", 9),
                bg=SURFACE_ALT,
                fg="#b8c0cf",
                activebackground="#26344b",
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
                cursor="hand2",
                padx=12,
                pady=7,
            )
            button.pack(side="left", padx=(0, 7))
            history_buttons[value] = button

        for source, label in (
            ("terminal", ui("Local Admin temizle", "Clear Local Admin")),
            ("telegram", ui("Telegram temizle", "Clear Telegram")),
            ("web", ui("Web temizle", "Clear Web")),
            ("guest", ui("Guest sayacını temizle", "Clear Guest Counter")),
        ):
            tk.Button(
                clear_bar,
                text=label,
                command=lambda item=source: clear_history(item),
                font=("Segoe UI", 8),
                bg="#2a2026",
                fg="#e5b9c2",
                activebackground="#3a2830",
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
                cursor="hand2",
                padx=10,
                pady=7,
            ).pack(side="left", padx=(0, 7))

        select_history("all")
        select_page("monitor")

    def run(self):
        self.root.mainloop()
