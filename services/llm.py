"""
LLM Service for InfoDigest Bot.
Handles AI summarization using the unified AI client.
"""

import re
from typing import Optional, Callable

from models.schemas import ContentType


class LLMError(Exception):
    """Raised when LLM processing fails."""
    pass


# The strict summary format prompt
SUMMARY_PROMPT_TEMPLATE = """You are an expert content summarizer. Analyze the following content and provide a concise, objective summary.

You MUST follow this EXACT Markdown format:

# [Eye-Catching Title]
*Create a compelling, attention-grabbing title that captures the essence*

**핵심요약:**
[One concise sentence - the most essential takeaway from the original content]

**주요 내용:**
- [Essential point 1 - from original content only]

- [Essential point 2 - from original content only]

- [Essential point 3 - from original content only]

CRITICAL RULES:
1. The title MUST be eye-catching, compelling, and attention-grabbing
2. Extract ONLY essential information from the original content
3. Minimize text - be extremely concise, focus on fundamentals only
4. NO subjective interpretation - summarize what the original says, NOT its implications
5. NO analysis of what it means or what should be done - only what was said
6. Keep the entire summary under 150 words
7. Use clear, direct language
8. Focus on facts and key points from the original content only
9. MANDATORY: There MUST be a blank line between each bullet point in "주요 내용" section - each point must be separated by an empty line

CONTENT TO SUMMARIZE:
{content}

Provide the summary now:"""


class LLMService:
    """
    Service for AI-powered content summarization.
    Uses ai_client for provider-agnostic text generation.
    """

    def __init__(self) -> None:
        """Initialize the LLM service with the configured AI provider."""
        try:
            from ai_client import call_ai, AIAPIError, get_configured_provider
        except Exception as exc:
            raise LLMError(f"Failed to initialize AI client: {exc}") from exc

        self._call_ai: Callable[[str, Optional[float]], str] = call_ai
        self._ai_error = AIAPIError
        self.provider = get_configured_provider()
    
    def summarize(
        self,
        content: str,
        content_type: str,
        title: Optional[str] = None,
        max_length: int = 100000
    ) -> str:
        """
        Generate a structured summary of the content.
        
        Args:
            content: The text content to summarize
            content_type: Type of content ('youtube', 'web', 'pdf')
            title: Optional title to include (may be overridden by AI)
            max_length: Maximum content length to process
            
        Returns:
            Formatted summary string in Markdown
            
        Raises:
            LLMError: If summarization fails
        """
        if not content or not content.strip():
            raise LLMError("No content provided for summarization")
        
        # Truncate if necessary
        if len(content) > max_length:
            content = content[:max_length] + "\n\n[Content truncated...]"
        
        # Build the prompt (no content_type needed)
        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            content=content
        )
        
        try:
            # Generate summary using configured provider
            summary = self._call_ai(prompt, temperature=0.3)
            if summary:
                # Post-process to ensure spacing between bullet points
                summary = self._ensure_bullet_spacing(summary)
                return summary.strip()
            raise LLMError("Empty response from AI model")
        except self._ai_error as e:
            raise LLMError(f"Failed to generate summary: {str(e)}") from e
        except Exception as e:
            raise LLMError(f"Failed to generate summary: {str(e)}") from e
    
    def _ensure_bullet_spacing(self, text: str) -> str:
        """
        Ensure proper spacing between bullet points in the summary.
        
        Args:
            text: The summary text
            
        Returns:
            Text with ensured spacing between bullet points
        """
        # Find the "주요 내용:" section
        lines = text.split('\n')
        result_lines = []
        in_key_points = False
        
        for i, line in enumerate(lines):
            # Check if we're entering the key points section
            if '**주요 내용:**' in line or '주요 내용:' in line:
                in_key_points = True
                result_lines.append(line)
                continue
            
            # Check if we're leaving the key points section (next section starts)
            if in_key_points and line.strip() and not line.strip().startswith('-'):
                # Check if it's a new section (starts with ** or #)
                if line.strip().startswith('**') or line.strip().startswith('#'):
                    in_key_points = False
                    result_lines.append(line)
                    continue
            
            # If we're in key points section and this is a bullet point
            if in_key_points and line.strip().startswith('-'):
                # Ensure there's a blank line before this bullet (except the first one)
                if result_lines and result_lines[-1].strip() and not result_lines[-1].strip().startswith('-'):
                    result_lines.append('')  # Add blank line before bullet
                result_lines.append(line)
                # Ensure there's a blank line after this bullet (if not last bullet)
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if next_line.strip() and next_line.strip().startswith('-'):
                        result_lines.append('')  # Add blank line after bullet
            else:
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    def test_connection(self) -> bool:
        """
        Test the connection to the Gemini API.
        
        Returns:
            True if connection is successful
            
        Raises:
            LLMError: If connection fails
        """
        try:
            response = self._call_ai("Say 'OK' if you can read this.", temperature=0.0)
            return bool(response)
        except self._ai_error as e:
            raise LLMError(f"Failed to connect to AI provider: {str(e)}") from e

