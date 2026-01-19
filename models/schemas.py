"""
Data models and schemas for database records.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional


class ContentType(str, Enum):
    """Enumeration of supported content types."""
    YOUTUBE = "Video"
    WEB = "Article"
    PDF = "Report"
    
    @classmethod
    def from_string(cls, content_type: str) -> "ContentType":
        """Convert string content type to enum."""
        mapping = {
            "youtube": cls.YOUTUBE,
            "web": cls.WEB,
            "pdf": cls.PDF,
        }
        return mapping.get(content_type.lower(), cls.WEB)


@dataclass
class DigestLog:
    """
    Schema for digest log entries stored in the database.
    
    Attributes:
        url: The original URL that was processed
        title: The extracted or generated title of the content
        content_type: Type of content (Video/Article/Report)
        summary: The AI-generated summary in markdown format
        user_comment: Optional user comment provided with the URL
        raw_text_length: Character count of extracted text
        timestamp: When the digest was created
        chat_id: Telegram chat/channel ID
        message_id: Telegram message ID for the response
        processing_time_ms: Time taken to process in milliseconds
        error: Error message if processing failed
    """
    url: str
    title: str
    content_type: ContentType
    summary: str
    user_comment: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    raw_text_length: int = 0
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    processing_time_ms: Optional[int] = None
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database operations."""
        data = asdict(self)
        data["content_type"] = self.content_type.value
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> "DigestLog":
        """Create instance from database record."""
        data = data.copy()
        if "id" in data:
            del data["id"]
        if isinstance(data.get("content_type"), str):
            # Map display value back to enum
            type_mapping = {
                "Video": ContentType.YOUTUBE,
                "Article": ContentType.WEB,
                "Report": ContentType.PDF,
            }
            data["content_type"] = type_mapping.get(data["content_type"], ContentType.WEB)
        return cls(**data)

