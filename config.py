"""
Configuration management for InfoDigest Bot.
Loads environment variables and provides centralized configuration.
"""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class ConfigurationError(Exception):
    """Raised when required configuration is missing."""
    pass


@dataclass
class Config:
    """Application configuration."""
    
    # Telegram Bot
    telegram_token: str
    
    # Cache settings
    cache_dir: str = "cache"  # Directory for cache files
    cache_ttl_days: Optional[int] = None  # Cache TTL in days (None = no expiration)
    
    # Processing limits
    max_text_length: int = 100000  # Max characters to send to LLM
    request_timeout: int = 30  # Seconds
    
    @classmethod
    def from_env(cls) -> "Config":
        """
        Load configuration from environment variables.
        
        Raises:
            ConfigurationError: If required variables are missing
        """
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        missing = []
        if not telegram_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        
        if missing:
            raise ConfigurationError(
                f"Missing required environment variables: {', '.join(missing)}"
            )
        
        # Parse cache TTL (optional)
        cache_ttl = os.getenv("CACHE_TTL_DAYS")
        cache_ttl_days = int(cache_ttl) if cache_ttl else None
        
        return cls(
            telegram_token=telegram_token,
            cache_dir=os.getenv("CACHE_DIR", "cache"),
            cache_ttl_days=cache_ttl_days,
            max_text_length=int(os.getenv("MAX_TEXT_LENGTH", "100000")),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
        )


def get_config() -> Config:
    """Get the application configuration."""
    return Config.from_env()

