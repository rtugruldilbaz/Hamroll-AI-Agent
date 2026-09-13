import asyncio
import hmac
import re
import secrets
import tempfile
import time
import zipfile
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from config.app_settings import (
    DATA_DIRECTORY,
    get_agent_name,
    get_language,
    get_web_session_secret,
    load_secrets,
    load_settings,
    save_secrets,
    save_settings,
)
from config.i18n import get_text, translate
from memory.memory_manager import MemoryManager
from rag.indexer import index_document
from security.permissions import is_admin, validate_custom_access_root
from speech.hotkey_listener import parse_hotkey, refresh_voice_hotkey
from speech.transcriber import transcribe_audio
from web.database import (
    clear_all_web_history,
    clear_guest_usage,
    create_guest,
    create_regular_user,
    get_all_web_message_count,
    get_guest_message_count,
    get_guest_usage_count,
    get_user_by_username,
    get_web_admin,
    increase_guest_message_count,
    initialize_database,
    save_web_admin_credentials,
    verify_password,
)

app = FastAPI()
agent = None
memory_manager = MemoryManager()

GUEST_MESSAGE_LIMIT = 5
REMEMBER_SECONDS = 60 * 60 * 24 * 30
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = 60 * 1024 * 1024

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = Path(__file__).resolve().parent
STATIC_DIR = WEB_ROOT / "static"
TEMPLATES_DIR = WEB_ROOT / "templates"
DOCUMENTS_DIR = DATA_DIRECTORY / "documents"

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".csv",
    ".json",
}

AUDIO_EXTENSIONS = {
    ".webm",
    ".wav",
    ".mp3",
    ".m4a",
    ".ogg",
    ".flac",
    ".aac",
}

WEB_TOOLS = {
    "create",
    "read",
    "write",
    "search-files",
    "list",
    "open",
    "rename",
    "move",
    "delete",
    "telegram-message",
    "telegram-file",
    "rag",
    "history",
}

LOCAL_CLIENTS = {
    "127.0.0.1",
    "::1",
}

RATE_LIMITS = {
    "upload": (5, 300),
    "transcribe": (12, 300),
}

_rate_events = defaultdict(deque)

WEB_SESSION_SECRET = get_web_session_secret()

remember_serializer = URLSafeTimedSerializer(
    WEB_SESSION_SECRET,
    salt="remember-user",
)

initialize_database()
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

app.add_middleware(
    SessionMiddleware,
    secret_key=WEB_SESSION_SECRET,
    same_site="lax",
    https_only=False,
)

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)

templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR)
)


class ChatRequest(BaseModel):
    message: str
    tool: str | None = None


class LanguageRequest(BaseModel):
    language: str


class OllamaTestRequest(BaseModel):
    host: str
    model: str | None = None


class CustomPathRequest(BaseModel):
    path: str


class SettingsGeneralRequest(BaseModel):
    agent_name: str
    language: str


class SettingsModelRequest(BaseModel):
    ollama_host: str
    chat_model: str


class SettingsWebRequest(BaseModel):
    enabled: bool
    access: str
    port: int
    open_browser: bool


class SettingsTelegramRequest(BaseModel):
    enabled: bool
    bot_token: str = ""
    authorized_user_id: str = ""


class SettingsVoiceRequest(BaseModel):
    enabled: bool
    hotkey: str
    scope: str


class SettingsLocalAdminRequest(BaseModel):
    enabled: bool
    access_mode: str
    allowed_paths: list[str]
    custom_access_acknowledged: bool


class SettingsHelpRequest(BaseModel):
    show_info_buttons: bool


class SettingsWebAdminRequest(BaseModel):
    username: str = ""
    password: str = ""


class SettingsRequest(BaseModel):
    general: SettingsGeneralRequest
    model: SettingsModelRequest
    web: SettingsWebRequest
    telegram: SettingsTelegramRequest
    voice: SettingsVoiceRequest
    local_admin: SettingsLocalAdminRequest
    help: SettingsHelpRequest
    web_admin: SettingsWebAdminRequest


def set_agent(shared_agent):
    global agent
    agent = shared_agent


def _request_language(request: Request) -> str:
    language = request.session.get("ui_language")

    return (
        language
        if language in {"tr", "en"}
        else get_language()
    )


def _csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")

    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token

    return token


def _csrf_valid(
    request: Request,
    token=None,
) -> bool:
    expected = request.session.get(
        "csrf_token"
    )

    supplied = (
        token
        or request.headers.get(
            "X-CSRF-Token"
        )
    )

    return bool(
        expected
        and supplied
        and hmac.compare_digest(
            str(expected),
            str(supplied),
        )
    )


