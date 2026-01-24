"""
Tests for database services (sync and async).
"""

import pytest
import asyncio
from datetime import datetime, timedelta

from services.database import DatabaseService, DatabaseError
from services.async_database import AsyncDatabaseService
from models.schemas import ContentType


class TestDatabaseService:
    """Tests for synchronous DatabaseService."""

    def test_connection(self, temp_db_path):
        """Test database connection."""
        db = DatabaseService(db_path=temp_db_path)
        conn = db.connect()
        assert conn is not None
        db.close()

    def test_save_and_retrieve_log(self, temp_db_path):
        """Test saving and retrieving a log entry."""
        db = DatabaseService(db_path=temp_db_path)
        db.connect()

        # Save a log
        log_id = db.save_log(
            url="https://example.com/article",
            title="Test Article",
            content_type="web",
            summary="This is a test summary.",
            raw_text_length=1000,
            chat_id=12345,
            processing_time_ms=500,
        )

        assert log_id is not None
        assert log_id > 0

        # Retrieve logs
        logs = db.get_logs(limit=10)
        assert len(logs) == 1
        assert logs[0].url == "https://example.com/article"
        assert logs[0].title == "Test Article"
        assert logs[0].content_type == ContentType.WEB

        db.close()

    def test_save_youtube_log(self, temp_db_path):
        """Test saving a YouTube log entry."""
        db = DatabaseService(db_path=temp_db_path)
        db.connect()

        log_id = db.save_log(
            url="https://youtube.com/watch?v=abc123",
            title="Test Video",
            content_type="youtube",
            summary="Video summary",
            raw_text_length=5000,
        )

        logs = db.get_logs()
        assert logs[0].content_type == ContentType.YOUTUBE
        assert logs[0].content_type.value == "Video"

        db.close()

    def test_save_pdf_log(self, temp_db_path):
        """Test saving a PDF log entry."""
        db = DatabaseService(db_path=temp_db_path)
        db.connect()

        log_id = db.save_log(
            url="https://example.com/doc.pdf",
            title="Test Document",
            content_type="pdf",
            summary="PDF summary",
            raw_text_length=10000,
        )

        logs = db.get_logs()
        assert logs[0].content_type == ContentType.PDF
        assert logs[0].content_type.value == "Report"

        db.close()

    def test_save_log_with_error(self, temp_db_path):
        """Test saving a log entry with error."""
        db = DatabaseService(db_path=temp_db_path)
        db.connect()

        log_id = db.save_log(
            url="https://example.com/broken",
            title="Failed Article",
            content_type="web",
            summary="",
            error="Failed to extract content",
        )

        logs = db.get_logs()
        assert logs[0].error == "Failed to extract content"

        db.close()

    def test_save_log_with_user_comment(self, temp_db_path):
        """Test saving a log entry with user comment."""
        db = DatabaseService(db_path=temp_db_path)
        db.connect()

        log_id = db.save_log(
            url="https://example.com/article",
            title="Test Article",
            content_type="web",
            summary="Summary here",
            user_comment="This is my comment",
        )

        logs = db.get_logs()
        assert logs[0].user_comment == "This is my comment"

        db.close()

    def test_get_log_by_url(self, temp_db_path):
        """Test retrieving log by URL."""
        db = DatabaseService(db_path=temp_db_path)
        db.connect()

        url = "https://example.com/specific-article"
        db.save_log(
            url=url,
            title="Specific Article",
            content_type="web",
            summary="Specific summary",
        )

        log = db.get_log_by_url(url)
        assert log is not None
        assert log.title == "Specific Article"

        db.close()

    def test_get_logs_with_pagination(self, temp_db_path):
        """Test pagination of logs."""
        db = DatabaseService(db_path=temp_db_path)
        db.connect()

        # Create multiple logs
        for i in range(10):
            db.save_log(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                content_type="web",
                summary=f"Summary {i}",
            )

        # Get first page
        page1 = db.get_logs(limit=5, skip=0)
        assert len(page1) == 5

        # Get second page
        page2 = db.get_logs(limit=5, skip=5)
        assert len(page2) == 5

        # Pages should have different entries
        assert page1[0].title != page2[0].title

        db.close()

    def test_get_logs_with_content_type_filter(self, temp_db_path):
        """Test filtering logs by content type."""
        db = DatabaseService(db_path=temp_db_path)
        db.connect()

        # Create different content types
        db.save_log(url="https://youtube.com/v1", title="Video 1",
                    content_type="youtube", summary="V1")
        db.save_log(url="https://example.com/a1", title="Article 1",
                    content_type="web", summary="A1")
        db.save_log(url="https://example.com/d1.pdf", title="Doc 1",
                    content_type="pdf", summary="D1")

        # Filter by content type
        videos = db.get_logs(filters={"content_type": "Video"})
        assert len(videos) == 1
        assert videos[0].content_type == ContentType.YOUTUBE

        db.close()

    def test_get_stats(self, temp_db_path):
        """Test getting statistics."""
        db = DatabaseService(db_path=temp_db_path)
        db.connect()

        # Create logs with different types and errors
        db.save_log(url="https://youtube.com/v1", title="Video 1",
                    content_type="youtube", summary="V1")
        db.save_log(url="https://example.com/a1", title="Article 1",
                    content_type="web", summary="A1")
        db.save_log(url="https://example.com/fail", title="Failed",
                    content_type="web", summary="", error="Error")

        stats = db.get_stats()

        assert stats["total_digests"] == 3
        assert stats["errors"] == 1
        assert stats["success_rate"] == pytest.approx(66.67, 0.1)
        assert "Video" in stats["by_type"]
        assert "Article" in stats["by_type"]

        db.close()

    def test_delete_log(self, temp_db_path):
        """Test deleting a log entry."""
        db = DatabaseService(db_path=temp_db_path)
        db.connect()

        url = "https://example.com/to-delete"
        db.save_log(url=url, title="To Delete", content_type="web", summary="Delete me")

        # Verify it exists
        assert db.get_log_by_url(url) is not None

        # Delete it
        result = db.delete_log(url)
        assert result is True

        # Verify it's gone
        assert db.get_log_by_url(url) is None

        db.close()

    def test_context_manager(self, temp_db_path):
        """Test database as context manager."""
        with DatabaseService(db_path=temp_db_path) as db:
            log_id = db.save_log(
                url="https://example.com/ctx",
                title="Context Test",
                content_type="web",
                summary="Using context manager",
            )
            assert log_id is not None


