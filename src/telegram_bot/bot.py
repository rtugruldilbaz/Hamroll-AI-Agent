import asyncio
import tempfile
import threading
from pathlib import Path

from telegram import Bot, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from config.app_settings import (
    get_language,
    get_telegram_chat_id,
    load_secrets,
    load_settings,
    save_telegram_chat_id,
    validate_telegram_settings,
)
from config.i18n import translate
from security.permissions import is_admin
from speech.transcriber import transcribe_audio


SEND_FILE_PREFIX = "__SEND_FILE__::"
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class TelegramDisabledError(RuntimeError):
    pass


class TelegramConfigurationError(RuntimeError):
    pass


agent = None
_bot_thread = None
_bot_application = None
_bot_loop = None
_bot_running = threading.Event()
_bot_starting = threading.Event()
_bot_stop_requested = threading.Event()
_bot_lock = threading.RLock()


def _record_event(event, user_id=None, detail=None):
    if agent is None:
        return

    try:
        agent.record_event(
            "telegram",
            event,
            user_id=user_id,
            detail=detail,
        )
    except AttributeError:
        pass


def get_bot_status():
    if _bot_running.is_set():
        return "running"

    if _bot_starting.is_set():
        return "starting"

    return "stopped"


def stop_bot():
    with _bot_lock:
        thread = _bot_thread
        application = _bot_application
        loop = _bot_loop

    _bot_stop_requested.set()

    if application is not None and loop is not None and loop.is_running():
        loop.call_soon_threadsafe(
            application.stop_running
        )

    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=5)

    return thread is None or not thread.is_alive()


def _language():
    language = get_language()
    return language if language in {"tr", "en"} else "en"


def _text(key, **values):
    return translate(
        _language(),
        key,
        **values,
    )


def _telegram_credentials():
    data = load_secrets()

    return (
        str(
            data.get(
                "telegram_bot_token",
                "",
            )
        ).strip(),
        str(
            data.get(
                "telegram_user_id",
                "",
            )
        ).strip(),
    )


def _telegram_enabled():
    return bool(
        load_settings()
        .get("telegram", {})
        .get("enabled", False)
    )


def is_authorized(user_id):
    return is_admin(
        "telegram",
        user_id,
    )


def save_chat_id(chat_id):
    save_telegram_chat_id(
        chat_id
    )


def get_chat_id():
    chat_id = get_telegram_chat_id()

    if chat_id is not None:
        return chat_id

    _, authorized_user_id = (
        _telegram_credentials()
    )

    if authorized_user_id.isdigit():
        return int(
            authorized_user_id
        )

    raise RuntimeError(
        "Telegram chat ID is not available."
    )


def _require_telegram():
    if not _telegram_enabled():
        raise TelegramDisabledError(
            "Telegram integration is disabled in Settings."
        )

    try:
        validate_telegram_settings()
    except (ValueError, RuntimeError) as error:
        raise TelegramConfigurationError(
            "Telegram settings are incomplete or invalid."
        ) from error

    bot_token, _ = (
        _telegram_credentials()
    )

    return bot_token


async def _send_telegram_message(
    message,
):
    bot_token = _require_telegram()

    async with Bot(
        token=bot_token
    ) as bot:
        await bot.send_message(
            chat_id=get_chat_id(),
            text=str(message),
        )


def send_telegram_message(
    message,
):
    message = str(
        message
    ).strip()

    if not message:
        raise ValueError(
            "Telegram message cannot be empty."
        )

    asyncio.run(
        _send_telegram_message(
            message
        )
    )

    return (
        "Telegram message sent successfully."
    )


async def _send_telegram_file(
    file_path,
):
    bot_token = _require_telegram()
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"File to send was not found: {path}"
        )

    if not path.is_file():
        raise ValueError(
            "The selected path is not a file."
        )

    async with Bot(
        token=bot_token
    ) as bot:
        with path.open(
            "rb"
        ) as file:
            await bot.send_document(
                chat_id=get_chat_id(),
                document=file,
                filename=path.name,
            )


def send_telegram_file(
    file_path,
):
    asyncio.run(
        _send_telegram_file(
            file_path
        )
    )

    return (
        "Telegram file sent successfully: "
        f"{Path(file_path).name}"
    )


async def send_response(
    update: Update,
    response,
):
    response = str(
        response or ""
    )

    if response.startswith(
        SEND_FILE_PREFIX
    ):
        file_path = Path(
            response.removeprefix(
                SEND_FILE_PREFIX
            )
        )

        if (
            not file_path.exists()
            or not file_path.is_file()
        ):
            await update.message.reply_text(
                _text(
                    "request_failed"
                )
            )
            return

        try:
            with file_path.open(
                "rb"
            ) as file:
                await update.message.reply_document(
                    document=file,
                    filename=file_path.name,
                )

        except Exception as error:
            print(
                "[Telegram] File send error: "
                f"{type(error).__name__}"
            )

            await update.message.reply_text(
                _text(
                    "request_failed"
                )
            )

        return

    if not response:
        return

    for start in range(
        0,
        len(response),
        4000,
    ):
        await update.message.reply_text(
            response[
                start:start + 4000
            ]
        )