def _template_context(
    request: Request,
    **extra,
):
    language = _request_language(
        request
    )

    context = {
        "language": language,
        "text": get_text(language),
        "agent_name": get_agent_name(),
        "csrf_token": _csrf_token(request),
    }

    context.update(extra)

    return context


def _is_local_request(
    request: Request,
) -> bool:
    return bool(
        request.client
        and request.client.host
        in LOCAL_CLIENTS
    )


def _same_origin(
    request: Request,
) -> bool:
    origin = request.headers.get(
        "origin"
    )

    if not origin:
        return True

    try:
        return (
            urlparse(origin).netloc
            == request.headers.get(
                "host",
                "",
            )
        )
    except ValueError:
        return False


def _error(
    request: Request,
    key: str,
    status_code=403,
):
    return JSONResponse(
        {
            "ok": False,
            "error": translate(
                _request_language(request),
                key,
            ),
        },
        status_code=status_code,
    )


def _check_csrf(
    request: Request,
    token=None,
):
    if not _same_origin(request):
        return _error(
            request,
            "invalid_request",
        )

    if not _csrf_valid(
        request,
        token,
    ):
        return _error(
            request,
            "csrf_invalid",
        )

    return None


def _rate_limited(
    request: Request,
    name: str,
) -> bool:
    limit, window = RATE_LIMITS[
        name
    ]

    identity = (
        request.session.get("user_id")
        or request.session.get("guest_id")
    )

    if (
        identity is None
        and request.client
    ):
        identity = request.client.host

    key = (
        name,
        str(identity or "unknown"),
    )

    now = time.monotonic()
    events = _rate_events[key]

    while (
        events
        and now - events[0] >= window
    ):
        events.popleft()

    if len(events) >= limit:
        return True

    events.append(now)

    return False


def is_admin_user(
    user_id,
) -> bool:
    return is_admin(
        "web",
        user_id,
    )


def _settings_access_allowed(
    request: Request,
) -> bool:
    if not _is_local_request(
        request
    ):
        return False

    return is_admin_user(
        request.session.get(
            "user_id"
        )
    )


def _check_data_access(
    request: Request,
    csrf=False,
):
    restore_remembered_user(
        request
    )

    if not _is_local_request(
        request
    ):
        return _error(
            request,
            "settings_local_only",
        )

    if csrf:
        error = _check_csrf(
            request
        )

        if error:
            return error

    if not is_admin_user(
        request.session.get(
            "user_id"
        )
    ):
        return _error(
            request,
            "settings_admin_required",
        )

    return None


def restore_remembered_user(
    request: Request,
):
    if request.session.get(
        "user_id"
    ):
        return

    token = request.cookies.get(
        "remember_user"
    )

    if not token:
        return

    try:
        username = remember_serializer.loads(
            token,
            max_age=REMEMBER_SECONDS,
        )
    except BadSignature:
        return

    user = get_user_by_username(
        username
    )

    if not user:
        return

    request.session[
        "user_id"
    ] = user[0]

    request.session[
        "username"
    ] = user[1]


def get_guest_id(
    request: Request,
):
    guest_id = request.session.get(
        "guest_id"
    )

    if (
        not guest_id
        or get_guest_message_count(
            guest_id
        )
        is None
    ):
        guest_id = create_guest()

        request.session[
            "guest_id"
        ] = guest_id

    return guest_id


def sanitize_document_name(
    filename,
):
    filename = (
        str(filename or "")
        .replace("\\", "/")
        .split("/")[-1]
        .strip()
    )

    path = Path(filename)

    stem = re.sub(
        r"[^\w\-(). ]",
        "_",
        path.stem.strip(),
        flags=re.UNICODE,
    )

    stem = re.sub(
        r"\s+",
        " ",
        stem,
    ).strip(" .") or "document"

    return (
        stem[:120]
        + path.suffix.lower()
    )