@pytest.mark.asyncio
class TestAsyncDatabaseService:
    """Tests for asynchronous AsyncDatabaseService."""

    async def test_async_save_and_retrieve(self, temp_db_path):
        """Test async save and retrieve."""
        db = AsyncDatabaseService(db_path=temp_db_path)
        await db.init()

        log_id = await db.save_log(
            url="https://example.com/async-article",
            title="Async Article",
            content_type="web",
            summary="Async summary",
            raw_text_length=2000,
        )

        assert log_id is not None

        logs = await db.get_logs(limit=10)
        assert len(logs) == 1
        assert logs[0].url == "https://example.com/async-article"

    async def test_async_get_log_by_url(self, temp_db_path):
        """Test async get log by URL."""
        db = AsyncDatabaseService(db_path=temp_db_path)
        await db.init()

        url = "https://example.com/async-specific"
        await db.save_log(
            url=url,
            title="Async Specific",
            content_type="web",
            summary="Specific async",
        )

        log = await db.get_log_by_url(url)
        assert log is not None
        assert log.title == "Async Specific"

    async def test_async_get_stats(self, temp_db_path):
        """Test async statistics."""
        db = AsyncDatabaseService(db_path=temp_db_path)
        await db.init()

        await db.save_log(url="https://example.com/1", title="Article 1",
                          content_type="web", summary="S1")
        await db.save_log(url="https://example.com/2", title="Article 2",
                          content_type="web", summary="S2")

        stats = await db.get_stats()
        assert stats["total_digests"] == 2
        assert stats["errors"] == 0

    async def test_async_delete_log(self, temp_db_path):
        """Test async delete."""
        db = AsyncDatabaseService(db_path=temp_db_path)
        await db.init()

        url = "https://example.com/async-delete"
        await db.save_log(url=url, title="To Delete", content_type="web", summary="D")

        result = await db.delete_log(url)
        assert result is True

        log = await db.get_log_by_url(url)
        assert log is None
