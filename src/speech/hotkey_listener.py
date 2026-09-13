import os
import threading

from pynput import keyboard

from config.app_settings import get_language, load_settings
from speech.recorder import start_recording, stop_recording
from speech.transcriber import transcribe_audio


recording_active = False
_recording_lock = threading.Lock()
_service_lock = threading.RLock()
_agent = None
_listener = None
_listener_hotkey = None
_local_admin_active = False
_message_handler = None


def _normalize_hotkey_part(part):
    value = str(part).strip().lower()

    aliases = {
        "control": "ctrl",
        "win": "cmd",
        "windows": "cmd",
        "escape": "esc",
        "return": "enter",
    }
    value = aliases.get(value, value)

    special_keys = {
        "alt", "alt_gr", "backspace", "caps_lock", "cmd", "ctrl",
        "delete", "down", "end", "enter", "esc", "home", "insert",
        "left", "menu", "page_down", "page_up", "pause", "right",
        "shift", "space", "tab", "up",
    }

    if value in special_keys:
        return f"<{value}>"

    if value.startswith("f") and value[1:].isdigit():
        number = int(value[1:])
        if 1 <= number <= 24:
            return f"<f{number}>"

    if len(value) == 1:
        return value

    raise ValueError(f"Unsupported hotkey key: {part}")


def parse_hotkey(value):
    value = str(value or "").strip()

    if not value:
        raise ValueError("Voice hotkey cannot be empty.")

    parts = [
        part
        for part in value.replace(" ", "").split("+")
        if part
    ]

    if not parts:
        raise ValueError("Voice hotkey cannot be empty.")

    return "+".join(_normalize_hotkey_part(part) for part in parts)


def _language():
    language = get_language()
    return language if language in {"tr", "en"} else "en"


def _text(tr, en):
    return tr if _language() == "tr" else en


def _remove_audio_file(audio_path):
    if not audio_path:
        return

    try:
        if os.path.exists(audio_path):
            os.remove(audio_path)
    except OSError:
        pass


def _create_listener(agent, hotkey):
    display_hotkey = str(hotkey or "f8").strip()
    parsed_hotkey = parse_hotkey(display_hotkey)

    def toggle_recording():
        global recording_active

        with _recording_lock:
            if not recording_active:
                if start_recording():
                    recording_active = True
                    print(
                        _text(
                            f"\n[Voice] Kayıt başladı. Durdurmak için "
                            f"{display_hotkey.upper()} tuşuna tekrar basın.",
                            f"\n[Voice] Recording started. Press "
                            f"{display_hotkey.upper()} again to stop.",
                        )
                    )
                return

            audio_path = stop_recording()
            recording_active = False

        if not audio_path:
            print(
                _text(
                    "[Voice] Ses kaydı alınamadı.",
                    "[Voice] Audio could not be recorded.",
                )
            )
            return

        print(
            _text(
                "[Voice] Kayıt tamamlandı.",
                "[Voice] Recording finished.",
            )
        )

        try:
            text = transcribe_audio(
                audio_path,
                _language(),
            )

            if not text:
                print(
                    _text(
                        "[Voice] Konuşma algılanamadı.",
                        "[Voice] No speech was detected.",
                    )
                )
                return

            if _message_handler is not None:
                _message_handler(text)
                return

            response = agent.run(
                text,
                source="terminal",
            )

            print(f"\nAgent: {response}")

        except PermissionError:
            print(
                _text(
                    "[Voice] İşlem güvenlik nedeniyle engellendi.",
                    "[Voice] The action was blocked by security rules.",
                )
            )

        except Exception as error:
            print(
                "[Voice] Processing error: "
                f"{type(error).__name__}"
            )

        finally:
            _remove_audio_file(audio_path)

    def trigger():
        threading.Thread(
            target=toggle_recording,
            daemon=True,
        ).start()

    listener = keyboard.GlobalHotKeys({
        parsed_hotkey: trigger,
    })

    listener.daemon = True
    listener.start()

    print(
        "[System] Global voice hotkey active: "
        f"{display_hotkey.upper()}"
    )

    return listener


def start_voice_hotkey(agent, hotkey="f8"):
    """Compatibility entry point used by main.py."""
    global _agent, _listener, _listener_hotkey
    _agent = agent
    _listener = _create_listener(agent, hotkey)
    _listener_hotkey = str(hotkey or "f8").strip()
    return _listener


def _stop_recording_if_needed():
    global recording_active

    with _recording_lock:
        if not recording_active:
            return

        audio_path = stop_recording()
        recording_active = False

    _remove_audio_file(audio_path)


def refresh_voice_hotkey(agent=None):
    global _agent, _listener, _listener_hotkey

    with _service_lock:
        if agent is not None:
            _agent = agent

        settings = load_settings()
        voice = settings["voice"]
        hotkey = voice["hotkey"]
        should_run = bool(
            voice["enabled"]
            and (
                voice["scope"] == "global"
                or _local_admin_active
            )
        )

        if should_run and _listener is not None and _listener_hotkey == hotkey:
            return True

        if _listener is not None:
            _listener.stop()
            _listener = None
            _listener_hotkey = None
            _stop_recording_if_needed()

        if not should_run:
            return True

        if _agent is None:
            return False

        try:
            _listener = _create_listener(_agent, hotkey)
            _listener_hotkey = hotkey
            return True
        except (OSError, ValueError):
            _listener = None
            _listener_hotkey = None
            return False


def set_local_admin_active(active):
    global _local_admin_active

    with _service_lock:
        _local_admin_active = bool(active)

    return refresh_voice_hotkey()


def set_voice_message_handler(handler):
    global _message_handler
    _message_handler = handler


def get_voice_status():
    with _service_lock:
        if _listener is not None:
            return "running"

        voice = load_settings()["voice"]
        if voice["enabled"] and voice["scope"] == "local_admin":
            return "waiting"

        return "stopped"


def stop_voice_hotkey():
    global _listener, _listener_hotkey

    with _service_lock:
        if _listener is not None:
            _listener.stop()
            _listener = None
            _listener_hotkey = None

        _stop_recording_if_needed()