def validate_uploaded_document(
    path: Path,
    language: str,
):
    extension = path.suffix.lower()

    if extension == ".pdf":
        with path.open(
            "rb"
        ) as file:
            if (
                file.read(5)
                != b"%PDF-"
            ):
                raise ValueError(
                    translate(
                        language,
                        "invalid_pdf",
                    )
                )

        return

    if extension == ".docx":
        if not zipfile.is_zipfile(
            path
        ):
            raise ValueError(
                translate(
                    language,
                    "invalid_docx",
                )
            )

        with zipfile.ZipFile(
            path,
            "r",
        ) as archive:
            names = set(
                archive.namelist()
            )

            if (
                "[Content_Types].xml"
                not in names
            ):
                raise ValueError(
                    translate(
                        language,
                        "invalid_docx_structure",
                    )
                )

            total_size = sum(
                item.file_size
                for item
                in archive.infolist()
            )

            if (
                total_size
                > MAX_DOCX_UNCOMPRESSED_BYTES
            ):
                raise ValueError(
                    translate(
                        language,
                        "docx_too_large",
                    )
                )

        return

    with path.open(
        "rb"
    ) as file:
        if (
            b"\x00"
            in file.read(4096)
        ):
            raise ValueError(
                translate(
                    language,
                    "not_text_document",
                )
            )


def get_web_role(
    user_id,
):
    if is_admin_user(
        user_id
    ):
        return "admin"

    if user_id:
        return "user"

    return "guest"


def normalize_web_tool(
    tool,
):
    tool = str(
        tool or ""
    ).strip()

    return (
        tool
        if tool in WEB_TOOLS
        else None
    )


def _settings_snapshot():
    settings = load_settings()
    secret_data = load_secrets()
    admin = get_web_admin()

    return {
        "general": settings[
            "general"
        ],
        "model": {
            "ollama_host": settings[
                "model"
            ][
                "ollama_host"
            ],
            "chat_model": settings[
                "model"
            ][
                "chat_model"
            ],
            "embedding_model": settings[
                "model"
            ][
                "embedding_model"
            ],
        },
        "web": settings[
            "web"
        ],
        "telegram": {
            "enabled": settings[
                "telegram"
            ][
                "enabled"
            ],
            "bot_token": "",
            "bot_token_configured": bool(
                secret_data[
                    "telegram_bot_token"
                ]
            ),
            "authorized_user_id": (
                secret_data[
                    "telegram_user_id"
                ]
            ),
        },
        "voice": settings[
            "voice"
        ],
        "local_admin": settings[
            "local_admin"
        ],
        "help": settings[
            "help"
        ],
        "web_admin": {
            "configured": bool(
                admin
            ),
            "username": (
                admin[1]
                if admin
                else ""
            ),
        },
    }


def _normalize_test_host(
    host: str,
) -> str:
    host = str(
        host or ""
    ).strip().rstrip("/")

    parsed = urlparse(
        host
    )

    if (
        parsed.scheme
        not in {"http", "https"}
        or not parsed.netloc
        or parsed.path
        not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Invalid Ollama host."
        )

    return host


def _list_ollama_models(
    host: str,
) -> list[str]:
    response = requests.get(
        f"{host}/api/tags",
        timeout=5,
    )

    response.raise_for_status()

    result = []

    for item in (
        response.json()
        .get(
            "models",
            [],
        )
    ):
        if not isinstance(
            item,
            dict,
        ):
            continue

        name = (
            item.get("name")
            or item.get("model")
        )

        if name:
            result.append(
                str(name)
            )

    return result


def _validate_custom_paths(
    paths: list[str],
) -> list[str]:
    result = []
    seen = set()

    for value in paths:
        path = (
            validate_custom_access_root(
                value
            )
        )

        normalized = str(
            path
        )

        key = normalized.casefold()

        if key in seen:
            continue

        seen.add(key)
        result.append(
            normalized
        )

    return result


@app.get("/")
def home(
    request: Request,
):
    restore_remembered_user(
        request
    )

    user_id = request.session.get(
        "user_id"
    )

    username = request.session.get(
        "username"
    )

    remembered = bool(
        request.cookies.get(
            "remember_user"
        )
    )

    remaining = None

    if not user_id:
        guest_id = get_guest_id(
            request
        )

        used = get_guest_message_count(
            guest_id
        )

        remaining = max(
            GUEST_MESSAGE_LIMIT - used,
            0,
        )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=_template_context(
            request,
            logged_in=bool(
                user_id
            ),
            username=username,
            is_admin=is_admin_user(
                user_id
            ),
            role=get_web_role(
                user_id
            ),
            remembered=remembered,
            guest_remaining=remaining,
        ),
    )


@app.post("/language")
def change_language(
    request: Request,
    data: LanguageRequest,
):
    error = _check_csrf(
        request
    )

    if error:
        return error

    language = (
        data.language
        .strip()
        .lower()
    )

    if language not in {
        "tr",
        "en",
    }:
        return _error(
            request,
            "invalid_request",
            400,
        )

    request.session[
        "ui_language"
    ] = language

    return {
        "ok": True,
        "language": language,
    }


