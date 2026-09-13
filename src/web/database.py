import hashlib
import secrets
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from config.app_settings import DATA_DIRECTORY, set_web_admin_user_id


DB_PATH = DATA_DIRECTORY / "web.db"
LEGACY_DB_PATH = Path(__file__).resolve().parent / "web.db"

GUEST_EXPIRE_HOURS = 2
PASSWORD_ITERATIONS = 200000


def _migrate_legacy_database():
    if DB_PATH.exists() or not LEGACY_DB_PATH.exists():
        return

    try:
        shutil.copy2(
            LEGACY_DB_PATH,
            DB_PATH,
        )
    except OSError as error:
        raise RuntimeError(
            "Web database migration failed."
        ) from error


def connect():
    return sqlite3.connect(DB_PATH)


def initialize_database():
    _migrate_legacy_database()

    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user'
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS guest_usage (
                guest_id TEXT PRIMARY KEY,
                message_count INTEGER NOT NULL DEFAULT 0,
                last_seen TEXT NOT NULL
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS web_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_web_messages_user
            ON web_messages(user_id, id)
            """
        )

    admin = get_web_admin()

    if admin:
        set_web_admin_user_id(
            admin[0]
        )


def hash_password(password):
    salt = secrets.token_hex(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    ).hex()

    return f"{salt}:{password_hash}"


def verify_password(password, stored_hash):
    try:
        salt, saved_hash = str(
            stored_hash
        ).split(":", 1)
    except ValueError:
        return False

    check_hash = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    ).hex()

    return secrets.compare_digest(
        check_hash,
        saved_hash,
    )


def cleanup_expired_guests():
    expire_time = (
        datetime.now()
        - timedelta(
            hours=GUEST_EXPIRE_HOURS
        )
    ).isoformat()

    with connect() as db:
        db.execute(
            """
            DELETE FROM guest_usage
            WHERE last_seen < ?
            """,
            (expire_time,),
        )


def create_guest():
    cleanup_expired_guests()

    guest_id = str(
        uuid.uuid4()
    )

    with connect() as db:
        db.execute(
            """
            INSERT INTO guest_usage(
                guest_id,
                message_count,
                last_seen
            )
            VALUES (?, 0, ?)
            """,
            (
                guest_id,
                datetime.now().isoformat(),
            ),
        )

    return guest_id


def get_guest_message_count(
    guest_id,
):
    cleanup_expired_guests()

    with connect() as db:
        row = db.execute(
            """
            SELECT message_count
            FROM guest_usage
            WHERE guest_id = ?
            """,
            (guest_id,),
        ).fetchone()

    return (
        None
        if row is None
        else int(row[0])
    )


def increase_guest_message_count(
    guest_id,
):
    with connect() as db:
        db.execute(
            """
            UPDATE guest_usage
            SET
                message_count = message_count + 1,
                last_seen = ?
            WHERE guest_id = ?
            """,
            (
                datetime.now().isoformat(),
                guest_id,
            ),
        )


def get_guest_usage_count():
    cleanup_expired_guests()

    with connect() as db:
        row = db.execute(
            """
            SELECT COUNT(*)
            FROM guest_usage
            """
        ).fetchone()

    return int(row[0])


def clear_guest_usage():
    with connect() as db:
        cursor = db.execute(
            "DELETE FROM guest_usage"
        )

    return cursor.rowcount


def _user_id_exists(
    user_id,
):
    with connect() as db:
        row = db.execute(
            """
            SELECT 1
            FROM users
            WHERE user_id = ?
            """,
            (int(user_id),),
        ).fetchone()

    return row is not None


def _generate_user_id():
    for _ in range(100):
        user_id = secrets.randbelow(
            900000000
        ) + 100000000

        if not _user_id_exists(
            user_id
        ):
            return user_id

    raise RuntimeError(
        "Could not generate a unique Web user ID."
    )


def create_user(
    user_id,
    username,
    password,
    role="user",
):
    username = str(
        username
    ).strip()

    if not username:
        raise ValueError(
            "Username is required."
        )

    with connect() as db:
        try:
            db.execute(
                """
                INSERT INTO users(
                    user_id,
                    username,
                    password_hash,
                    role
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(user_id),
                    username,
                    hash_password(
                        password
                    ),
                    str(role),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                "Username is already in use."
            ) from error

    return int(user_id)


def create_regular_user(
    username,
    password,
):
    return create_user(
        _generate_user_id(),
        username,
        password,
        role="user",
    )


def get_user_by_username(
    username,
):
    with connect() as db:
        return db.execute(
            """
            SELECT
                user_id,
                username,
                password_hash,
                role
            FROM users
            WHERE username = ?
            """,
            (
                str(username).strip(),
            ),
        ).fetchone()


def get_user_by_id(
    user_id,
):
    with connect() as db:
        return db.execute(
            """
            SELECT
                user_id,
                username,
                password_hash,
                role
            FROM users
            WHERE user_id = ?
            """,
            (int(user_id),),
        ).fetchone()


def get_web_admin():
    with connect() as db:
        return db.execute(
            """
            SELECT
                user_id,
                username,
                password_hash,
                role
            FROM users
            WHERE role = 'admin'
            ORDER BY user_id ASC
            LIMIT 1
            """
        ).fetchone()


def save_web_admin_credentials(
    username,
    password="",
):
    username = str(
        username
    ).strip()

    password = str(
        password or ""
    )

    if not username:
        raise ValueError(
            "Admin username is required."
        )

    current_admin = get_web_admin()
    existing_user = get_user_by_username(
        username
    )

    if (
        existing_user
        and (
            current_admin is None
            or int(existing_user[0])
            != int(current_admin[0])
        )
    ):
        raise ValueError(
            "Username is already in use."
        )

    if current_admin is None:
        if not password:
            raise ValueError(
                "Admin password is required."
            )

        user_id = _generate_user_id()

        with connect() as db:
            db.execute(
                """
                INSERT INTO users(
                    user_id,
                    username,
                    password_hash,
                    role
                )
                VALUES (?, ?, ?, 'admin')
                """,
                (
                    user_id,
                    username,
                    hash_password(
                        password
                    ),
                ),
            )

    else:
        user_id = int(
            current_admin[0]
        )

        with connect() as db:
            if password:
                db.execute(
                    """
                    UPDATE users
                    SET
                        username = ?,
                        password_hash = ?,
                        role = 'admin'
                    WHERE user_id = ?
                    """,
                    (
                        username,
                        hash_password(
                            password
                        ),
                        user_id,
                    ),
                )
            else:
                db.execute(
                    """
                    UPDATE users
                    SET
                        username = ?,
                        role = 'admin'
                    WHERE user_id = ?
                    """,
                    (
                        username,
                        user_id,
                    ),
                )

    set_web_admin_user_id(
        user_id
    )

    return get_user_by_id(
        user_id
    )


def save_web_message(
    user_id,
    role,
    content,
):
    if user_id is None:
        return

    with connect() as db:
        db.execute(
            """
            INSERT INTO web_messages(
                user_id,
                role,
                content,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                int(user_id),
                str(role),
                str(content),
                datetime.now().isoformat(),
            ),
        )


def get_user_web_messages(
    user_id,
    limit=None,
):
    params = [
        int(user_id)
    ]

    query = """
        SELECT
            user_id,
            role,
            content
        FROM web_messages
        WHERE user_id = ?
    """

    if limit:
        query += (
            " ORDER BY id DESC"
            " LIMIT ?"
        )

        params.append(
            int(limit)
        )
    else:
        query += " ORDER BY id ASC"

    with connect() as db:
        rows = db.execute(
            query,
            params,
        ).fetchall()

    if limit:
        rows.reverse()

    return rows


def get_all_web_messages(
    limit=None,
):
    params = []

    query = """
        SELECT
            user_id,
            role,
            content
        FROM web_messages
    """

    if limit:
        query += (
            " ORDER BY id DESC"
            " LIMIT ?"
        )

        params.append(
            int(limit)
        )
    else:
        query += " ORDER BY id ASC"

    with connect() as db:
        rows = db.execute(
            query,
            params,
        ).fetchall()

    if limit:
        rows.reverse()

    return rows


def get_user_web_message_count(
    user_id,
):
    with connect() as db:
        row = db.execute(
            """
            SELECT COUNT(*)
            FROM web_messages
            WHERE user_id = ?
            """,
            (int(user_id),),
        ).fetchone()

    return int(row[0])


def get_all_web_message_count():
    with connect() as db:
        row = db.execute(
            """
            SELECT COUNT(*)
            FROM web_messages
            """
        ).fetchone()

    return int(row[0])


def clear_all_web_history():
    with connect() as db:
        cursor = db.execute(
            "DELETE FROM web_messages"
        )

    return cursor.rowcount