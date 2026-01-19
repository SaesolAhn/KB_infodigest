"""
URL validation and content type detection utilities.
"""

import re
from typing import Optional, Tuple
from urllib.parse import urlparse


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