@app.get("/login")
def login_page(
    request: Request,
):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context=_template_context(
            request,
            error=None,
        ),
    )


@app.post("/login")
async def login(
    request: Request,
):
    form = await request.form()

    error = _check_csrf(
        request,
        str(
            form.get(
                "csrf_token",
                "",
            )
        ),
    )

    if error:
        return error

    username = str(
        form.get(
            "username",
            "",
        )
    ).strip()

    password = str(
        form.get(
            "password",
            "",
        )
    )

    remember = (
        form.get(
            "remember"
        )
        == "1"
    )

    user = get_user_by_username(
        username
    )

    if (
        not user
        or not verify_password(
            password,
            user[2],
        )
    ):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context=_template_context(
                request,
                error=translate(
                    _request_language(
                        request
                    ),
                    "invalid_credentials",
                ),
            ),
            status_code=401,
        )

    request.session[
        "user_id"
    ] = user[0]

    request.session[
        "username"
    ] = user[1]

    request.session[
        "csrf_token"
    ] = secrets.token_urlsafe(
        32
    )

    response = RedirectResponse(
        "/",
        status_code=303,
    )

    if remember:
        response.set_cookie(
            "remember_user",
            remember_serializer.dumps(
                user[1]
            ),
            max_age=REMEMBER_SECONDS,
            httponly=True,
            samesite="lax",
        )
    else:
        response.delete_cookie(
            "remember_user"
        )

    return response


@app.get("/register")
def register_page(
    request: Request,
):
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context=_template_context(
            request,
            error=None,
        ),
    )


@app.post("/register")
async def register(
    request: Request,
):
    form = await request.form()

    error = _check_csrf(
        request,
        str(
            form.get(
                "csrf_token",
                "",
            )
        ),
    )

    if error:
        return error

    language = _request_language(
        request
    )

    username = str(
        form.get(
            "username",
            "",
        )
    ).strip()

    password = str(
        form.get(
            "password",
            "",
        )
    )

    if len(username) < 3:
        message = translate(
            language,
            "username_too_short",
        )
    elif len(password) < 6:
        message = translate(
            language,
            "password_too_short",
        )
    elif get_user_by_username(
        username
    ):
        message = translate(
            language,
            "username_in_use",
        )
    else:
        message = None

    if message:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context=_template_context(
                request,
                error=message,
            ),
            status_code=400,
        )

    try:
        user_id = create_regular_user(
            username,
            password,
        )
    except ValueError:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context=_template_context(
                request,
                error=translate(
                    language,
                    "username_in_use",
                ),
            ),
            status_code=400,
        )

    request.session[
        "user_id"
    ] = user_id

    request.session[
        "username"
    ] = username

    request.session[
        "csrf_token"
    ] = secrets.token_urlsafe(
        32
    )

    return RedirectResponse(
        "/",
        status_code=303,
    )


@app.post("/logout")
async def logout(
    request: Request,
):
    form = await request.form()

    error = _check_csrf(
        request,
        str(
            form.get(
                "csrf_token",
                "",
            )
        ),
    )

    if error:
        return error

    request.session.pop(
        "user_id",
        None,
    )
    request.session.pop(
        "username",
        None,
    )
    request.session.pop(
        "last_document",
        None,
    )
    request.session["csrf_token"] = secrets.token_urlsafe(
        32
    )

    response = RedirectResponse(
        "/",
        status_code=303,
    )

    response.delete_cookie(
        "remember_user"
    )

    return response


@app.post("/browser-session-reset")
def browser_session_reset(
    request: Request,
):
    error = _check_csrf(
        request
    )

    if error:
        return error

    request.session.pop(
        "user_id",
        None,
    )

    request.session.pop(
        "username",
        None,
    )

    request.session.pop(
        "last_document",
        None,
    )

    request.session[
        "csrf_token"
    ] = secrets.token_urlsafe(
        32
    )

    return {
        "ok": True,
    }


@app.get("/settings")
def settings_page(
    request: Request,
):
    restore_remembered_user(
        request
    )

    if not _is_local_request(
        request
    ):
        return templates.TemplateResponse(
            request=request,
            name="settings.html",
            context=_template_context(
                request,
                settings=None,
                error=translate(
                    _request_language(
                        request
                    ),
                    "settings_local_only",
                ),
            ),
            status_code=403,
        )

    if not _settings_access_allowed(
        request
    ):
        return RedirectResponse(
            "/login",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context=_template_context(
            request,
            settings=_settings_snapshot(),
            error=None,
        ),
    )


