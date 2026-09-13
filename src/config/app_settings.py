import json
import os
import secrets
import threading
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


load_dotenv()

APP_FOLDER_NAME = "AI-Agent"
DEFAULT_AGENT_NAME = "AI Agent"
DEFAULT_LANGUAGE = "tr"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_CHAT_MODEL = "qwen2.5:7b"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_WEB_PORT = 8000
DEFAULT_VOICE_HOTKEY = "f8"
DEFAULT_VOICE_SCOPE = "global"

SUPPORTED_LANGUAGES = {"tr", "en"}
SUPPORTED_WEB_ACCESS = {"local", "lan"}
SUPPORTED_LOCAL_ACCESS_MODES = {"safe", "custom"}
SUPPORTED_VOICE_SCOPES = {"global", "local_admin"}

DEFAULT_SETTINGS = {
    "general": {
        "agent_name": DEFAULT_AGENT_NAME,
        "language": DEFAULT_LANGUAGE,
    },
    "model": {
        "ollama_host": DEFAULT_OLLAMA_HOST,
        "chat_model": DEFAULT_CHAT_MODEL,
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
    },
    "web": {
        "enabled": True,
        "access": "local",
        "port": DEFAULT_WEB_PORT,
        "open_browser": True,
    },
    "telegram": {
        "enabled": False,
    },
    "voice": {
        "enabled": True,
        "hotkey": DEFAULT_VOICE_HOTKEY,
        "scope": DEFAULT_VOICE_SCOPE,
    },
    "local_admin": {
        "enabled": True,
        "access_mode": "safe",
        "allowed_paths": [],
        "custom_access_acknowledged": False,
    },
    "help": {
        "show_info_buttons": True,
    },
}

DEFAULT_SECRETS = {
    "telegram_bot_token": "",
    "telegram_user_id": "",
}

_lock = threading.RLock()


def _get_data_directory() -> Path:
    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA")
        directory = (
            Path(local_app_data) / APP_FOLDER_NAME
            if local_app_data
            else Path.home() / "AppData" / "Local" / APP_FOLDER_NAME
        )
    else:
        directory = Path.home() / ".ai-agent"

    directory.mkdir(parents=True, exist_ok=True)
    return directory


DATA_DIRECTORY = _get_data_directory()
CONFIG_PATH = DATA_DIRECTORY / "config.json"
SECRETS_PATH = DATA_DIRECTORY / "secrets.json"
INTERNAL_PATH = DATA_DIRECTORY / "internal.json"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _merge(defaults: dict, loaded: dict) -> dict:
    result = deepcopy(defaults)

    for key, value in loaded.items():
        if key not in result:
            continue

        if isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value

    return result


def _normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
            "enabled",
        }

    return bool(value)


def _normalize_agent_name(value) -> str:
    value = str(value or "").strip()

    if value.casefold() in {"", "badi", "badi ai agent"}:
        return DEFAULT_AGENT_NAME

    return value[:50]


def _normalize_language(value) -> str:
    value = str(value or "").strip().lower()
    return value if value in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def _normalize_ollama_host(value) -> str:
    value = str(value or "").strip().rstrip("/")

    if not value:
        return DEFAULT_OLLAMA_HOST

    parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "Ollama host must be a valid HTTP or HTTPS address."
        )

    if (
        parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Ollama host must not include an API path, query, or fragment."
        )

    return value


def _normalize_chat_model(value) -> str:
    value = str(value or "").strip()
    return value[:100] or DEFAULT_CHAT_MODEL


def _normalize_web_access(value) -> str:
    value = str(value or "").strip().lower()
    return value if value in SUPPORTED_WEB_ACCESS else "local"


def _normalize_port(value) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return DEFAULT_WEB_PORT

    return port if 1024 <= port <= 65535 else DEFAULT_WEB_PORT


def _normalize_hotkey(value) -> str:
    value = str(value or "").strip().lower()

    if not value:
        return DEFAULT_VOICE_HOTKEY

    if len(value) > 80:
        raise ValueError("Voice hotkey is too long.")

    return value


