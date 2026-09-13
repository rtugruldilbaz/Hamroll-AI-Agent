import os
from pathlib import Path

from config.app_settings import (
    DATA_DIRECTORY,
    get_local_access_mode,
    get_local_allowed_paths,
    get_web_admin_user_id,
    is_custom_access_acknowledged,
    load_secrets,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOME = Path.home().resolve()

NORMAL_ALLOWED_ROOTS = [
    HOME / "Desktop",
    HOME / "Documents",
    HOME / "Downloads",
]

BLOCKED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
}

BLOCKED_FILE_NAMES = {
    ".env",
    "config.json",
    "secrets.json",
    "internal.json",
    "telegram_chat_id.txt",
}

BLOCKED_EXTENSIONS = {
    ".db",
    ".sqlite",
    ".sqlite3",
}

PROTECTED_FILES = {
    PROJECT_ROOT / "src" / "security" / "permissions.py",
    PROJECT_ROOT / "src" / "agent" / "agent.py",
    PROJECT_ROOT / "src" / "telegram_bot" / "bot.py",
    PROJECT_ROOT / "src" / "config" / "app_settings.py",
}

BLOCKED_DIRECTORY_NAMES_LOWER = {
    name.lower()
    for name in BLOCKED_DIRECTORY_NAMES
}

BLOCKED_FILE_NAMES_LOWER = {
    name.lower()
    for name in BLOCKED_FILE_NAMES
}


def normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_inside(path: Path, root: Path) -> bool:
    path = path.resolve()
    root = root.resolve()
    return path == root or root in path.parents


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(str(first.resolve())) == os.path.normcase(
        str(second.resolve())
    )


def _is_normal_allowed_path(path: Path) -> bool:
    return any(
        _is_inside(path, root)
        for root in NORMAL_ALLOWED_ROOTS
    )


def _telegram_admin_id():
    try:
        value = load_secrets().get("telegram_user_id")
    except Exception:
        return None

    value = str(value or "").strip()
    return value or None


def is_admin(
    source: str,
    user_id: int | str | None,
) -> bool:
    if source == "terminal":
        return True

    if user_id is None:
        return False

    if source == "web":
        try:
            admin_id = get_web_admin_user_id()
        except Exception:
            return False

        return (
            admin_id is not None
            and str(user_id) == str(admin_id)
        )

    if source == "telegram":
        admin_id = _telegram_admin_id()

        return (
            admin_id is not None
            and str(user_id) == admin_id
        )

    return False


def is_project_path(path: str | Path) -> bool:
    return _is_inside(
        normalize_path(path),
        PROJECT_ROOT,
    )


def _windows_directory():
    value = (
        os.environ.get("SystemRoot")
        or os.environ.get("WINDIR")
    )

    if not value:
        return None

    try:
        return normalize_path(value)
    except Exception:
        return None


def _program_data_directory():
    value = os.environ.get("ProgramData")

    if not value:
        return None

    try:
        return normalize_path(value)
    except Exception:
        return None


def _program_files_directories():
    directories = []

    for key in (
        "ProgramFiles",
        "ProgramFiles(x86)",
        "ProgramW6432",
    ):
        value = os.environ.get(key)

        if not value:
            continue

        try:
            path = normalize_path(value)
        except Exception:
            continue

        if not any(
            _same_path(path, current)
            for current in directories
        ):
            directories.append(path)

    return directories


def is_critical_system_path(
    path: str | Path,
) -> bool:
    path = normalize_path(path)

    windows_directory = _windows_directory()

    if (
        windows_directory
        and _is_inside(path, windows_directory)
    ):
        return True

    program_data = _program_data_directory()

    if (
        program_data
        and _is_inside(path, program_data)
    ):
        return True

    return False


def is_sensitive_path(
    path: str | Path,
) -> bool:
    path = normalize_path(path)
    data_directory = normalize_path(DATA_DIRECTORY)

    if _is_inside(path, data_directory):
        return True

    if any(
        _same_path(path, protected)
        for protected in PROTECTED_FILES
    ):
        return True

    if any(
        part.lower() in BLOCKED_DIRECTORY_NAMES_LOWER
        for part in path.parts
    ):
        return True

    if path.name.lower() in BLOCKED_FILE_NAMES_LOWER:
        return True

    return path.suffix.lower() in BLOCKED_EXTENSIONS


