"""
Content extraction service for InfoDigest Bot.
Handles extraction from YouTube, PDF, and Web sources.
"""

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


class ContentExtractor:
    """
    Extracts text content from various URL types.
    
    Supports:
    - YouTube videos (via transcript API)
    - PDF files (via pypdf)
    - Web pages (via trafilatura)
    """
    
    def __init__(self, timeout: int = 30):
        """
        Initialize the content extractor.
        
        Args:
            timeout: HTTP request timeout in seconds
        """
        self.timeout = timeout
        self._http_client = None
    
    @property
    def http_client(self) -> httpx.Client:
        """Lazy-loaded HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36"
                }
            )
        return self._http_client
    
    def close(self):
        """Close HTTP client and release resources."""
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
    
    def extract(self, url: str) -> Tuple[str, str, str]:
        """
        Extract content from a URL.
        
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
            text, title = self.extract_youtube(url)
        elif content_type == "pdf":
            text, title = self.extract_pdf(url)
        elif content_type == "web":
            text, title = self.extract_web(url)
        else:
            raise ValueError(f"Unsupported content type for URL: {url}")
        
        return text, title, content_type
    
    def extract_youtube(self, url: str) -> Tuple[str, str]:
        """
        Extract transcript from a YouTube video.
        
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
        
        try:
            # Create API instance
            yt_api = YouTubeTranscriptApi()
            
            # Try to get transcript, preferring English
            try:
                transcript_list = yt_api.list(video_id)
            except VideoUnavailable:
                raise ExtractionError("Video is unavailable or private. Please check if the video exists and is publicly accessible.")
            except Exception as e:
                # Catch any other errors from list
                error_msg = str(e).lower()
                if "unavailable" in error_msg or "private" in error_msg:
                    raise ExtractionError("Video is unavailable or private. Please check if the video exists and is publicly accessible.")
                elif "not found" in error_msg:
                    raise ExtractionError("Video not found. Please check if the URL is correct.")
                else:
                    raise ExtractionError(f"Failed to access YouTube video: {str(e)}")
            
            # Try to find an English transcript first
            transcript = None
            try:
                transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
            except NoTranscriptFound:
                # Fall back to any available transcript and translate to English
                try:
                    transcript = transcript_list.find_generated_transcript(['en', 'en-US', 'en-GB'])
                except NoTranscriptFound:
                    # Get any available transcript
                    available = list(transcript_list)
                    if available:
                        transcript = available[0]
                        # Try to translate to English if possible
                        if transcript.is_translatable:
                            try:
                                transcript = transcript.translate('en')
                            except Exception:
                                pass  # Use original if translation fails
            
            if transcript is None:
                raise NoTranscriptError("No transcript available for this video.")
            
            # Fetch the actual transcript data
            transcript_data = transcript.fetch()
            
            # Combine transcript segments into full text
            # transcript_data is a FetchedTranscript object containing FetchedTranscriptSnippet objects
            text_parts = [snippet.text for snippet in transcript_data]
            full_text = ' '.join(text_parts)
            
            # Clean up the text
            full_text = self._clean_text(full_text)
            
            # Try to get the video title from the page
            title = self._get_youtube_title(url, video_id)
            
            return full_text, title
            
        except (NoTranscriptFound, TranscriptsDisabled):
            raise NoTranscriptError("No transcript available for this video.")
        except VideoUnavailable:
            raise ExtractionError("Video is unavailable or private.")
        except NoTranscriptError:
            raise  # Re-raise our custom error
        except Exception as e:
            raise ExtractionError(f"Failed to extract YouTube transcript: {str(e)}")
    
    def _get_youtube_title(self, url: str, video_id: str) -> str:
        """
        Attempt to get YouTube video title.
        
        Args:
            url: YouTube video URL
            video_id: YouTube video ID
            
        Returns:
            Video title or fallback title
        """
        try:
            response = self.http_client.get(url)
            html = response.text
            
            # Try to extract title from HTML
            title_match = re.search(r'<title>(.+?)</title>', html)
            if title_match:
                title = title_match.group(1)
                # Clean up YouTube suffix
                title = re.sub(r'\s*-\s*YouTube\s*$', '', title)
                return title.strip()
        except Exception:
            pass
        
        return f"YouTube Video ({video_id})"
    
    def extract_pdf(self, url: str) -> Tuple[str, str]:
        """
        Extract text from a PDF file.
        
        Args:
            url: URL to the PDF file
            
        Returns:
            Tuple of (extracted_text, title)
            
        Raises:
            PDFExtractionError: If PDF cannot be read or has no extractable text
        """
        try:
            # Download PDF to temporary file
            response = self.http_client.get(url)
            response.raise_for_status()
            
            # Create temp file with PDF content
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                tmp_file.write(response.content)
                tmp_path = tmp_file.name
            
            try:
                # Extract text from PDF
                text, title = self._extract_pdf_text(tmp_path, url)
                return text, title
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                    
        except PDFExtractionError:
            raise  # Re-raise our custom error
        except httpx.HTTPStatusError as e:
            raise ExtractionError(f"Failed to download PDF: HTTP {e.response.status_code}")
        except Exception as e:
            raise ExtractionError(f"Failed to extract PDF content: {str(e)}")
    
    def extract_pdf_from_file(self, file_path: str) -> Tuple[str, str]:
        """
        Extract text from a local PDF file.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Tuple of (extracted_text, title)
            
        Raises:
            PDFExtractionError: If PDF cannot be read or has no extractable text
        """
        return self._extract_pdf_text(file_path, file_path)
    
    def _extract_pdf_text(self, file_path: str, source: str) -> Tuple[str, str]:
        """
        Internal method to extract text from a PDF file.
        
        Args:
            file_path: Path to the PDF file
            source: Original source (URL or file path) for title generation
            
        Returns:
            Tuple of (extracted_text, title)
        """
        try:
            reader = PdfReader(file_path)
            
            # Extract text from all pages
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
            
            # Try to get title from PDF metadata
            title = self._get_pdf_title(reader, source)
            
            return full_text, title
            
        except PDFExtractionError:
            raise
        except Exception as e:
            raise PDFExtractionError(f"Failed to read PDF: {str(e)}")
    
    def _get_pdf_title(self, reader: PdfReader, source: str) -> str:
        """
        Extract title from PDF metadata or generate from source.
        
        Args:
            reader: PDF reader instance
            source: Original source URL or file path
            
        Returns:
            Document title
        """
        # Try PDF metadata
        if reader.metadata:
            title = reader.metadata.get('/Title')
            if title and isinstance(title, str) and title.strip():
                return title.strip()
        
        # Generate from filename/URL
        parsed = urlparse(source)
        filename = os.path.basename(parsed.path)
        if filename:
            # Remove extension and clean up
            title = os.path.splitext(filename)[0]
            title = title.replace('_', ' ').replace('-', ' ')
            return title.title()
        
        return "PDF Document"
    
    def extract_web(self, url: str) -> Tuple[str, str]:
        """
        Extract main content from a web page.
        
        Args:
            url: Web page URL
            
        Returns:
            Tuple of (extracted_text, page_title)
            
        Raises:
            WebExtractionError: If content cannot be extracted
        """
        try:
            # Fetch the page
            response = self.http_client.get(url)
            response.raise_for_status()
            html = response.text
            
            # Extract main content using trafilatura
            text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
                favor_precision=True,
            )
            
            if not text or len(text.strip()) < 100:
                raise WebExtractionError(
                    "Could not extract meaningful content from this page."
                )
            
            text = self._clean_text(text)
            
            # Extract title
            title = self._get_web_title(html, url)
            
            return text, title
            
        except WebExtractionError:
            raise
        except httpx.HTTPStatusError as e:
            raise WebExtractionError(f"Failed to fetch page: HTTP {e.response.status_code}")
        except Exception as e:
            raise WebExtractionError(f"Failed to extract web content: {str(e)}")
    
    def _get_web_title(self, html: str, url: str) -> str:
        """
        Extract title from web page HTML.
        
        Args:
            html: Page HTML content
            url: Page URL (fallback)
            
        Returns:
            Page title
        """
        # Try to extract from title tag
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
            # Clean up common suffixes
            title = re.sub(r'\s*[|\-–—]\s*[^|\-–—]+$', '', title)
            if title:
                return title
        
        # Try og:title meta tag
        og_match = re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        )
        if og_match:
            return og_match.group(1).strip()
        
        # Fallback to domain
        parsed = urlparse(url)
        return parsed.netloc or "Web Article"
    
    def _clean_text(self, text: str) -> str:
        """
        Clean up extracted text.
        
        Args:
            text: Raw extracted text
            
        Returns:
            Cleaned text
        """
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove excessive newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Strip leading/trailing whitespace
        text = text.strip()
        
        return text