@app.get("/settings/data-summary")
def settings_data_summary(
    request: Request,
):
    error = _check_data_access(
        request
    )

    if error:
        return error

    return {
        "ok": True,
        "local_history": (
            memory_manager
            .get_message_count(
                "terminal"
            )
        ),
        "telegram_history": (
            memory_manager
            .get_message_count(
                "telegram"
            )
        ),
        "web_history": (
            get_all_web_message_count()
        ),
        "guest_usage": (
            get_guest_usage_count()
        ),
    }


@app.post(
    "/settings/clear-local-history"
)
def clear_local_history(
    request: Request,
):
    error = _check_data_access(
        request,
        csrf=True,
    )

    if error:
        return error

    deleted = (
        memory_manager
        .clear_messages(
            "terminal"
        )
    )

    return {
        "ok": True,
        "deleted": deleted,
    }


@app.post(
    "/settings/clear-telegram-history"
)
def clear_telegram_history(
    request: Request,
):
    error = _check_data_access(
        request,
        csrf=True,
    )

    if error:
        return error

    deleted = (
        memory_manager
        .clear_messages(
            "telegram"
        )
    )

    return {
        "ok": True,
        "deleted": deleted,
    }


@app.post(
    "/settings/clear-web-history"
)
def clear_web_history(
    request: Request,
):
    error = _check_data_access(
        request,
        csrf=True,
    )

    if error:
        return error

    deleted = (
        clear_all_web_history()
    )

    return {
        "ok": True,
        "deleted": deleted,
    }


@app.post(
    "/settings/clear-guest-usage"
)
def clear_guest_usage_data(
    request: Request,
):
    error = _check_data_access(
        request,
        csrf=True,
    )

    if error:
        return error

    deleted = clear_guest_usage()

    request.session.pop(
        "guest_id",
        None,
    )

    return {
        "ok": True,
        "deleted": deleted,
    }


@app.post(
    "/settings/validate-local-path"
)
def validate_local_path(
    request: Request,
    data: CustomPathRequest,
):
    restore_remembered_user(
        request
    )

    if not _is_local_request(
        request
    ):
        return _error(
            request,
            "settings_local_only",
        )

    error = _check_csrf(
        request
    )

    if error:
        return error

    if not _settings_access_allowed(
        request
    ):
        return _error(
            request,
            "settings_admin_required",
        )

    try:
        path = (
            validate_custom_access_root(
                data.path
            )
        )
    except (
        FileNotFoundError,
        ValueError,
        PermissionError,
        OSError,
    ) as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
            },
            status_code=400,
        )

    language = _request_language(
        request
    )

    message = (
        "Klasör Custom Local Access için kullanılabilir."
        if language == "tr"
        else "The folder can be used for Custom Local Access."
    )

    return {
        "ok": True,
        "path": str(path),
        "message": message,
    }


