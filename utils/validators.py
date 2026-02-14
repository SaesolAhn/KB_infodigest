"""
URL validation and content type detection utilities.
"""

import re
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse


# YouTube URL patterns
YOUTUBE_PATTERNS = [
    r'(https?://)?(www\.)?youtube\.com/watch\?v=[\w-]+',
    r'(https?://)?(www\.)?youtube\.com/shorts/[\w-]+',
    r'(https?://)?(www\.)?youtu\.be/[\w-]+',
    r'(https?://)?(www\.)?youtube\.com/embed/[\w-]+',
]

# URL extraction pattern
URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+'
)

NAVER_STOCK_HOST_PATTERN = re.compile(r'(^|\.)stock\.naver\.com$', re.IGNORECASE)


def is_youtube_url(url: str) -> bool:
    """
    Check if the URL is a YouTube video link.
    
    Args:
        url: The URL to check
        
    Returns:
        True if YouTube URL, False otherwise
    """
    for pattern in YOUTUBE_PATTERNS:
        if re.match(pattern, url, re.IGNORECASE):
            return True
    return False


def is_pdf_url(url: str) -> bool:
    """
    Check if the URL points to a PDF file.
    
    Args:
        url: The URL to check
        
    Returns:
        True if PDF URL, False otherwise
    """
    parsed = urlparse(url.lower())
    path = parsed.path
    
    # Check file extension
    if path.endswith('.pdf'):
        return True
    
    # Check common PDF hosting patterns
    if 'pdf' in parsed.query.lower():
        return True
        
    return False


def is_web_url(url: str) -> bool:
    """
    Validate if the string is a valid web URL.
    
    Args:
        url: The URL to validate
        
    Returns:
        True if valid web URL, False otherwise
    """
    try:
        parsed = urlparse(url)
        return all([
            parsed.scheme in ('http', 'https'),
            parsed.netloc,
        ])
    except Exception:
        return False


def is_naver_stock_url(url: str) -> bool:
    """
    Check if the URL points to a Naver Stock page.

    Args:
        url: The URL to check

    Returns:
        True if URL is under stock.naver.com, False otherwise
    """
    if not is_web_url(url):
        return False

    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    return bool(NAVER_STOCK_HOST_PATTERN.search(hostname))


def extract_naver_stock_code(value: str) -> Optional[str]:
    """
    Extract 6-digit stock code from plain text or Naver Stock URL.

    Supports:
    - Plain code: 005930
    - URL path: https://stock.naver.com/domestic/005930/total
    - URL query: ?code=005930

    Args:
        value: User input text or URL

    Returns:
        6-digit stock code or None
    """
    if not value:
        return None

    raw = value.strip()

    # Direct code input
    direct_match = re.fullmatch(r'\d{6}', raw)
    if direct_match:
        return direct_match.group(0)

    # Code embedded in text
    embedded_match = re.search(r'\b(\d{6})\b', raw)
    if embedded_match and not is_web_url(raw):
        return embedded_match.group(1)

    if not is_web_url(raw):
        return None

    parsed = urlparse(raw)

    # code query parameter
    query = parse_qs(parsed.query)
    code_values = query.get("code", [])
    if code_values:
        query_code = code_values[0].strip()
        if re.fullmatch(r'\d{6}', query_code):
            return query_code

    # /domestic/{code}/... pattern
    path_match = re.search(r'/domestic/(\d{6})(?:/|$)', parsed.path)
    if path_match:
        return path_match.group(1)

    # Last-resort 6-digit segment in URL
    any_path_match = re.search(r'/(\d{6})(?:/|$)', parsed.path)
    if any_path_match:
        return any_path_match.group(1)

    return None


def get_content_type(url: str) -> Optional[str]:
    """
    Determine the content type of a URL.
    
    Args:
        url: The URL to analyze
        
    Returns:
        'youtube', 'pdf', 'web', or None if invalid
    """
    if not is_web_url(url):
        return None
    
    if is_youtube_url(url):
        return 'youtube'
    
    if is_pdf_url(url):
        return 'pdf'
    
    return 'web'


def extract_url_from_text(text: str) -> Optional[str]:
    """
    Extract the first URL from a text message.
    
    Args:
        text: The text to search for URLs
        
    Returns:
        The first URL found, or None
    """
    match = URL_PATTERN.search(text)
    if match:
        return match.group(0)
    return None


def extract_youtube_video_id(url: str) -> Optional[str]:
    """
    Extract the video ID from a YouTube URL.
    
    Args:
        url: The YouTube URL
        
    Returns:
        The video ID or None if not found
    """
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)([\w-]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None


def extract_comment_and_url(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract user comment and URL from a text message.
    
    The comment can appear before or after the URL.
    
    Args:
        text: The text message containing URL and optional comment
        
    Returns:
        Tuple of (comment, url) where comment can be None if not provided
    """
    # Find the URL in the text
    url_match = URL_PATTERN.search(text)
    if not url_match:
        return None, None
    
    url = url_match.group(0)
    url_start = url_match.start()
    url_end = url_match.end()
    
    # Extract text before and after URL
    text_before = text[:url_start].strip()
    text_after = text[url_end:].strip()
    
    # Combine text before and after, prioritizing text before URL
    comment = text_before if text_before else text_after
    comment = comment if comment else None
    
    return comment, url