def _normalize_voice_scope(value) -> str:
    value = str(value or "").strip().lower()
    return value if value in SUPPORTED_VOICE_SCOPES else DEFAULT_VOICE_SCOPE


def _normalize_telegram_user_id(value) -> str:
    value = str(value or "").strip()

    if value and not value.isdigit():
        raise ValueError(
            "Telegram user ID must contain only numbers."
        )

    return value


def _normalize_local_access_mode(value) -> str:
    value = str(value or "").strip().lower()
    return (
        value
        if value in SUPPORTED_LOCAL_ACCESS_MODES
        else "safe"
    )


def _normalize_allowed_paths(value) -> list[str]:
    if not isinstance(value, list):
        return []

    result = []
    seen = set()

    for item in value:
        path_text = str(item or "").strip()

        if not path_text:
            continue

        try:
            path = Path(path_text).expanduser().resolve()
        except (OSError, RuntimeError):
            continue

        normalized = str(path)
        comparison = os.path.normcase(normalized)

        if comparison in seen:
            continue

        seen.add(comparison)
        result.append(normalized)

        if len(result) >= 50:
            break

    return result


def normalize_settings(settings: dict) -> dict:
    settings = _merge(DEFAULT_SETTINGS, settings)

    settings["general"]["agent_name"] = _normalize_agent_name(
        settings["general"].get("agent_name")
    )
    settings["general"]["language"] = _normalize_language(
        settings["general"].get("language")
    )

    settings["model"]["ollama_host"] = _normalize_ollama_host(
        settings["model"].get("ollama_host")
    )
    settings["model"]["chat_model"] = _normalize_chat_model(
        settings["model"].get("chat_model")
    )
    settings["model"]["embedding_model"] = DEFAULT_EMBEDDING_MODEL

    settings["web"]["enabled"] = _normalize_bool(
        settings["web"].get("enabled")
    )
    settings["web"]["access"] = _normalize_web_access(
        settings["web"].get("access")
    )
    settings["web"]["port"] = _normalize_port(
        settings["web"].get("port")
    )
    settings["web"]["open_browser"] = _normalize_bool(
        settings["web"].get("open_browser")
    )

    settings["telegram"]["enabled"] = _normalize_bool(
        settings["telegram"].get("enabled")
    )

    settings["voice"]["enabled"] = _normalize_bool(
        settings["voice"].get("enabled")
    )
    settings["voice"]["hotkey"] = _normalize_hotkey(
        settings["voice"].get("hotkey")
    )
    settings["voice"]["scope"] = _normalize_voice_scope(
        settings["voice"].get("scope")
    )

    settings["local_admin"]["enabled"] = _normalize_bool(
        settings["local_admin"].get("enabled")
    )
    settings["local_admin"]["access_mode"] = _normalize_local_access_mode(
        settings["local_admin"].get("access_mode")
    )
    settings["local_admin"]["allowed_paths"] = _normalize_allowed_paths(
        settings["local_admin"].get("allowed_paths")
    )
    settings["local_admin"]["custom_access_acknowledged"] = _normalize_bool(
        settings["local_admin"].get("custom_access_acknowledged")
    )

    settings["help"]["show_info_buttons"] = _normalize_bool(
        settings["help"].get("show_info_buttons")
    )

    return settings


def _validate_settings_for_save(settings: dict) -> None:
    local_admin = settings["local_admin"]

    if (
        local_admin["access_mode"] == "custom"
        and not local_admin["custom_access_acknowledged"]
    ):
        raise ValueError(
            "Custom Local Access requires risk acknowledgement."
        )


def normalize_secrets(data: dict) -> dict:
    result = _merge(DEFAULT_SECRETS, data)

    result["telegram_bot_token"] = str(
        result.get("telegram_bot_token") or ""
    ).strip()

    result["telegram_user_id"] = _normalize_telegram_user_id(
        result.get("telegram_user_id")
    )

    return result


def load_settings() -> dict:
    with _lock:
        if not CONFIG_PATH.exists():
            settings = normalize_settings(DEFAULT_SETTINGS)
            _write_json(CONFIG_PATH, settings)
            return settings

        loaded = _read_json(CONFIG_PATH)
        settings = normalize_settings(loaded)

        if settings != loaded:
            _write_json(CONFIG_PATH, settings)

        return settings


