import shutil
import sqlite3
import threading
from pathlib import Path

from config.app_settings import DATA_DIRECTORY


DB_PATH = DATA_DIRECTORY / "agent_memory.db"
LEGACY_DB_PATH = Path(__file__).resolve().parent / "agent_memory.db"

AGENT_SOURCES = {
    "terminal",
    "telegram",
}


class MemoryManager:
    def __init__(self):
        self.lock = threading.Lock()
        self._migrate_legacy_database()
        self.create_table()

    def _connect(self):
        return sqlite3.connect(DB_PATH)

    def _migrate_legacy_database(self):
        if DB_PATH.exists() or not LEGACY_DB_PATH.exists():
            return

        try:
            shutil.copy2(
                LEGACY_DB_PATH,
                DB_PATH,
            )
        except OSError as error:
            raise RuntimeError(
                "Agent memory database migration failed."
            ) from error

    def create_table(self):
        with self.lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT
                )
                """
            )

            columns = {
                column[1]
                for column in conn.execute(
                    "PRAGMA table_info(messages)"
                ).fetchall()
            }

            if "source" not in columns:
                conn.execute(
                    """
                    ALTER TABLE messages
                    ADD COLUMN source TEXT
                    """
                )

    def save_message(
        self,
        role,
        source,
        content,
    ):
        if source not in AGENT_SOURCES:
            return

        with self.lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages(
                    role,
                    source,
                    content
                )
                VALUES (?, ?, ?)
                """,
                (
                    str(role),
                    source,
                    str(content),
                ),
            )

    def get_recent_messages(
        self,
        source=None,
        limit=None,
    ):
        if (
            source is not None
            and source not in AGENT_SOURCES
        ):
            return []

        query = """
            SELECT
                role,
                source,
                content
            FROM messages
        """

        params = []

        if source:
            query += " WHERE source = ?"
            params.append(source)

        if limit:
            query += " ORDER BY id DESC LIMIT ?"
            params.append(int(limit))
        else:
            query += " ORDER BY id ASC"

        with self.lock, self._connect() as conn:
            rows = conn.execute(
                query,
                params,
            ).fetchall()

        if limit:
            rows.reverse()

        return rows

    def get_message_count(
        self,
        source=None,
    ):
        if (
            source is not None
            and source not in AGENT_SOURCES
        ):
            return 0

        query = """
            SELECT COUNT(*)
            FROM messages
        """

        params = []

        if source:
            query += " WHERE source = ?"
            params.append(source)

        with self.lock, self._connect() as conn:
            row = conn.execute(
                query,
                params,
            ).fetchone()

        return int(row[0])

    def clear_messages(
        self,
        source=None,
    ):
        if (
            source is not None
            and source not in AGENT_SOURCES
        ):
            raise ValueError(
                "Invalid Agent history source."
            )

        query = "DELETE FROM messages"
        params = []

        if source:
            query += " WHERE source = ?"
            params.append(source)

        with self.lock, self._connect() as conn:
            cursor = conn.execute(
                query,
                params,
            )

        return cursor.rowcount