async def _authorize_update(
    update: Update,
):
    user = update.effective_user
    chat = update.effective_chat
    message = update.message

    if (
        user is None
        or chat is None
        or message is None
    ):
        return None

    if not is_authorized(
        user.id
    ):
        await message.reply_text(
            _text(
                "permission_denied"
            )
        )
        return None

    save_chat_id(
        chat.id
    )

    return user.id


async def _run_agent(
    update: Update,
    message,
    user_id,
):
    if agent is None:
        await update.message.reply_text(
            _text(
                "agent_not_ready"
            )
        )
        return

    response = await asyncio.to_thread(
        agent.run,
        message,
        "telegram",
        user_id,
    )

    await send_response(
        update,
        response,
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = await _authorize_update(
        update
    )

    if user_id is None:
        return

    message = str(
        update.message.text or ""
    ).strip()

    if not message:
        return

    try:
        await _run_agent(
            update,
            message,
            user_id,
        )

    except PermissionError:
        await update.message.reply_text(
            _text(
                "permission_denied"
            )
        )

    except Exception as error:
        _record_event(
            "message_error",
            user_id=user_id,
            detail=type(error).__name__,
        )
        print(
            "[Telegram] Message processing error: "
            f"{type(error).__name__}"
        )

        await update.message.reply_text(
            _text(
                "request_failed"
            )
        )


async def handle_voice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = await _authorize_update(
        update
    )

    if user_id is None:
        return

    audio = (
        update.message.voice
        or update.message.audio
    )

    if audio is None:
        await update.message.reply_text(
            _text(
                "transcription_failed"
            )
        )
        return

    telegram_file = await audio.get_file()
    temp_path = None

    try:
        suffix = (
            Path(
                getattr(
                    audio,
                    "file_name",
                    "",
                )
                or ""
            ).suffix.lower()
            or ".ogg"
        )

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:
            temp_path = Path(
                temp_file.name
            )

        await telegram_file.download_to_drive(
            custom_path=temp_path
        )

        if (
            temp_path.stat().st_size
            > MAX_AUDIO_BYTES
        ):
            await update.message.reply_text(
                _text(
                    "audio_too_large"
                )
            )
            return

        text = await asyncio.to_thread(
            transcribe_audio,
            str(temp_path),
            _language(),
        )

        if not text:
            await update.message.reply_text(
                _text(
                    "speech_not_detected"
                )
            )
            return

        await _run_agent(
            update,
            text,
            user_id,
        )

    except PermissionError:
        await update.message.reply_text(
            _text(
                "permission_denied"
            )
        )

    except Exception as error:
        print(
            "[Telegram] Voice processing error: "
            f"{type(error).__name__}"
        )

        await update.message.reply_text(
            _text(
                "transcription_failed"
            )
        )

    finally:
        if (
            temp_path
            and temp_path.exists()
        ):
            try:
                temp_path.unlink()
            except OSError:
                pass


def _run_bot(agent_instance, bot_token):
    global agent, _bot_application, _bot_loop, _bot_thread

    agent = agent_instance
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def telegram_started(application):
        _bot_starting.clear()

        if _bot_stop_requested.is_set():
            application.stop_running()
            return

        _bot_running.set()
        _record_event("connection_active")
        print("[System] Telegram connection is active.")

    try:
        application = (
            Application.builder()
            .token(bot_token)
            .connect_timeout(30)
            .read_timeout(30)
            .write_timeout(30)
            .pool_timeout(30)
            .post_init(telegram_started)
            .build()
        )

        with _bot_lock:
            _bot_application = application
            _bot_loop = loop

        application.add_handler(
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND,
                handle_message,
            )
        )

        application.add_handler(
            MessageHandler(
                filters.VOICE
                | filters.AUDIO,
                handle_voice,
            )
        )

        application.run_polling(
            stop_signals=None,
            close_loop=False,
            drop_pending_updates=True,
        )

    except Exception as error:
        _record_event(
            "connection_error",
            detail=type(error).__name__,
        )
        print(
            "[System] Telegram connection error: "
            f"{type(error).__name__}"
        )

    finally:
        was_running = _bot_running.is_set()
        _bot_running.clear()
        _bot_starting.clear()

        if was_running:
            _record_event("connection_stopped")

        with _bot_lock:
            _bot_application = None
            _bot_loop = None
            _bot_thread = None

        if not loop.is_closed():
            loop.close()


def start_bot(agent_instance):
    global agent, _bot_thread

    agent = agent_instance

    if not _telegram_enabled():
        return False

    try:
        bot_token = _require_telegram()
    except Exception as error:
        _record_event(
            "connection_error",
            detail=type(error).__name__,
        )
        raise

    with _bot_lock:
        if _bot_thread is not None and _bot_thread.is_alive():
            return True

        _bot_stop_requested.clear()
        _bot_starting.set()
        _bot_thread = threading.Thread(
            target=_run_bot,
            args=(agent_instance, bot_token),
            daemon=True,
        )
        _bot_thread.start()

    return True
