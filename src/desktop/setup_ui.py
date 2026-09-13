import subprocess
import threading
import webbrowser
import tkinter as tk
from tkinter import StringVar, ttk

import requests

from config.app_settings import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_OLLAMA_HOST,
    get_language,
    load_settings,
    update_settings,
)
from config.i18n import translate
from desktop.resources import apply_dark_title_bar, get_app_icon_path
from web.database import get_user_by_username, get_web_admin, save_web_admin_credentials

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"

BG = "#f5f7fb"
SURFACE = "#ffffff"
SURFACE_ALT = "#f8fafc"
TEXT = "#172033"
MUTED = "#667085"
BORDER = "#e3e8ef"
ACCENT = "#356ae6"
ACCENT_HOVER = "#2859ca"
SUCCESS_BG = "#eaf8f0"
SUCCESS_TEXT = "#18794e"
WARNING_BG = "#fff6e8"
WARNING_TEXT = "#9a5b13"
DANGER_BG = "#fff0f0"
DANGER_TEXT = "#b42318"


def _t(key, **values):
    return translate(get_language(), key, **values)


def _installed_models(host):
    response = requests.get(f"{host.rstrip('/')}/api/tags", timeout=5)
    response.raise_for_status()
    result = []

    for item in response.json().get("models", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model")
        if name:
            result.append(str(name))

    return result


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


class FirstRunSetup:
    def __init__(self):
        self.completed = False
        self.page = "ollama"
        self.ollama_ready = False
        self.status_badges = {}

        self.root = tk.Tk()
        self.root.title(_t("desktop_setup_title"))
        apply_dark_title_bar(self.root)

        icon_path = get_app_icon_path()
        if icon_path is not None:
            try:
                self.root.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass

        self.root.geometry("920x690")
        self.root.minsize(850, 640)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

        settings = load_settings()
        self.host = StringVar(value=settings["model"].get("ollama_host") or DEFAULT_OLLAMA_HOST)
        self.chat_model = StringVar(value=settings["model"].get("chat_model") or DEFAULT_CHAT_MODEL)
        self.language = StringVar(value="Türkçe (TR)" if get_language() == "tr" else "English (EN)")
        self.username = StringVar(value="")
        self.password = StringVar(value="")
        self.confirm_password = StringVar(value="")
        self.admin_status = StringVar(value="")

        self._configure_ttk()
        self._build_ollama_page()

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
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            arrowcolor=TEXT,
        )

    def _clear(self):
        for child in self.root.winfo_children():
            child.destroy()
        self.status_badges = {}

    def _button(self, parent, text, command, primary=False, variant=None):
        if variant is None:
            variant = "primary" if primary else "secondary"

        palette = {
            "primary": (ACCENT, "#ffffff", ACCENT_HOVER, ACCENT),
            "secondary": ("#eef4ff", "#254fa3", "#e2ebff", "#cbd9f5"),
            "neutral": (SURFACE, TEXT, "#f3f5f8", BORDER),
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
            padx=16,
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
            bg="#eef4ff",
            fg="#315db8",
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#cbd9f5",
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

    def _shell(self, step):
        self._clear()

        topbar = tk.Frame(self.root, bg=SURFACE, height=72, highlightthickness=1, highlightbackground=BORDER)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        brand = tk.Frame(topbar, bg=SURFACE)
        brand.pack(side="left", padx=30, pady=13)
        tk.Label(brand, text="AI Agent", bg=SURFACE, fg=TEXT, font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(brand, text=_t("desktop_setup_subtitle"), bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")

        language_box = ttk.Combobox(
            topbar,
            textvariable=self.language,
            values=("Türkçe (TR)", "English (EN)"),
            state="readonly",
            width=16,
            style="Modern.TCombobox",
        )
        language_box.pack(side="right", padx=30, pady=18)
        language_box.bind("<<ComboboxSelected>>", self._change_language)

        stage = tk.Frame(self.root, bg=BG)
        stage.pack(fill="both", expand=True, padx=30, pady=22)

        steps = tk.Frame(stage, bg=BG)
        steps.pack(fill="x", pady=(0, 16))

        names = (_t("desktop_step_ollama"), _t("desktop_step_admin"), _t("desktop_step_control_panel"))
        for index, name in enumerate(names, start=1):
            active = index == step
            done = index < step
            badge_bg = ACCENT if active else SUCCESS_TEXT if done else "#98a2b3"
            cell = tk.Frame(steps, bg=BG)
            cell.pack(side="left", fill="x", expand=True)
            tk.Label(cell, text=str(index), bg=badge_bg, fg="#ffffff", font=("Segoe UI", 9, "bold"), width=2).pack(side="left")
            tk.Label(
                cell,
                text=name,
                bg=BG,
                fg=TEXT if active else MUTED,
                font=("Segoe UI", 9, "bold" if active else "normal"),
            ).pack(side="left", padx=8)

        card = tk.Frame(stage, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="both", expand=True)
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=32, pady=28)
        return inner

    def _title(self, parent, title, subtitle):
        tk.Label(parent, text=title, bg=SURFACE, fg=TEXT, font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(
            parent,
            text=subtitle,
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 10),
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(6, 20))

    def _field(self, parent, label, variable, show=None, helper=None):
        tk.Label(parent, text=label, bg=SURFACE, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        entry = self._entry(parent, variable, show=show)
        entry.pack(fill="x", ipady=9, pady=(6, 4))
        if helper:
            tk.Label(
                parent,
                text=helper,
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI", 9),
                wraplength=760,
                justify="left",
            ).pack(anchor="w", pady=(0, 12))
        else:
            tk.Frame(parent, bg=SURFACE, height=8).pack()
        return entry

    def _status_row(self, parent, key, title):
        row = tk.Frame(parent, bg=SURFACE_ALT)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=title, bg=SURFACE_ALT, fg=TEXT, font=("Segoe UI", 9)).pack(side="left")
        badge = tk.Label(row, text=_t("desktop_not_tested"), bg="#eef2f7", fg=MUTED, font=("Segoe UI", 8, "bold"), padx=9, pady=3)
        badge.pack(side="right")
        self.status_badges[key] = badge

    def _set_status(self, key, text, state):
        badge = self.status_badges.get(key)
        if badge is None:
            return
        palette = {
            "success": (SUCCESS_BG, SUCCESS_TEXT),
            "warning": (WARNING_BG, WARNING_TEXT),
            "error": (DANGER_BG, DANGER_TEXT),
            "idle": ("#eef2f7", MUTED),
        }
        bg, fg = palette[state]
        badge.configure(text=text, bg=bg, fg=fg)

    def _change_language(self, event=None):
        language = "en" if self.language.get().startswith("English") else "tr"
        update_settings({"general": {"language": language}})
        self.root.title(_t("desktop_setup_title"))
        self.ollama_ready = False
        if self.page == "ollama":
            self._build_ollama_page()
        else:
            self._build_admin_page()

    def _build_ollama_page(self):
        self.page = "ollama"
        parent = self._shell(1)
        self._title(parent, _t("desktop_ollama_setup"), _t("desktop_ollama_required"))

        fields = tk.Frame(parent, bg=SURFACE)
        fields.pack(fill="x")
        fields.columnconfigure(0, weight=1)
        fields.columnconfigure(1, weight=1)

        left = tk.Frame(fields, bg=SURFACE)
        left.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        right = tk.Frame(fields, bg=SURFACE)
        right.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        self._field(left, _t("desktop_ollama_host"), self.host, helper=_t("desktop_ollama_host_help"))
        self._field(right, _t("desktop_chat_model"), self.chat_model, helper=_t("desktop_chat_model_help"))

        embed = tk.Frame(parent, bg=SURFACE_ALT, highlightthickness=1, highlightbackground=BORDER)
        embed.pack(fill="x", pady=(2, 14))
        embed_inner = tk.Frame(embed, bg=SURFACE_ALT)
        embed_inner.pack(fill="x", padx=16, pady=13)
        tk.Label(
            embed_inner,
            text=f"{_t('desktop_embedding_model')}  ·  {DEFAULT_EMBEDDING_MODEL}",
            bg=SURFACE_ALT,
            fg=TEXT,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")
        tk.Label(
            embed_inner,
            text=_t("desktop_embedding_explanation"),
            bg=SURFACE_ALT,
            fg=MUTED,
            font=("Segoe UI", 9),
            wraplength=730,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))
        tk.Label(
            embed_inner,
            text=_t("desktop_embedding_install_help", model=DEFAULT_EMBEDDING_MODEL),
            bg=SURFACE_ALT,
            fg=MUTED,
            font=("Segoe UI", 9),
            wraplength=730,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        actions = tk.Frame(parent, bg=SURFACE)
        actions.pack(fill="x", pady=(0, 12))
        self._button(
            actions,
            _t("desktop_open_ollama_site"),
            lambda: webbrowser.open(OLLAMA_DOWNLOAD_URL),
            variant="neutral",
        ).pack(side="left")

        install_group = tk.Frame(actions, bg=SURFACE)
        install_group.pack(side="left", padx=8)
        self._button(
            install_group,
            _t("desktop_install_models"),
            self._install_models,
            variant="secondary",
        ).pack(side="left")
        self._info_button(
            install_group,
            _t("desktop_install_models_info", model=DEFAULT_EMBEDDING_MODEL),
        ).pack(side="left", padx=(6, 0), pady=7)

        self._button(
            actions,
            _t("desktop_check_connection"),
            self._test_ollama,
            variant="primary",
        ).pack(side="right")

        status_card = tk.Frame(parent, bg=SURFACE_ALT, highlightthickness=1, highlightbackground=BORDER)
        status_card.pack(fill="x", pady=(0, 14))
        status_inner = tk.Frame(status_card, bg=SURFACE_ALT)
        status_inner.pack(fill="x", padx=16, pady=10)
        self._status_row(status_inner, "service", "Ollama")
        self._status_row(status_inner, "chat", _t("desktop_chat_model"))
        self._status_row(status_inner, "embedding", _t("desktop_embedding_model"))

        navigation = tk.Frame(parent, bg=SURFACE)
        navigation.pack(fill="x", side="bottom")
        self.continue_button = self._button(navigation, _t("desktop_continue"), self._build_admin_page, variant="primary")
        self.continue_button.pack(side="right")
        self.continue_button.configure(state="normal" if self.ollama_ready else "disabled")

    def _test_ollama(self):
        host = self.host.get().strip().rstrip("/")
        model = self.chat_model.get().strip()
        if not model:
            self._set_status("chat", _t("desktop_chat_model_required"), "error")
            return

        self.ollama_ready = False
        self.continue_button.configure(state="disabled")
        for key in ("service", "chat", "embedding"):
            self._set_status(key, _t("desktop_checking"), "idle")

        def worker():
            try:
                models = _installed_models(host)
                chat_ok = _model_installed(model, models)
                embedding_ok = _model_installed(DEFAULT_EMBEDDING_MODEL, models)

                def finish():
                    self._set_status("service", _t("desktop_connected_label"), "success")
                    self._set_status("chat", _t("desktop_installed") if chat_ok else _t("desktop_missing"), "success" if chat_ok else "error")
                    self._set_status("embedding", _t("desktop_installed") if embedding_ok else _t("desktop_missing"), "success" if embedding_ok else "error")
                    self.ollama_ready = bool(chat_ok and embedding_ok)
                    if self.ollama_ready:
                        update_settings({"model": {"ollama_host": host, "chat_model": model}})
                    self.continue_button.configure(state="normal" if self.ollama_ready else "disabled")

                self.root.after(0, finish)
            except (requests.RequestException, ValueError):
                self.root.after(0, self._ollama_failed)

        threading.Thread(target=worker, daemon=True).start()

    def _ollama_failed(self):
        self._set_status("service", _t("desktop_connection_failed_plain"), "error")
        self._set_status("chat", _t("desktop_not_checked"), "idle")
        self._set_status("embedding", _t("desktop_not_checked"), "idle")
        self.ollama_ready = False
        self.continue_button.configure(state="disabled")

    def _install_models(self):
        host = self.host.get().strip().rstrip("/")
        model = self.chat_model.get().strip()
        if not model:
            self._set_status("chat", _t("desktop_chat_model_required"), "error")
            return

        self.ollama_ready = False
        self.continue_button.configure(state="disabled")
        self._set_status("chat", _t("desktop_installing"), "warning")
        self._set_status("embedding", _t("desktop_installing"), "warning")

        def worker():
            try:
                installed = _installed_models(host)
                missing = []
                if not _model_installed(model, installed):
                    missing.append(model)
                if not _model_installed(DEFAULT_EMBEDDING_MODEL, installed):
                    missing.append(DEFAULT_EMBEDDING_MODEL)

                for name in missing:
                    process = subprocess.run(
                        ["ollama", "pull", name],
                        capture_output=True,
                        text=True,
                        timeout=7200,
                        check=False,
                    )
                    if process.returncode != 0:
                        self.root.after(0, self._ollama_failed)
                        return

                self.root.after(0, self._test_ollama)
            except requests.RequestException:
                self.root.after(0, self._ollama_failed)
            except (OSError, subprocess.SubprocessError):
                self.root.after(0, lambda: self._set_status("service", _t("desktop_ollama_cli_missing"), "error"))

        threading.Thread(target=worker, daemon=True).start()

    def _build_admin_page(self):
        if not self.ollama_ready:
            return
        self.page = "admin"
        parent = self._shell(2)
        self._title(parent, _t("desktop_admin_setup"), _t("desktop_admin_help"))

        info = tk.Frame(parent, bg="#eef4ff", highlightthickness=1, highlightbackground="#c9d8fb")
        info.pack(fill="x", pady=(0, 16))
        tk.Label(
            info,
            text=_t("desktop_admin_scope"),
            bg="#eef4ff",
            fg="#294d9b",
            font=("Segoe UI", 9, "bold"),
            wraplength=730,
            justify="left",
        ).pack(anchor="w", padx=14, pady=12)

        self._field(parent, _t("desktop_username"), self.username)
        self._field(parent, _t("desktop_password"), self.password, show="*")
        self._field(parent, _t("desktop_confirm_password"), self.confirm_password, show="*")
        tk.Label(
            parent,
            textvariable=self.admin_status,
            bg=SURFACE,
            fg=DANGER_TEXT,
            font=("Segoe UI", 9),
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(2, 8))

        navigation = tk.Frame(parent, bg=SURFACE)
        navigation.pack(fill="x", side="bottom")
        self._button(navigation, _t("desktop_back"), self._build_ollama_page).pack(side="left")
        self._button(navigation, _t("desktop_create_admin_continue"), self._create_admin, variant="primary").pack(side="right")

    def _create_admin(self):
        username = self.username.get().strip()
        password = self.password.get()
        confirm = self.confirm_password.get()

        if len(username) < 3:
            self.admin_status.set(_t("username_too_short"))
            return
        if len(password) < 6:
            self.admin_status.set(_t("password_too_short"))
            return
        if password != confirm:
            self.admin_status.set(_t("desktop_passwords_do_not_match"))
            return
        if get_user_by_username(username):
            self.admin_status.set(_t("username_in_use"))
            return

        try:
            save_web_admin_credentials(username, password)
        except ValueError as error:
            self.admin_status.set(str(error))
            return

        self.completed = True
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        return self.completed


def run_first_setup():
    if get_web_admin() is not None:
        return True
    return FirstRunSetup().run()
