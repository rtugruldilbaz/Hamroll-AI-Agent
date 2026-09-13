import logging
import sys
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path

SRC_PATH = Path(__file__).parent / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import uvicorn

from agent.agent import Agent
from config.app_settings import get_language, get_voice_hotkey, get_web_host, load_settings
from desktop.desktop_ui import DesktopUI
from desktop.setup_ui import run_first_setup
from speech.hotkey_listener import start_voice_hotkey
from telegram_bot.bot import get_bot_status, start_bot, stop_bot
from web.app import app, set_agent

logging.getLogger("telegram").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.CRITICAL)

web_server = None
web_thread = None
web_lock = threading.RLock()


def text(tr, en):
    return tr if get_language() == "tr" else en


class SharedAgent:
    def __init__(self):
        self._agent = Agent()
        self._lock = threading.Lock()
        self._active = None
        self._events = deque(maxlen=250)
        self._events_lock = threading.Lock()

    def record_event(self, source, event, user_id=None, detail=None):
        item = {"time": time.strftime("%H:%M:%S"), "source": source,
                "event": event, "user_id": user_id}
        if detail:
            item["detail"] = str(detail)
        with self._events_lock:
            self._events.append(item)

    def get_system_snapshot(self):
        with self._events_lock:
            active = self._active
            events = list(self._events)
        if active:
            active = dict(active)
            active["elapsed"] = round(time.monotonic() - active["started"], 1)
            active.pop("started", None)
        return {"active": active, "events": events}

    def clear_system_events(self):
        with self._events_lock:
            self._events.clear()

    def reset_conversation(self, source="terminal", user_id=None):
        if not self._lock.acquire(blocking=False):
            return False
        try:
            self._agent.reset_conversation(source, user_id)
            return True
        finally:
            self._lock.release()

    def run(
        self,
        user_message,
        source="terminal",
        user_id=None,
        selected_tool=None,
        document_source=None,
    ):
        if not self._lock.acquire(blocking=False):
            with self._events_lock:
                active_source = (self._active or {}).get("source")
            self.record_event(source, "request_blocked", user_id, active_source)

            source_name = {
                "web": "Web",
                "telegram": "Telegram",
                "terminal": "Local Admin",
            }.get(active_source, "another interface")

            return text(
                f"Agent şu anda {source_name} üzerinden kullanılıyor. Lütfen bekleyin.",
                f"The Agent is currently being used through {source_name}. Please wait.",
            )

        started_at = time.monotonic()
        with self._events_lock:
            self._active = {"source": source, "user_id": user_id, "started": started_at}
        self.record_event(source, "request_started", user_id)

        try:
            return self._agent.run(
                user_message,
                source=source,
                user_id=user_id,
                selected_tool=selected_tool,
                document_source=document_source,
            )
        except Exception as error:
            self.record_event(source, "request_error", user_id, type(error).__name__)
            raise
        finally:
            elapsed = round(time.monotonic() - started_at, 1)
            self.record_event(source, "request_finished", user_id, f"{elapsed:.1f}s")
            with self._events_lock:
                self._active = None
            self._lock.release()

    def __getattr__(self, name):
        return getattr(self._agent, name)


def start_web(settings=None, open_browser=False):
    global web_server, web_thread

    settings = settings or load_settings()
    host = get_web_host()
    port = settings["web"]["port"]

    with web_lock:
        if is_web_running():
            return True

        if web_thread is not None and web_thread.is_alive():
            return False

        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            log_config=None,
            timeout_graceful_shutdown=3,
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=server.run,
            daemon=True,
        )
        web_server = server
        web_thread = thread
        thread.start()

    deadline = time.monotonic() + 6

    while time.monotonic() < deadline:
        if server.started:
            url = f"http://127.0.0.1:{port}"
            print(
                text(
                    f"[System] Web arayüzü başlatıldı: {url}",
                    f"[System] Web interface started at {url}",
                )
            )

            if settings["web"]["access"] == "lan":
                print(
                    text(
                        "[System] Yerel ağ erişimi etkin.",
                        "[System] Local network access is enabled.",
                    )
                )

            if open_browser:
                webbrowser.open(url)

            return True

        if not thread.is_alive():
            break

        time.sleep(0.05)

    with web_lock:
        if web_server is server:
            web_server = None
        if web_thread is thread:
            web_thread = None

    return False


def stop_web():
    global web_server, web_thread

    with web_lock:
        server = web_server
        thread = web_thread

    if server is None:
        return True

    # Stop accepting new work and allow active requests to finish first.
    server.should_exit = True

    if thread is not None:
        thread.join(timeout=5)

        if thread.is_alive():
            # Last resort for a server that did not honor graceful shutdown.
            print(
                text(
                    "[System] Web graceful kapanışı zaman aşımına uğradı; "
                    "force exit kullanılıyor.",
                    "[System] Web graceful shutdown timed out; "
                    "force exit is being used.",
                )
            )
            server.force_exit = True
            thread.join(timeout=2)

    stopped = thread is None or not thread.is_alive()

    if stopped:
        with web_lock:
            if web_server is server:
                web_server = None
            if web_thread is thread:
                web_thread = None

    return stopped


def is_web_running():
    with web_lock:
        server = web_server
        thread = web_thread

    return bool(
        server is not None
        and thread is not None
        and thread.is_alive()
        and server.started
        and not server.should_exit
    )

def start_voice_if_enabled(agent, settings):
    if not settings["voice"]["enabled"]:
        return None

    try:
        return start_voice_hotkey(
            agent,
            hotkey=get_voice_hotkey(),
        )
    except ValueError:
        return None


def main():
    if not run_first_setup():
        return

    settings = load_settings()
    agent = SharedAgent()
    voice_listener = None
    set_agent(agent)

    try:
        if settings["web"]["enabled"]:
            start_web(
                settings,
                open_browser=False,
            )

        if settings["telegram"]["enabled"]:
            start_bot(agent)

        voice_listener = start_voice_if_enabled(
            agent,
            settings,
        )

        DesktopUI(
            agent,
            start_web,
            stop_web,
            is_web_running,
            start_bot,
            stop_bot,
            get_bot_status,
        ).run()

    finally:
        if voice_listener is not None:
            try:
                voice_listener.stop()
            except Exception:
                pass

        stop_bot()
        stop_web()


if __name__ == "__main__":
    main()