def validate_custom_access_root(
    path: str | Path,
) -> Path:
    path = normalize_path(path)

    if not path.exists():
        raise ValueError(
            "The selected folder does not exist."
        )

    if not path.is_dir():
        raise ValueError(
            "The selected path is not a folder."
        )

    if path.parent == path:
        raise PermissionError(
            "Drive roots cannot be authorized."
        )

    if (
        _same_path(path, HOME)
        or _is_inside(HOME, path)
    ):
        raise PermissionError(
            "The user profile or one of its parent folders cannot be authorized."
        )

    if (
        _is_inside(path, PROJECT_ROOT)
        or _is_inside(PROJECT_ROOT, path)
    ):
        raise PermissionError(
            "The AI Agent project directory cannot be authorized."
        )

    data_directory = normalize_path(DATA_DIRECTORY)

    if (
        _is_inside(path, data_directory)
        or _is_inside(data_directory, path)
    ):
        raise PermissionError(
            "The AI Agent data directory cannot be authorized."
        )

    if is_sensitive_path(path):
        raise PermissionError(
            "The selected folder is protected."
        )

    if is_critical_system_path(path):
        raise PermissionError(
            "Critical Windows system locations cannot be authorized."
        )

    if any(
        _same_path(path, program_files)
        for program_files in _program_files_directories()
    ):
        raise PermissionError(
            "Authorize a specific application folder instead of the entire Program Files directory."
        )

    return path


def _custom_local_roots():
    if get_local_access_mode() != "custom":
        return []

    if not is_custom_access_acknowledged():
        return []

    roots = []

    for value in get_local_allowed_paths():
        try:
            root = validate_custom_access_root(value)
        except (
            OSError,
            ValueError,
            PermissionError,
        ):
            continue

        if not any(
            _same_path(root, existing)
            for existing in roots
        ):
            roots.append(root)

    return roots


def _is_local_custom_allowed(
    path: Path,
    source: str,
) -> bool:
    if source != "terminal":
        return False

    return any(
        _is_inside(path, root)
        for root in _custom_local_roots()
    )


def _is_allowed_data_path(
    path: Path,
    source: str,
) -> bool:
    return (
        _is_normal_allowed_path(path)
        or _is_local_custom_allowed(path, source)
    )


def validate_identity(
    source: str,
    user_id: int | str | None,
) -> None:
    if source == "terminal":
        return

    if source == "web":
        if user_id is None:
            raise PermissionError(
                "Authentication is required for local file access."
            )

        if not is_admin(source, user_id):
            raise PermissionError(
                "This Web account does not have local file access."
            )

        return

    if source == "telegram":
        if not is_admin(source, user_id):
            raise PermissionError(
                "This Telegram user does not have local file access."
            )

        return

    raise PermissionError(
        "Local file access is not allowed from this source."
    )


def validate_read(
    path: str | Path,
    source: str,
    user_id: int | str | None,
) -> Path:
    validate_identity(source, user_id)
    path = normalize_path(path)

    if is_sensitive_path(path):
        raise PermissionError(
            "Access to this file or folder is blocked."
        )

    if is_critical_system_path(path):
        raise PermissionError(
            "Access to this system location is blocked."
        )

    if is_project_path(path):
        if source != "terminal":
            raise PermissionError(
                "Project file access is available only from Local Admin."
            )

        return path

    if _is_allowed_data_path(path, source):
        return path

    raise PermissionError(
        "Read access is not allowed for this location."
    )


def validate_write(
    path: str | Path,
    source: str,
    user_id: int | str | None,
) -> Path:
    validate_identity(source, user_id)
    path = normalize_path(path)

    if is_sensitive_path(path):
        raise PermissionError(
            "Writing to this file or folder is blocked."
        )

    if is_critical_system_path(path):
        raise PermissionError(
            "Writing to this system location is blocked."
        )

    if is_project_path(path):
        raise PermissionError(
            "Writing to project files through the Agent is blocked."
        )

    if _is_allowed_data_path(path, source):
        return path

    raise PermissionError(
        "Write access is not allowed for this location."
    )


def validate_delete(
    path: str | Path,
    source: str,
    user_id: int | str | None,
) -> Path:
    validate_identity(source, user_id)
    path = normalize_path(path)

    if is_sensitive_path(path):
        raise PermissionError(
            "This file or folder cannot be deleted."
        )

    if is_critical_system_path(path):
        raise PermissionError(
            "Items in this system location cannot be deleted."
        )

    if is_project_path(path):
        raise PermissionError(
            "Project files cannot be deleted through the Agent."
        )

    if _is_allowed_data_path(path, source):
        return path

    raise PermissionError(
        "Delete access is not allowed for this location."
    )


def validate_existing_file_for_read(
    path: str | Path,
    source: str,
    user_id: int | str | None,
) -> Path:
    path = validate_read(
        path,
        source,
        user_id,
    )

    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {path}"
        )

    if not path.is_file():
        raise ValueError(
            "The provided path is not a file."
        )

    return path


def validate_existing_file_for_delete(
    path: str | Path,
    source: str,
    user_id: int | str | None,
) -> Path:
    path = validate_delete(
        path,
        source,
        user_id,
    )

    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {path}"
        )

    if not path.is_file():
        raise ValueError(
            "The provided path is not a file."
        )

    return path


def validate_existing_directory_for_read(
    path: str | Path,
    source: str,
    user_id: int | str | None,
) -> Path:
    path = validate_read(
        path,
        source,
        user_id,
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Directory not found: {path}"
        )

    if not path.is_dir():
        raise ValueError(
            "The provided path is not a directory."
        )

    return path