@app.post("/settings")
def update_application_settings(
    request: Request,
    data: SettingsRequest,
):
    restore_remembered_user(
        request
    )

    if not _is_local_request(
        request
    ):
        return _error(
            request,
            "settings_local_only",
        )

    error = _check_csrf(
        request
    )

    if error:
        return error

    if not _settings_access_allowed(
        request
    ):
        return _error(
            request,
            "settings_admin_required",
        )

    language = (
        data.general.language
        .strip()
        .lower()
    )

    if language not in {
        "tr",
        "en",
    }:
        language = get_language()

    current = load_settings()
    current_secrets = load_secrets()

    bot_token = (
        data.telegram
        .bot_token
        .strip()
        or current_secrets[
            "telegram_bot_token"
        ]
    )

    telegram_user_id = (
        data.telegram
        .authorized_user_id
        .strip()
        or current_secrets[
            "telegram_user_id"
        ]
    )

    if (
        telegram_user_id
        and not telegram_user_id.isdigit()
    ):
        return JSONResponse(
            {
                "ok": False,
                "error": translate(
                    language,
                    "telegram_id_invalid",
                ),
            },
            status_code=400,
        )

    if (
        data.telegram.enabled
        and not bot_token
    ):
        return JSONResponse(
            {
                "ok": False,
                "error": translate(
                    language,
                    "telegram_token_required",
                ),
            },
            status_code=400,
        )

    if (
        data.telegram.enabled
        and not telegram_user_id
    ):
        return JSONResponse(
            {
                "ok": False,
                "error": translate(
                    language,
                    "telegram_id_required",
                ),
            },
            status_code=400,
        )

    try:
        parse_hotkey(
            data.voice.hotkey
        )
    except ValueError as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
            },
            status_code=400,
        )

    voice_scope = data.voice.scope.strip().lower()
    if voice_scope not in {"global", "local_admin"}:
        return _error(request, "invalid_request", 400)

    access_mode = (
        data.local_admin
        .access_mode
        .strip()
        .lower()
    )

    if access_mode not in {
        "safe",
        "custom",
    }:
        return _error(
            request,
            "invalid_request",
            400,
        )

    if (
        access_mode == "custom"
        and not data.local_admin
        .custom_access_acknowledged
    ):
        message = (
            "Custom Local Access için riskleri kabul etmeniz gerekir."
            if language == "tr"
            else "You must acknowledge the risks before enabling Custom Local Access."
        )

        return JSONResponse(
            {
                "ok": False,
                "error": message,
            },
            status_code=400,
        )

    try:
        allowed_paths = (
            _validate_custom_paths(
                data.local_admin
                .allowed_paths
            )
        )
    except (
        FileNotFoundError,
        ValueError,
        PermissionError,
        OSError,
    ) as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
            },
            status_code=400,
        )

    admin_before = get_web_admin()

    admin_username = (
        data.web_admin
        .username
        .strip()
    )

    admin_password = (
        data.web_admin.password
    )

    if len(admin_username) < 3:
        return JSONResponse(
            {
                "ok": False,
                "error": translate(
                    language,
                    "username_too_short",
                ),
            },
            status_code=400,
        )

    if (
        admin_before is None
        and len(admin_password) < 6
    ):
        return JSONResponse(
            {
                "ok": False,
                "error": translate(
                    language,
                    "password_too_short",
                ),
            },
            status_code=400,
        )

    if (
        admin_before is not None
        and admin_password
        and len(admin_password) < 6
    ):
        return JSONResponse(
            {
                "ok": False,
                "error": translate(
                    language,
                    "password_too_short",
                ),
            },
            status_code=400,
        )

    existing = get_user_by_username(
        admin_username
    )

    if (
        existing
        and (
            admin_before is None
            or int(existing[0])
            != int(admin_before[0])
        )
    ):
        return JSONResponse(
            {
                "ok": False,
                "error": translate(
                    language,
                    "username_in_use",
                ),
            },
            status_code=400,
        )

    current[
        "general"
    ] = {
        "agent_name": (
            data.general
            .agent_name
            .strip()
        ),
        "language": language,
    }

    current[
        "model"
    ][
        "ollama_host"
    ] = (
        data.model
        .ollama_host
        .strip()
    )

    current[
        "model"
    ][
        "chat_model"
    ] = (
        data.model
        .chat_model
        .strip()
    )

    current[
        "web"
    ] = {
        "enabled": data.web.enabled,
        "access": data.web.access,
        "port": data.web.port,
        "open_browser": (
            data.web.open_browser
        ),
    }

    current[
        "telegram"
    ][
        "enabled"
    ] = data.telegram.enabled

    current[
        "voice"
    ] = {
        "enabled": data.voice.enabled,
        "hotkey": (
            data.voice
            .hotkey
            .strip()
        ),
        "scope": voice_scope,
    }

    current[
        "local_admin"
    ] = {
        "enabled": (
            data.local_admin.enabled
        ),
        "access_mode": access_mode,
        "allowed_paths": allowed_paths,
        "custom_access_acknowledged": (
            data.local_admin
            .custom_access_acknowledged
        ),
    }

    current[
        "help"
    ][
        "show_info_buttons"
    ] = (
        data.help
        .show_info_buttons
    )

    try:
        saved_settings = (
            save_settings(
                current
            )
        )

        save_secrets(
            {
                "telegram_bot_token": (
                    bot_token
                ),
                "telegram_user_id": (
                    telegram_user_id
                ),
            }
        )

        admin = (
            save_web_admin_credentials(
                admin_username,
                admin_password,
            )
        )

    except ValueError as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
            },
            status_code=400,
        )

    request.session[
        "user_id"
    ] = admin[0]

    request.session[
        "username"
    ] = admin[1]

    request.session[
        "ui_language"
    ] = (
        saved_settings[
            "general"
        ][
            "language"
        ]
    )

    request.session[
        "csrf_token"
    ] = secrets.token_urlsafe(
        32
    )

    refresh_voice_hotkey(agent)

    return {
        "ok": True,
        "message": translate(
            language,
            "settings_saved",
        ),
        "restart_required": True,
        "restart_message": translate(
            language,
            "restart_required",
        ),
        "admin_message": translate(
            language,
            (
                "admin_created"
                if admin_before is None
                else "admin_updated"
            ),
        ),
        "csrf_token": (
            request.session[
                "csrf_token"
            ]
        ),
    }


