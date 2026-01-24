"""
Async Database Service for InfoDigest Bot.
Handles SQLite operations asynchronously using aiosqlite.
"""

import aiosqlite
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from models.schemas import DigestLog, ContentType


class DatabaseError(Exception):
    """Raised when database operations fail."""
    pass


class AsyncDatabaseService:
    """
    Async service for SQLite database operations.
    Handles saving and retrieving digest logs without blocking.
    """

    def __init__(
        self,
        db_path: str = "data/infodigest.db"
    ):
        """
        Initialize async database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._ensure_db_directory()

    def _ensure_db_directory(self) -> None:
        """Ensure the database directory exists."""
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        """Initialize database and create tables."""
        await self._create_tables()

    async def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS digest_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    user_comment TEXT,
                    raw_text_length INTEGER DEFAULT 0,
                    timestamp TEXT NOT NULL,
                    chat_id INTEGER,
                    message_id INTEGER,
                    processing_time_ms INTEGER,
                    error TEXT,
                    UNIQUE(url, timestamp)
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON digest_logs(timestamp DESC)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_url ON digest_logs(url)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_id ON digest_logs(chat_id)
            """)

            await db.commit()

    async def save_log(
        self,
        url: str,
        title: str,
        content_type: str,
        summary: str,
        raw_text_length: int = 0,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
        processing_time_ms: Optional[int] = None,
        error: Optional[str] = None,
        user_comment: Optional[str] = None
    ) -> int:
        """
        Save a digest log entry to the database asynchronously.

        Args:
            url: The processed URL
            title: Content title
            content_type: Type of content ('youtube', 'web', 'pdf')
            summary: Generated summary
            raw_text_length: Length of extracted text
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            processing_time_ms: Processing time in milliseconds
            error: Error message if failed
            user_comment: Optional user comment provided with the URL

        Returns:
            The inserted row ID

        Raises:
            DatabaseError: If save fails
        """
        try:
            content_type_enum = ContentType.from_string(content_type)

            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    INSERT INTO digest_logs (
                        url, title, content_type, summary, user_comment,
                        raw_text_length, timestamp, chat_id, message_id,
                        processing_time_ms, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    url,
                    title,
                    content_type_enum.value,
                    summary,
                    user_comment,
                    raw_text_length,
                    datetime.utcnow().isoformat(),
                    chat_id,
                    message_id,
                    processing_time_ms,
                    error
                ))

                await db.commit()
                return cursor.lastrowid

        except Exception as e:
            raise DatabaseError(f"Failed to save log: {str(e)}")

    async def get_logs(
        self,
        limit: int = 50,
        skip: int = 0,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[DigestLog]:
        """
        Retrieve digest logs from the database asynchronously.

        Args:
            limit: Maximum number of logs to return
            skip: Number of logs to skip (for pagination)
            filters: Optional filter criteria

        Returns:
            List of DigestLog objects

        Raises:
            DatabaseError: If query fails
        """
        try:
            where_clauses = []
            params = []

            if filters:
                for key, value in filters.items():
                    if key == "error" and isinstance(value, dict) and "$ne" in value:
                        where_clauses.append("error IS NOT NULL")
                    elif key == "timestamp" and isinstance(value, dict) and "$gte" in value:
                        where_clauses.append("timestamp >= ?")
                        params.append(value["$gte"].isoformat())
                    else:
                        where_clauses.append(f"{key} = ?")
                        params.append(value)

            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            query = f"""
                SELECT * FROM digest_logs
                {where_sql}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """

            params.extend([limit, skip])

            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(query, params)
                rows = await cursor.fetchall()

            logs = []
            for row in rows:
                try:
                    logs.append(self._row_to_digest_log(dict(row)))
                except Exception:
                    continue

            return logs

        except Exception as e:
            raise DatabaseError(f"Failed to retrieve logs: {str(e)}")

    def _row_to_digest_log(self, data: dict) -> DigestLog:
        """Convert a database row to DigestLog object."""
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])

        if isinstance(data.get("content_type"), str):
            type_mapping = {
                "Video": ContentType.YOUTUBE,
                "Article": ContentType.WEB,
                "Report": ContentType.PDF,
            }
            data["content_type"] = type_mapping.get(
                data["content_type"], ContentType.WEB
            )

        if "id" in data:
            del data["id"]

        return DigestLog(**data)

    async def get_log_by_url(self, url: str) -> Optional[DigestLog]:
        """
        Retrieve a log entry by URL (most recent).

        Args:
            url: The URL to search for

        Returns:
            DigestLog if found, None otherwise
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM digest_logs
                    WHERE url = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (url,))

                row = await cursor.fetchone()
                if row:
                    return self._row_to_digest_log(dict(row))
                return None
        except Exception:
            return None

    async def get_logs_by_chat(
        self,
        chat_id: int,
        limit: int = 50
    ) -> List[DigestLog]:
        """
        Retrieve logs for a specific Telegram chat.

        Args:
            chat_id: Telegram chat ID
            limit: Maximum number of logs

        Returns:
            List of DigestLog objects
        """
        return await self.get_logs(limit=limit, filters={"chat_id": chat_id})

    async def get_stats(self) -> Dict[str, Any]:
        """
        Get summary statistics for the dashboard.

        Returns:
            Dictionary with statistics
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row

                cursor = await db.execute(
                    "SELECT COUNT(*) as total FROM digest_logs"
                )
                row = await cursor.fetchone()
                total = row["total"]

                cursor = await db.execute("""
                    SELECT content_type, COUNT(*) as count
                    FROM digest_logs
                    GROUP BY content_type
                """)
                rows = await cursor.fetchall()
                type_counts = {row["content_type"]: row["count"] for row in rows}

                cursor = await db.execute(
                    "SELECT COUNT(*) as errors FROM digest_logs WHERE error IS NOT NULL"
                )
                row = await cursor.fetchone()
                errors = row["errors"]

            return {
                "total_digests": total,
                "by_type": type_counts,
                "errors": errors,
                "success_rate": ((total - errors) / total * 100) if total > 0 else 100
            }

        except Exception:
            return {
                "total_digests": 0,
                "by_type": {},
                "errors": 0,
                "success_rate": 100
            }

    async def delete_log(self, url: str) -> bool:
        """
        Delete a log entry by URL (most recent).

        Args:
            url: The URL of the log to delete

        Returns:
            True if deleted, False if not found
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    DELETE FROM digest_logs
                    WHERE url = ?
                    AND id = (
                        SELECT id FROM digest_logs
                        WHERE url = ?
                        ORDER BY timestamp DESC
                        LIMIT 1
                    )
                """, (url, url))

                await db.commit()
                return cursor.rowcount > 0
        except Exception:
            return False
