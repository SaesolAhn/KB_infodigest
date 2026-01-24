"""
ai_client.py - Abstracted AI API client for easy model/provider switching.

Supports multiple AI providers (Qwen, OpenAI, etc.) with a unified interface.
Includes retry logic with exponential backoff for resilience.
"""

import os
from typing import Optional, Tuple
from openai import OpenAI
from dotenv import load_dotenv
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import logging

load_dotenv()

# Get logger for retry logging
logger = logging.getLogger(__name__)

# AI Provider configuration - required from .env
AI_PROVIDER = os.getenv("AI_PROVIDER")
if not AI_PROVIDER:
    raise ValueError(
        "AI_PROVIDER is required. Set it in your .env file.\n"
        "Example: AI_PROVIDER=qwen or AI_PROVIDER=openai"
    )
AI_PROVIDER = AI_PROVIDER.lower()

# Qwen API configuration
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
QWEN_API_BASE_URL = os.getenv(
    "QWEN_API_BASE_URL",
    "https://dashscope-intl.aliyuncs.com/compatible-mode"
)
QWEN_MODEL = os.getenv("QWEN_MODEL")
if AI_PROVIDER == "qwen" and not QWEN_MODEL:
    raise ValueError(
        "QWEN_MODEL is required when using Qwen provider. Set it in your .env file.\n"
        "Example: QWEN_MODEL=qwen-flash or QWEN_MODEL=qwen-plus"
    )

# OpenAI API configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE_URL = os.getenv(
    "OPENAI_API_BASE_URL",
    "https://api.openai.com"
)
OPENAI_MODEL = os.getenv("OPENAI_MODEL")
if AI_PROVIDER == "openai" and not OPENAI_MODEL:
    raise ValueError(
        "OPENAI_MODEL is required when using OpenAI provider. Set it in your .env file.\n"
        "Example: OPENAI_MODEL=gpt-4o-mini or OPENAI_MODEL=gpt-4"
    )

# Default temperature for structured outputs
DEFAULT_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.3"))


class AIAPIError(Exception):
    """Custom exception for AI API errors."""
    pass


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def call_qwen(prompt: str, temperature: float = DEFAULT_TEMPERATURE) -> str:
    """
    Call Qwen API for text generation using OpenAI-compatible client.

    Includes automatic retry with exponential backoff for transient failures.

    Args:
        prompt: The prompt to send to Qwen
        temperature: Sampling temperature (default: 0.3)

    Returns:
        Generated text response

    Raises:
        AIAPIError: If Qwen API call fails after retries
    """
    if not QWEN_API_KEY:
        raise AIAPIError(
            "QWEN_API_KEY is not set in environment variables. "
            "Please set it in your .env file. Example: QWEN_API_KEY=sk-..."
        )
    
    # Validate API key format (should not contain quotes or spaces)
    api_key_clean = QWEN_API_KEY.strip().strip('"').strip("'")
    if not api_key_clean:
        raise AIAPIError(
            "QWEN_API_KEY is empty or has quotes around it. "
            "Remove quotes from your .env file. Example: QWEN_API_KEY=sk-... (not QWEN_API_KEY=\"sk-...\")"
        )
    
    # Construct base URL - ensure it ends with /v1 for OpenAI client
    base_url = QWEN_API_BASE_URL.rstrip('/')
    if not base_url.endswith('/v1'):
        base_url = f"{base_url}/v1"
    
    try:
        # Use OpenAI client with Qwen's compatible API endpoint
        client = OpenAI(
            api_key=api_key_clean,
            base_url=base_url,
            timeout=120.0
        )
        
        response = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=temperature
        )
        
        # Extract content from response
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content or ""
        else:
            raise AIAPIError("No response content received from Qwen API")
            
    except Exception as e:
        error_msg = f"Qwen API error: {str(e)}"
        
        # Add helpful troubleshooting for 401 errors
        if "401" in str(e) or "Unauthorized" in str(e):
            error_msg += "\n\nTroubleshooting 401 (Unauthorized) error:"
            error_msg += "\n  1. Check that QWEN_API_KEY is set correctly in your .env file"
            error_msg += "\n  2. Verify your API key is valid at https://dashscope.console.aliyun.com/"
            error_msg += "\n  3. Ensure there are no extra spaces or quotes around the API key"
            error_msg += "\n  4. Make sure your API key hasn't expired or been revoked"
            if not api_key_clean:
                error_msg += "\n  ⚠️  QWEN_API_KEY appears to be empty or not set!"
            elif len(api_key_clean) < 10:
                error_msg += f"\n  ⚠️  QWEN_API_KEY looks suspiciously short ({len(api_key_clean)} chars)"
        
        raise AIAPIError(error_msg)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def call_openai(prompt: str, temperature: float = DEFAULT_TEMPERATURE) -> str:
    """
    Call OpenAI API for text generation using OpenAI client.

    Includes automatic retry with exponential backoff for transient failures.

    Args:
        prompt: The prompt to send to OpenAI
        temperature: Sampling temperature (default: 0.3)

    Returns:
        Generated text response

    Raises:
        AIAPIError: If OpenAI API call fails after retries
    """
    if not OPENAI_API_KEY:
        raise AIAPIError("OPENAI_API_KEY is not set in environment variables")
    
    # Construct base URL - ensure it ends with /v1 for OpenAI client
    base_url = OPENAI_API_BASE_URL.rstrip('/')
    if not base_url.endswith('/v1'):
        base_url = f"{base_url}/v1"
    
    try:
        # Use OpenAI client
        client = OpenAI(
            api_key=OPENAI_API_KEY.strip().strip('"').strip("'"),
            base_url=base_url,
            timeout=120.0
        )
        
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=temperature
        )
        
        # Extract content from response
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content or ""
        else:
            raise AIAPIError("No response content received from OpenAI API")
            
    except Exception as e:
        error_msg = f"OpenAI API error: {str(e)}"
        raise AIAPIError(error_msg)


def call_ai(prompt: str, temperature: Optional[float] = None) -> str:
    """
    Unified interface to call AI API based on configured provider.
    
    Args:
        prompt: The prompt to send to the AI
        temperature: Sampling temperature (default: uses DEFAULT_TEMPERATURE)
        
    Returns:
        Generated text response
        
    Raises:
        AIAPIError: If AI API call fails or provider is not supported
    """
    if temperature is None:
        temperature = DEFAULT_TEMPERATURE
    
    provider = AI_PROVIDER.lower()
    
    if provider == "qwen":
        return call_qwen(prompt, temperature)
    elif provider == "openai":
        return call_openai(prompt, temperature)
    else:
        raise AIAPIError(f"Unsupported AI provider: {provider}. Supported providers: qwen, openai")


def get_configured_provider() -> str:
    """
    Get the currently configured AI provider.
    
    Returns:
        Name of the configured provider
    """
    return AI_PROVIDER


def validate_qwen_config() -> Tuple[bool, str]:
    """
    Validate Qwen API configuration and return status.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not QWEN_API_KEY:
        return False, "QWEN_API_KEY is not set in .env file"
    
    api_key_clean = QWEN_API_KEY.strip().strip('"').strip("'")
    if not api_key_clean:
        return False, "QWEN_API_KEY is empty or only contains quotes/spaces"
    
    if len(api_key_clean) < 10:
        return False, f"QWEN_API_KEY looks too short ({len(api_key_clean)} characters). Expected at least 20+ characters."
    
    if not QWEN_MODEL:
        return False, "QWEN_MODEL is not set in .env file"
    
    return True, ""
