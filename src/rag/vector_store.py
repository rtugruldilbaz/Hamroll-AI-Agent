import json
import shutil
import sqlite3
from pathlib import Path

from config.app_settings import DATA_DIRECTORY


DATABASE_PATH = DATA_DIRECTORY / "rag_vectors.db"
LEGACY_DATABASE_PATH = (
    Path(__file__).resolve().parents[1]
    / "memory"
    / "rag_vectors.db"
)


class VectorStore:
    def __init__(self, database_path=DATABASE_PATH):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        if (
            self.database_path == DATABASE_PATH
            and not DATABASE_PATH.exists()
            and LEGACY_DATABASE_PATH.exists()
        ):
            try:
                shutil.copy2(
                    LEGACY_DATABASE_PATH,
                    DATABASE_PATH,
                )
            except OSError as error:
                raise RuntimeError(
                    "RAG database migration failed."
                ) from error

        self._create_table()
        self._migrate_table()

    def _connect(self):
        return sqlite3.connect(
            self.database_path
        )

    def _create_table(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT ''
                )
                """
            )

    def _migrate_table(self):
        with self._connect() as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(chunks)"
                ).fetchall()
            }

            if "source" not in columns:
                connection.execute(
                    """
                    ALTER TABLE chunks
                    ADD COLUMN source TEXT NOT NULL DEFAULT ''
                    """
                )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_source
                ON chunks(source)
                """
            )

    def add(
        self,
        text: str,
        embedding: list[float],
        source: str = "",
    ):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO chunks (
                    text,
                    embedding,
                    source
                )
                VALUES (?, ?, ?)
                """,
                (
                    text,
                    json.dumps(embedding),
                    source,
                ),
            )

    def replace_source(
        self,
        source: str,
        chunks: list[
            tuple[
                str,
                list[float],
            ]
        ],
    ):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM chunks WHERE source = ?",
                (source,),
            )

            connection.executemany(
                """
                INSERT INTO chunks (
                    text,
                    embedding,
                    source
                )
                VALUES (?, ?, ?)
                """,
                [
                    (
                        text,
                        json.dumps(embedding),
                        source,
                    )
                    for text, embedding in chunks
                ],
            )

    def delete_source(
        self,
        source: str,
    ):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM chunks WHERE source = ?",
                (source,),
            )

    def get_all(
        self,
        source: str | None = None,
    ) -> list[dict]:
        with self._connect() as connection:
            if source:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        text,
                        embedding,
                        source
                    FROM chunks
                    WHERE source = ?
                    """,
                    (source,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        text,
                        embedding,
                        source
                    FROM chunks
                    """
                ).fetchall()

        return [
            {
                "id": row[0],
                "text": row[1],
                "embedding": json.loads(
                    row[2]
                ),
                "source": row[3],
            }
            for row in rows
        ]