"""
Tests for URL validation and content type detection utilities.
"""

import pytest
from utils.validators import (
    is_youtube_url,
    is_pdf_url,
    is_web_url,
    is_naver_stock_url,
    get_content_type,
    extract_url_from_text,
    extract_youtube_video_id,
    extract_comment_and_url,
    extract_naver_stock_code,
)


class TestIsYoutubeUrl:
    """Tests for is_youtube_url function."""

    def test_standard_youtube_url(self):
        """Test standard YouTube watch URL."""
        assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_youtube_short_url(self):
        """Test YouTube short URL format."""
        assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ") is True

    def test_youtube_shorts_url(self):
        """Test YouTube Shorts URL."""
        assert is_youtube_url("https://www.youtube.com/shorts/abc123def") is True

    def test_youtube_embed_url(self):
        """Test YouTube embed URL."""
        assert is_youtube_url("https://www.youtube.com/embed/dQw4w9WgXcQ") is True

    def test_youtube_without_https(self):
        """Test YouTube URL without https."""
        assert is_youtube_url("http://www.youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_youtube_without_www(self):
        """Test YouTube URL without www."""
        assert is_youtube_url("https://youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_non_youtube_url(self):
        """Test non-YouTube URL returns False."""
        assert is_youtube_url("https://example.com/video") is False

    def test_empty_string(self):
        """Test empty string returns False."""
        assert is_youtube_url("") is False


class TestIsPdfUrl:
    """Tests for is_pdf_url function."""

    def test_pdf_extension(self):
        """Test URL ending with .pdf."""
        assert is_pdf_url("https://example.com/document.pdf") is True

    def test_pdf_in_query(self):
        """Test URL with pdf in query string."""
        assert is_pdf_url("https://example.com/download?file=document.pdf") is True

    def test_uppercase_pdf(self):
        """Test URL with uppercase PDF extension."""
        assert is_pdf_url("https://example.com/document.PDF") is True

    def test_non_pdf_url(self):
        """Test non-PDF URL returns False."""
        assert is_pdf_url("https://example.com/article") is False

    def test_html_url(self):
        """Test HTML URL returns False."""
        assert is_pdf_url("https://example.com/page.html") is False


class TestIsWebUrl:
    """Tests for is_web_url function."""

    def test_https_url(self):
        """Test valid HTTPS URL."""
        assert is_web_url("https://example.com") is True

    def test_http_url(self):
        """Test valid HTTP URL."""
        assert is_web_url("http://example.com") is True

    def test_url_with_path(self):
        """Test URL with path."""
        assert is_web_url("https://example.com/path/to/page") is True

    def test_url_with_query(self):
        """Test URL with query parameters."""
        assert is_web_url("https://example.com/page?id=123") is True

    def test_ftp_url(self):
        """Test FTP URL returns False."""
        assert is_web_url("ftp://example.com/file") is False

    def test_invalid_url(self):
        """Test invalid URL returns False."""
        assert is_web_url("not-a-url") is False

    def test_empty_string(self):
        """Test empty string returns False."""
        assert is_web_url("") is False


class TestGetContentType:
    """Tests for get_content_type function."""

    def test_youtube_content_type(self):
        """Test YouTube URL returns 'youtube'."""
        assert get_content_type("https://www.youtube.com/watch?v=abc123") == "youtube"

    def test_pdf_content_type(self):
        """Test PDF URL returns 'pdf'."""
        assert get_content_type("https://example.com/doc.pdf") == "pdf"

    def test_web_content_type(self):
        """Test regular web URL returns 'web'."""
        assert get_content_type("https://example.com/article") == "web"

    def test_invalid_url_returns_none(self):
        """Test invalid URL returns None."""
        assert get_content_type("not-a-url") is None


class TestExtractUrlFromText:
    """Tests for extract_url_from_text function."""

    def test_url_at_start(self):
        """Test extracting URL at start of text."""
        text = "https://example.com Check this out"
        assert extract_url_from_text(text) == "https://example.com"

    def test_url_at_end(self):
        """Test extracting URL at end of text."""
        text = "Check this out https://example.com"
        assert extract_url_from_text(text) == "https://example.com"

    def test_url_in_middle(self):
        """Test extracting URL in middle of text."""
        text = "Look at https://example.com for more"
        assert extract_url_from_text(text) == "https://example.com"

    def test_url_with_path(self):
        """Test extracting URL with path."""
        text = "Visit https://example.com/path/to/page today"
        assert extract_url_from_text(text) == "https://example.com/path/to/page"

    def test_no_url_returns_none(self):
        """Test text without URL returns None."""
        text = "This is just plain text"
        assert extract_url_from_text(text) is None


class TestExtractYoutubeVideoId:
    """Tests for extract_youtube_video_id function."""

    def test_standard_watch_url(self):
        """Test extracting ID from standard watch URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert extract_youtube_video_id(url) == "dQw4w9WgXcQ"

    def test_short_url(self):
        """Test extracting ID from short URL."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert extract_youtube_video_id(url) == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        """Test extracting ID from Shorts URL."""
        url = "https://www.youtube.com/shorts/abc123def"
        assert extract_youtube_video_id(url) == "abc123def"

    def test_embed_url(self):
        """Test extracting ID from embed URL."""
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        assert extract_youtube_video_id(url) == "dQw4w9WgXcQ"

    def test_non_youtube_url(self):
        """Test non-YouTube URL returns None."""
        url = "https://example.com/video"
        assert extract_youtube_video_id(url) is None


class TestExtractCommentAndUrl:
    """Tests for extract_comment_and_url function."""

    def test_comment_before_url(self):
        """Test extracting comment before URL."""
        text = "This is interesting https://example.com"
        comment, url = extract_comment_and_url(text)
        assert comment == "This is interesting"
        assert url == "https://example.com"

    def test_comment_after_url(self):
        """Test extracting comment after URL."""
        text = "https://example.com Check this article"
        comment, url = extract_comment_and_url(text)
        assert comment == "Check this article"
        assert url == "https://example.com"

    def test_url_only(self):
        """Test URL without comment."""
        text = "https://example.com"
        comment, url = extract_comment_and_url(text)
        assert comment is None
        assert url == "https://example.com"

    def test_no_url(self):
        """Test text without URL."""
        text = "Just some text without a link"
        comment, url = extract_comment_and_url(text)
        assert comment is None
        assert url is None

    def test_comment_with_spaces(self):
        """Test comment with multiple spaces is trimmed."""
        text = "   Great article   https://example.com   "
        comment, url = extract_comment_and_url(text)
        assert comment == "Great article"
        assert url == "https://example.com"


class TestNaverStockHelpers:
    """Tests for stock.naver.com helper functions."""

    def test_is_naver_stock_url_true(self):
        """stock.naver.com URL should be detected."""
        assert is_naver_stock_url("https://stock.naver.com/domestic/005930/total") is True

    def test_is_naver_stock_url_false(self):
        """Non-stock.naver.com URL should return False."""
        assert is_naver_stock_url("https://example.com/domestic/005930/total") is False

    def test_extract_naver_stock_code_from_plain_code(self):
        """Extract code from plain 6-digit input."""
        assert extract_naver_stock_code("005930") == "005930"

    def test_extract_naver_stock_code_from_url_path(self):
        """Extract code from stock.naver.com domestic path."""
        assert extract_naver_stock_code("https://stock.naver.com/domestic/005930/total") == "005930"

    def test_extract_naver_stock_code_from_query(self):
        """Extract code from query string."""
        assert extract_naver_stock_code("https://stock.naver.com/item?code=035420") == "035420"

    def test_extract_naver_stock_code_from_text(self):
        """Extract code embedded in plain text."""
        assert extract_naver_stock_code("check 251270 quickly") == "251270"

    def test_extract_naver_stock_code_invalid(self):
        """Invalid input should return None."""
        assert extract_naver_stock_code("no stock code here") is None
