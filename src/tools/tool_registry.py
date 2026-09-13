from config.app_settings import get_language
from config.i18n import translate
from memory.memory_manager import MemoryManager
from rag.context_builder import build_context
from security.permissions import is_admin
from telegram_bot.bot import send_telegram_file, send_telegram_message
from tools.calculator import calculate
from tools.file_tools import (
    create_file,
    execute_pending_file_action,
    list_directory,
    manage_file,
    open_path,
    read_file,
    search_files,
    send_file as prepare_telegram_file,
    write_file,
)
from web.database import get_all_web_messages, get_user_web_messages


memory_manager = MemoryManager()


def _text(key):
    return translate(
        get_language(),
        key,
    )


def _format_agent_history(rows):
    return [
        f"[{message_source or 'legacy'}] {role}: {content}"
        for role, message_source, content in rows
    ]


def _format_web_history(rows):
    return [
        f"[web user_id={user_id}] {role}: {content}"
        for user_id, role, content in rows
    ]


def _agent_history(source=None, limit=None):
    rows = memory_manager.get_recent_messages(
        source=source,
        limit=limit,
    )

    if not rows:
        return _text("history_empty")

    return "\n".join(
        _format_agent_history(rows)
    )


def _web_history(user_id=None, limit=None, all_users=False):
    rows = (
        get_all_web_messages(limit=limit)
        if all_users
        else get_user_web_messages(
            user_id,
            limit=limit,
        )
    )

    if not rows:
        return _text("history_empty")

    return "\n".join(
        _format_web_history(rows)
    )


def get_recent_messages(
    source=None,
    limit=None,
    _source="terminal",
    _user_id=None,
):
    if limit is not None:
        limit = int(limit)

        if limit <= 0:
            raise ValueError(
                "History limit must be greater than zero."
            )

        limit = min(
            limit,
            100,
        )

    if source not in {
        None,
        "terminal",
        "telegram",
        "web",
    }:
        raise ValueError(
            "Invalid history source."
        )

    if _source == "terminal":
        if source == "web":
            return _web_history(
                limit=limit,
                all_users=True,
            )

        if source in {
            "terminal",
            "telegram",
        }:
            return _agent_history(
                source=source,
                limit=limit,
            )

        agent_rows = memory_manager.get_recent_messages(
            limit=limit
        )

        web_rows = get_all_web_messages(
            limit=limit
        )

        lines = []

        if agent_rows:
            lines.append(
                "=== TERMINAL / TELEGRAM ==="
            )

            lines.extend(
                _format_agent_history(
                    agent_rows
                )
            )

        if web_rows:
            if lines:
                lines.append("")

            lines.append(
                "=== WEB ==="
            )

            lines.extend(
                _format_web_history(
                    web_rows
                )
            )

        if not lines:
            return _text(
                "history_empty"
            )

        return "\n".join(lines)

    if _source == "web":
        if _user_id is None:
            raise PermissionError(
                _text(
                    "history_login_required"
                )
            )

        if is_admin(
            "web",
            _user_id,
        ):
            return _web_history(
                limit=limit,
                all_users=True,
            )

        return _web_history(
            user_id=_user_id,
            limit=limit,
        )

    if _source == "telegram":
        if not is_admin(
            "telegram",
            _user_id,
        ):
            raise PermissionError(
                _text(
                    "history_permission_denied"
                )
            )

        return _agent_history(
            source="telegram",
            limit=limit,
        )

    raise PermissionError(
        _text(
            "history_permission_denied"
        )
    )


def search_documents(
    query,
    source=None,
    top_k=3,
):
    return build_context(
        query,
        top_k=top_k,
        source=source,
    )


def telegram_send_message(
    message,
    _source="terminal",
    _user_id=None,
):
    if (
        _source != "terminal"
        and not is_admin(
            _source,
            _user_id,
        )
    ):
        raise PermissionError(
            _text(
                "permission_denied"
            )
        )

    return send_telegram_message(
        message
    )


def send_file(
    path,
    _source="terminal",
    _user_id=None,
):
    result = prepare_telegram_file(
        path,
        _source=_source,
        _user_id=_user_id,
    )

    if _source == "telegram":
        return result

    if not str(result).startswith(
        "__SEND_FILE__::"
    ):
        raise RuntimeError(
            "Telegram file path could not be prepared."
        )

    file_path = str(result).split(
        "::",
        1,
    )[1]

    return send_telegram_file(
        file_path
    )


TOOLS = {
    "calculate": calculate,
    "search_documents": search_documents,
    "get_recent_messages": get_recent_messages,
    "telegram_send_message": telegram_send_message,
    "create_file": create_file,
    "write_file": write_file,
    "read_file": read_file,
    "search_files": search_files,
    "list_directory": list_directory,
    "open_path": open_path,
    "manage_file": manage_file,
    "send_file": send_file,
}


IDENTITY_TOOLS = {
    "get_recent_messages",
    "telegram_send_message",
    "create_file",
    "write_file",
    "read_file",
    "search_files",
    "list_directory",
    "open_path",
    "manage_file",
    "send_file",
}


def execute_tool(
    tool_name,
    arguments,
    source="terminal",
    user_id=None,
):
    tool_function = TOOLS.get(
        tool_name
    )

    if tool_function is None:
        raise ValueError(
            f"Unknown tool: {tool_name}"
        )

    arguments = dict(
        arguments or {}
    )

    if tool_name in IDENTITY_TOOLS:
        arguments["_source"] = source
        arguments["_user_id"] = user_id

    try:
        return tool_function(
            **arguments
        )

    except TypeError as error:
        raise ValueError(
            f"Invalid arguments for {tool_name}: {error}"
        ) from error


def execute_pending_action(
    pending_action,
    source,
    user_id,
):
    return execute_pending_file_action(
        pending_action,
        _source=source,
        _user_id=user_id,
    )