def save_settings(settings: dict) -> dict:
    with _lock:
        settings = normalize_settings(settings)
        _validate_settings_for_save(settings)
        _write_json(CONFIG_PATH, settings)
        return settings


def update_settings(changes: dict) -> dict:
    with _lock:
        current = load_settings()

        for section, values in changes.items():
            if (
                section in current
                and isinstance(current[section], dict)
                and isinstance(values, dict)
            ):
                current[section].update(values)

        return save_settings(current)


def load_secrets() -> dict:
    with _lock:
        if not SECRETS_PATH.exists():
            data = {
                "telegram_bot_token": os.getenv(
                    "TELEGRAM_BOT_TOKEN",
                    "",
                ).strip(),
                "telegram_user_id": os.getenv(
                    "AUTHORIZED_USER_ID",
                    "",
                ).strip(),
            }

            data = normalize_secrets(data)
            _write_json(SECRETS_PATH, data)
            return data

        return normalize_secrets(_read_json(SECRETS_PATH))


def save_secrets(data: dict) -> dict:
    with _lock:
        current = load_secrets()
        current.update(data)
        current = normalize_secrets(current)
        _write_json(SECRETS_PATH, current)
        return current


def validate_telegram_settings(
    settings: dict | None = None,
    secrets_data: dict | None = None,
) -> None:
    settings = settings or load_settings()
    secrets_data = secrets_data or load_secrets()

    if not settings["telegram"]["enabled"]:
        return

    if not secrets_data["telegram_bot_token"]:
        raise ValueError(
            "Telegram bot token is required when Telegram is enabled."
        )

    if not secrets_data["telegram_user_id"]:
        raise ValueError(
            "Telegram user ID is required when Telegram is enabled."
        )


def get_internal_settings() -> dict:
    with _lock:
        data = _read_json(INTERNAL_PATH)

        if not data.get("web_session_secret"):
            existing_secret = os.getenv(
                "WEB_SESSION_SECRET",
                "",
            ).strip()

            data["web_session_secret"] = (
                existing_secret
                or secrets.token_urlsafe(48)
            )

            _write_json(INTERNAL_PATH, data)

        return data


def update_internal_settings(changes: dict) -> dict:
    with _lock:
        data = get_internal_settings()
        data.update(changes)
        _write_json(INTERNAL_PATH, data)
        return data


def get_web_session_secret() -> str:
    return get_internal_settings()["web_session_secret"]


def set_web_admin_user_id(user_id: int) -> None:
    update_internal_settings(
        {"web_admin_user_id": int(user_id)}
    )


def get_web_admin_user_id() -> int | None:
    value = get_internal_settings().get("web_admin_user_id")

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def save_telegram_chat_id(chat_id) -> None:
    update_internal_settings(
        {"telegram_chat_id": str(chat_id)}
    )


def get_telegram_chat_id() -> int | None:
    value = str(
        get_internal_settings().get("telegram_chat_id") or ""
    ).strip()

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_agent_name() -> str:
    return load_settings()["general"]["agent_name"]


def get_language() -> str:
    return load_settings()["general"]["language"]


def get_ollama_host() -> str:
    return load_settings()["model"]["ollama_host"]


def get_chat_model() -> str:
    return load_settings()["model"]["chat_model"]


def get_embedding_model() -> str:
    return load_settings()["model"]["embedding_model"]


def get_web_host() -> str:
    return (
        "0.0.0.0"
        if load_settings()["web"]["access"] == "lan"
        else "127.0.0.1"
    )


def get_voice_hotkey() -> str:
    return load_settings()["voice"]["hotkey"]
def get_local_access_mode() -> str:
    return load_settings()["local_admin"]["access_mode"]


def get_local_allowed_paths() -> list[str]:
    return list(
        load_settings()["local_admin"]["allowed_paths"]
    )


def is_custom_access_acknowledged() -> bool:
    return load_settings()["local_admin"][
        "custom_access_acknowledged"
    ]


def show_info_buttons() -> bool:
    return load_settings()["help"]["show_info_buttons"]