@app.post(
    "/settings/test-ollama"
)
def test_ollama(
    request: Request,
    data: OllamaTestRequest,
):
    restore_remembered_user(
        request
    )

    if not _is_local_request(
        request
    ):
        return _error(
            request,
            "settings_local_only",
        )

    error = _check_csrf(
        request
    )

    if error:
        return error

    if not _settings_access_allowed(
        request
    ):
        return _error(
            request,
            "settings_admin_required",
        )

    language = _request_language(
        request
    )

    try:
        host = _normalize_test_host(
            data.host
        )

        models = _list_ollama_models(
            host
        )

    except (
        ValueError,
        requests.RequestException,
    ):
        return {
            "ok": False,
            "connected": False,
            "message": translate(
                language,
                "ollama_unavailable",
            ),
        }

    model = str(
        data.model or ""
    ).strip()

    model_found = (
        model in models
        if model
        else None
    )

    embedding_model = load_settings()["model"]["embedding_model"]
    embedding_found = embedding_model in models

    if (
        model
        and not model_found
    ):
        message = translate(
            language,
            "ollama_model_missing",
        )
    elif model:
        message = translate(
            language,
            "ollama_model_found",
        )
    else:
        message = translate(
            language,
            "ollama_connected",
        )

    return {
        "ok": True,
        "connected": True,
        "model_found": model_found,
        "embedding_model": embedding_model,
        "embedding_found": embedding_found,
        "models": models,
        "message": message,
    }


@app.post("/upload-document")
async def upload_document(
    request: Request,
    document: UploadFile = File(...),
):
    restore_remembered_user(
        request
    )

    language = _request_language(
        request
    )

    target_path = None

    try:
        error = _check_csrf(
            request
        )

        if error:
            return error

        if not request.session.get(
            "user_id"
        ):
            return _error(
                request,
                "authentication_required",
                401,
            )

        if _rate_limited(
            request,
            "upload",
        ):
            return _error(
                request,
                "rate_limit_exceeded",
                429,
            )

        original_name = (
            document.filename
            or ""
        ).strip()

        if not original_name:
            raise ValueError(
                translate(
                    language,
                    "filename_missing",
                )
            )

        safe_name = (
            sanitize_document_name(
                original_name
            )
        )

        extension = Path(
            safe_name
        ).suffix.lower()

        if (
            extension
            not in DOCUMENT_EXTENSIONS
        ):
            raise ValueError(
                translate(
                    language,
                    "unsupported_document",
                )
            )

        target_path = (
            DOCUMENTS_DIR
            / safe_name
        )

        if target_path.exists():
            return JSONResponse(
                {
                    "ok": False,
                    "error": translate(
                        language,
                        "document_exists",
                    ),
                },
                status_code=409,
            )

        written = 0

        with target_path.open(
            "xb"
        ) as output:
            while True:
                chunk = (
                    await document.read(
                        UPLOAD_CHUNK_BYTES
                    )
                )

                if not chunk:
                    break

                written += len(chunk)

                if (
                    written
                    > MAX_DOCUMENT_BYTES
                ):
                    raise ValueError(
                        translate(
                            language,
                            "document_too_large",
                        )
                    )

                output.write(
                    chunk
                )

        if not written:
            raise ValueError(
                translate(
                    language,
                    "document_empty",
                )
            )

        validate_uploaded_document(
            target_path,
            language,
        )

        chunk_count = (
            await asyncio.to_thread(
                index_document,
                str(target_path),
            )
        )

        request.session[
            "last_document"
        ] = safe_name

        return {
            "ok": True,
            "filename": safe_name,
            "chunks": chunk_count,
            "message": (
                f"{safe_name} hazır."
                if language == "tr"
                else f"{safe_name} is ready."
            ),
        }

    except FileExistsError:
        return JSONResponse(
            {
                "ok": False,
                "error": translate(
                    language,
                    "document_exists",
                ),
            },
            status_code=409,
        )

    except ValueError as exc:
        if (
            target_path
            and target_path.exists()
        ):
            try:
                target_path.unlink()
            except OSError:
                pass

        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
            },
            status_code=400,
        )

    except Exception as exc:
        if (
            target_path
            and target_path.exists()
        ):
            try:
                target_path.unlink()
            except OSError:
                pass

        print(
            "[Web] Document upload error: "
            f"{type(exc).__name__}"
        )

        return JSONResponse(
            {
                "ok": False,
                "error": translate(
                    language,
                    "document_upload_failed",
                ),
            },
            status_code=500,
        )

    finally:
        await document.close()


