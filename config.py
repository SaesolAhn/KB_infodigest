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
    
    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "infodigest"
    mongodb_collection: str = "digest_logs"
    
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
        
        return cls(
            telegram_token=telegram_token,
            mongodb_uri=os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
            mongodb_database=os.getenv("MONGODB_DATABASE", "infodigest"),
            mongodb_collection=os.getenv("MONGODB_COLLECTION", "digest_logs"),
            max_text_length=int(os.getenv("MAX_TEXT_LENGTH", "100000")),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
        )


def get_config() -> Config:
    """Get the application configuration."""
    return Config.from_env()

