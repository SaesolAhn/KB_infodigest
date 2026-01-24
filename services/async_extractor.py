"""
Async content extraction service for InfoDigest Bot.
Handles extraction from YouTube, PDF, and Web sources asynchronously.
"""

import asyncio
import os
import re
import tempfile
from typing import Tuple, Optional
from urllib.parse import urlparse

import httpx
import trafilatura
from pypdf import PdfReader
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from utils.validators import (
    get_content_type,
    extract_youtube_video_id,
    is_web_url,
)


class ExtractionError(Exception):
    """Base exception for extraction errors."""
    pass


class NoTranscriptError(ExtractionError):
    """Raised when YouTube video has no available transcript."""
    pass


class PDFExtractionError(ExtractionError):
    """Raised when PDF text extraction fails."""
    pass


class WebExtractionError(ExtractionError):
    """Raised when web content extraction fails."""
    pass


class AsyncContentExtractor:
    """
    Async extractor for text content from various URL types.

    Supports:
    - YouTube videos (via transcript API)
    - PDF files (via pypdf)
    - Web pages (via trafilatura)
    """

    def __init__(self, timeout: int = 30):
        """
        Initialize the async content extractor.

        Args:
            timeout: HTTP request timeout in seconds
        """
        self.timeout = timeout
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy-loaded async HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36"
                }
            )
        return self._http_client

    async def close(self):
        """Close HTTP client and release resources."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    async def extract(self, url: str) -> Tuple[str, str, str]:
        """
        Extract content from a URL asynchronously.

        Args:
            url: The URL to extract content from

        Returns:
            Tuple of (extracted_text, title, content_type)

        Raises:
            ExtractionError: If extraction fails
            ValueError: If URL is invalid or unsupported
        """
        if not is_web_url(url):
            raise ValueError(f"Invalid URL: {url}")

        content_type = get_content_type(url)

        if content_type == "youtube":
            text, title = await self.extract_youtube(url)
        elif content_type == "pdf":
            text, title = await self.extract_pdf(url)
        elif content_type == "web":
            text, title = await self.extract_web(url)
        else:
            raise ValueError(f"Unsupported content type for URL: {url}")

        return text, title, content_type

    async def extract_youtube(self, url: str) -> Tuple[str, str]:
        """
        Extract transcript from a YouTube video asynchronously.

        Args:
            url: YouTube video URL

        Returns:
            Tuple of (transcript_text, video_title)

        Raises:
            NoTranscriptError: If no transcript is available
            ExtractionError: If extraction fails for other reasons
        """
        video_id = extract_youtube_video_id(url)
        if not video_id:
            raise ExtractionError(f"Could not extract video ID from URL: {url}")

        # Run sync YouTube API call in thread pool
        loop = asyncio.get_event_loop()
        text, title = await loop.run_in_executor(
            None, self._extract_youtube_sync, url, video_id
        )
        return text, title

    def _extract_youtube_sync(self, url: str, video_id: str) -> Tuple[str, str]:
        """Synchronous YouTube extraction (run in thread pool)."""
        try:
            yt_api = YouTubeTranscriptApi()

            try:
                transcript_list = yt_api.list(video_id)
            except VideoUnavailable:
                raise ExtractionError(
                    "Video is unavailable or private. "
                    "Please check if the video exists and is publicly accessible."
                )
            except Exception as e:
                error_msg = str(e).lower()
                if "unavailable" in error_msg or "private" in error_msg:
                    raise ExtractionError(
                        "Video is unavailable or private. "
                        "Please check if the video exists and is publicly accessible."
                    )
                elif "not found" in error_msg:
                    raise ExtractionError(
                        "Video not found. Please check if the URL is correct."
                    )
                else:
                    raise ExtractionError(f"Failed to access YouTube video: {str(e)}")

            transcript = None
            try:
                transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
            except NoTranscriptFound:
                try:
                    transcript = transcript_list.find_generated_transcript(
                        ['en', 'en-US', 'en-GB']
                    )
                except NoTranscriptFound:
                    available = list(transcript_list)
                    if available:
                        transcript = available[0]
                        if transcript.is_translatable:
                            try:
                                transcript = transcript.translate('en')
                            except Exception:
                                pass

            if transcript is None:
                raise NoTranscriptError("No transcript available for this video.")

            transcript_data = transcript.fetch()
            text_parts = [snippet.text for snippet in transcript_data]
            full_text = ' '.join(text_parts)
            full_text = self._clean_text(full_text)

            # Get title (sync HTTP call, will be run in executor)
            title = f"YouTube Video ({video_id})"

            return full_text, title

        except (NoTranscriptFound, TranscriptsDisabled):
            raise NoTranscriptError("No transcript available for this video.")
        except VideoUnavailable:
            raise ExtractionError("Video is unavailable or private.")
        except (NoTranscriptError, ExtractionError):
            raise
        except Exception as e:
            raise ExtractionError(f"Failed to extract YouTube transcript: {str(e)}")

    async def _get_youtube_title(self, url: str, video_id: str) -> str:
        """Attempt to get YouTube video title asynchronously."""
        try:
            response = await self.http_client.get(url)
            html = response.text

            title_match = re.search(r'<title>(.+?)</title>', html)
            if title_match:
                title = title_match.group(1)
                title = re.sub(r'\s*-\s*YouTube\s*$', '', title)
                return title.strip()
        except Exception:
            pass

        return f"YouTube Video ({video_id})"

    async def extract_pdf(self, url: str) -> Tuple[str, str]:
        """
        Extract text from a PDF file asynchronously.

        Args:
            url: URL to the PDF file

        Returns:
            Tuple of (extracted_text, title)

        Raises:
            PDFExtractionError: If PDF cannot be read or has no extractable text
        """
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()

            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                tmp_file.write(response.content)
                tmp_path = tmp_file.name

            try:
                # Run sync PDF extraction in thread pool
                loop = asyncio.get_event_loop()
                text, title = await loop.run_in_executor(
                    None, self._extract_pdf_sync, tmp_path, url
                )
                return text, title
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        except PDFExtractionError:
            raise
        except httpx.HTTPStatusError as e:
            raise ExtractionError(
                f"Failed to download PDF: HTTP {e.response.status_code}"
            )
        except Exception as e:
            raise ExtractionError(f"Failed to extract PDF content: {str(e)}")

    def _extract_pdf_sync(self, file_path: str, source: str) -> Tuple[str, str]:
        """Synchronous PDF extraction (run in thread pool)."""
        try:
            reader = PdfReader(file_path)

            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

            if not text_parts:
                raise PDFExtractionError(
                    "Could not extract text (OCR not supported in MVP)."
                )

            full_text = '\n\n'.join(text_parts)
            full_text = self._clean_text(full_text)

            if len(full_text.strip()) < 100:
                raise PDFExtractionError(
                    "Could not extract text (OCR not supported in MVP)."
                )

            title = self._get_pdf_title(reader, source)
            return full_text, title

        except PDFExtractionError:
            raise
        except Exception as e:
            raise PDFExtractionError(f"Failed to read PDF: {str(e)}")

    def _get_pdf_title(self, reader: PdfReader, source: str) -> str:
        """Extract title from PDF metadata or generate from source."""
        if reader.metadata:
            title = reader.metadata.get('/Title')
            if title and isinstance(title, str) and title.strip():
                return title.strip()

        parsed = urlparse(source)
        filename = os.path.basename(parsed.path)
        if filename:
            title = os.path.splitext(filename)[0]
            title = title.replace('_', ' ').replace('-', ' ')
            return title.title()

        return "PDF Document"

    async def extract_web(self, url: str) -> Tuple[str, str]:
        """
        Extract main content from a web page asynchronously.

        Args:
            url: Web page URL

        Returns:
            Tuple of (extracted_text, page_title)

        Raises:
            WebExtractionError: If content cannot be extracted
        """
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()
            html = response.text

            # Run trafilatura in thread pool (it's CPU-bound)
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None, self._extract_web_content, html
            )

            if not text or len(text.strip()) < 100:
                raise WebExtractionError(
                    "Could not extract meaningful content from this page."
                )

            text = self._clean_text(text)
            title = self._get_web_title(html, url)

            return text, title

        except WebExtractionError:
            raise
        except httpx.HTTPStatusError as e:
            raise WebExtractionError(
                f"Failed to fetch page: HTTP {e.response.status_code}"
            )
        except Exception as e:
            raise WebExtractionError(f"Failed to extract web content: {str(e)}")

    def _extract_web_content(self, html: str) -> Optional[str]:
        """Extract content using trafilatura (sync, run in executor)."""
        return trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_precision=True,
        )

    def _get_web_title(self, html: str, url: str) -> str:
        """Extract title from web page HTML."""
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
            title = re.sub(r'\s*[|\-–—]\s*[^|\-–—]+$', '', title)
            if title:
                return title

        og_match = re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        )
        if og_match:
            return og_match.group(1).strip()

        parsed = urlparse(url)
        return parsed.netloc or "Web Article"

    def _clean_text(self, text: str) -> str:
        """Clean up extracted text."""
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()
        return text