@app.post("/transcribe-audio")
async def transcribe_web_audio(
    request: Request,
    audio: UploadFile = File(...),
):
    restore_remembered_user(
        request
    )

    language = _request_language(
        request
    )

    temp_path = None

    try:
        error = _check_csrf(
            request
        )

        if error:
            return error

        if not request.session.get(
            "user_id"
        ):
            return _error(
                request,
                "authentication_required",
                401,
            )

        if _rate_limited(
            request,
            "transcribe",
        ):
            return _error(
                request,
                "rate_limit_exceeded",
                429,
            )

        suffix = Path(
            audio.filename or ""
        ).suffix.lower() or ".webm"

        if (
            suffix
            not in AUDIO_EXTENSIONS
        ):
            raise ValueError(
                translate(
                    language,
                    "unsupported_audio",
                )
            )

        written = 0

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:
            temp_path = Path(
                temp_file.name
            )

            while True:
                chunk = (
                    await audio.read(
                        UPLOAD_CHUNK_BYTES
                    )
                )

                if not chunk:
                    break

                written += len(chunk)

                if (
                    written
                    > MAX_AUDIO_BYTES
                ):
                    raise ValueError(
                        translate(
                            language,
                            "audio_too_large",
                        )
                    )

                temp_file.write(
                    chunk
                )

        if not written:
            raise ValueError(
                translate(
                    language,
                    "audio_empty",
                )
            )

        text = await asyncio.to_thread(
            transcribe_audio,
            str(temp_path),
            language,
        )

        if not text:
            return JSONResponse(
                {
                    "ok": False,
                    "error": translate(
                        language,
                        "speech_not_detected",
                    ),
                },
                status_code=400,
            )

        return {
            "ok": True,
            "text": text,
        }

    except ValueError as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
            },
            status_code=400,
        )

    except Exception as exc:
        print(
            "[Web] Audio transcription error: "
            f"{type(exc).__name__}"
        )

        return JSONResponse(
            {
                "ok": False,
                "error": translate(
                    language,
                    "transcription_failed",
                ),
            },
            status_code=500,
        )

    finally:
        await audio.close()

        if (
            temp_path
            and temp_path.exists()
        ):
            try:
                temp_path.unlink()
            except OSError:
                pass


@app.post("/chat")
def chat(
    request: Request,
    data: ChatRequest,
):
    error = _check_csrf(
        request
    )

    if error:
        return error

    restore_remembered_user(
        request
    )

    language = _request_language(
        request
    )

    user_id = request.session.get(
        "user_id"
    )

    message = data.message.strip()

    if not message:
        return {
            "response": translate(
                language,
                "empty_message",
            ),
            "logged_in": bool(
                user_id
            ),
        }

    used = None

    if not user_id:
        guest_id = get_guest_id(
            request
        )

        used = get_guest_message_count(
            guest_id
        )

        if (
            used
            >= GUEST_MESSAGE_LIMIT
        ):
            return {
                "response": translate(
                    language,
                    "guest_limit",
                ),
                "logged_in": False,
                "guest_messages": used,
                "guest_limit": (
                    GUEST_MESSAGE_LIMIT
                ),
            }

        increase_guest_message_count(
            guest_id
        )

        used += 1

    if agent is None:
        return {
            "response": translate(
                language,
                "agent_not_ready",
            ),
            "logged_in": bool(
                user_id
            ),
        }

    selected_tool = (
        normalize_web_tool(
            data.tool
        )
    )

    document_source = (
        request.session.get(
            "last_document"
        )
    )

    print(
        "[Web] Request received "
        f"({get_web_role(user_id)})"
    )

    try:
        response = agent.run(
            message,
            source="web",
            user_id=user_id,
            selected_tool=selected_tool,
            document_source=(
                document_source
            ),
        )

    except PermissionError:
        return JSONResponse(
            {
                "response": translate(
                    language,
                    "permission_denied",
                ),
                "logged_in": bool(
                    user_id
                ),
            },
            status_code=403,
        )

    except Exception as exc:
        print(
            "[Web] Agent request error: "
            f"{type(exc).__name__}"
        )

        return JSONResponse(
            {
                "response": translate(
                    language,
                    "request_failed",
                ),
                "logged_in": bool(
                    user_id
                ),
            },
            status_code=500,
        )

    result = {
        "response": str(response),
        "logged_in": bool(
            user_id
        ),
    }

    if not user_id:
        result[
            "guest_messages"
        ] = used

        result[
            "guest_limit"
        ] = GUEST_MESSAGE_LIMIT

    return result
