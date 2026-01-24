"""
Tests for data models and schemas.
"""

import pytest
from datetime import datetime
from models.schemas import DigestLog, ContentType


class TestContentType:
    """Tests for ContentType enum."""

    def test_youtube_value(self):
        """Test YouTube content type value."""
        assert ContentType.YOUTUBE.value == "Video"

    def test_web_value(self):
        """Test Web content type value."""
        assert ContentType.WEB.value == "Article"

    def test_pdf_value(self):
        """Test PDF content type value."""
        assert ContentType.PDF.value == "Report"

    def test_from_string_youtube(self):
        """Test from_string for youtube."""
        assert ContentType.from_string("youtube") == ContentType.YOUTUBE
        assert ContentType.from_string("YOUTUBE") == ContentType.YOUTUBE

    def test_from_string_web(self):
        """Test from_string for web."""
        assert ContentType.from_string("web") == ContentType.WEB
        assert ContentType.from_string("WEB") == ContentType.WEB

    def test_from_string_pdf(self):
        """Test from_string for pdf."""
        assert ContentType.from_string("pdf") == ContentType.PDF
        assert ContentType.from_string("PDF") == ContentType.PDF

    def test_from_string_unknown(self):
        """Test from_string with unknown type defaults to WEB."""
        assert ContentType.from_string("unknown") == ContentType.WEB


class TestDigestLog:
    """Tests for DigestLog dataclass."""

    def test_create_minimal_log(self):
        """Test creating log with minimal required fields."""
        log = DigestLog(
            url="https://example.com",
            title="Test",
            content_type=ContentType.WEB,
            summary="Summary"
        )

        assert log.url == "https://example.com"
        assert log.title == "Test"
        assert log.content_type == ContentType.WEB
        assert log.summary == "Summary"
        assert log.user_comment is None
        assert log.error is None

    def test_create_full_log(self):
        """Test creating log with all fields."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0)
        log = DigestLog(
            url="https://example.com/article",
            title="Full Article",
            content_type=ContentType.WEB,
            summary="Full summary",
            user_comment="User's comment",
            timestamp=timestamp,
            raw_text_length=5000,
            chat_id=12345,
            message_id=67890,
            processing_time_ms=1500,
            error=None
        )

        assert log.url == "https://example.com/article"
        assert log.user_comment == "User's comment"
        assert log.timestamp == timestamp
        assert log.raw_text_length == 5000
        assert log.chat_id == 12345
        assert log.message_id == 67890
        assert log.processing_time_ms == 1500

    def test_create_log_with_error(self):
        """Test creating log with error."""
        log = DigestLog(
            url="https://example.com/fail",
            title="Failed Article",
            content_type=ContentType.WEB,
            summary="",
            error="Failed to extract content"
        )

        assert log.error == "Failed to extract content"
        assert log.summary == ""

    def test_to_dict(self):
        """Test converting log to dictionary."""
        log = DigestLog(
            url="https://example.com",
            title="Test",
            content_type=ContentType.YOUTUBE,
            summary="Summary"
        )

        data = log.to_dict()

        assert data["url"] == "https://example.com"
        assert data["title"] == "Test"
        assert data["content_type"] == "Video"  # Enum value
        assert data["summary"] == "Summary"

    def test_from_dict(self):
        """Test creating log from dictionary."""
        data = {
            "url": "https://example.com",
            "title": "From Dict",
            "content_type": "Article",  # String value
            "summary": "Dict summary",
            "timestamp": datetime(2024, 1, 15),
            "raw_text_length": 1000,
        }

        log = DigestLog.from_dict(data)

        assert log.url == "https://example.com"
        assert log.title == "From Dict"
        assert log.content_type == ContentType.WEB
        assert log.summary == "Dict summary"

    def test_from_dict_removes_id(self):
        """Test that from_dict removes id field."""
        data = {
            "id": 123,  # Should be removed
            "url": "https://example.com",
            "title": "Test",
            "content_type": "Article",
            "summary": "Summary",
            "timestamp": datetime.now(),
        }

        log = DigestLog.from_dict(data)
        assert not hasattr(log, "id") or "id" not in log.__dict__

    def test_default_timestamp(self):
        """Test that timestamp defaults to current time."""
        log = DigestLog(
            url="https://example.com",
            title="Test",
            content_type=ContentType.WEB,
            summary="Summary"
        )

        # Should be close to now
        now = datetime.utcnow()
        diff = (now - log.timestamp).total_seconds()
        assert diff < 1  # Less than 1 second difference

    def test_youtube_content_type_from_dict(self):
        """Test creating YouTube log from dict."""
        data = {
            "url": "https://youtube.com/watch?v=abc",
            "title": "Video",
            "content_type": "Video",
            "summary": "Video summary",
            "timestamp": datetime.now(),
        }

        log = DigestLog.from_dict(data)
        assert log.content_type == ContentType.YOUTUBE

    def test_pdf_content_type_from_dict(self):
        """Test creating PDF log from dict."""
        data = {
            "url": "https://example.com/doc.pdf",
            "title": "Document",
            "content_type": "Report",
            "summary": "PDF summary",
            "timestamp": datetime.now(),
        }

        log = DigestLog.from_dict(data)
        assert log.content_type == ContentType.PDF
