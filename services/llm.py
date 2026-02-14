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

**AI 핵심요약**
• [One concise sentence - the most essential takeaway from the original content]

**주요 내용**
{bullet_points}

[3 #hashtags based on keywords]

CRITICAL RULES:
1. The title MUST be eye-catching, compelling, and attention-grabbing
2. There MUST be a blank line between the title and "**AI 핵심요약**"
3. DO NOT use colons after "AI 핵심요약" or "주요 내용"
4. Use the "•" (circle) symbol for pinpoint bullet points in BOTH "AI 핵심요약" and "주요 내용" sections
5. DO NOT use periods at the end of bullet points in "주요 내용"
6. For "주요 내용", you MUST use ONLY information from the original content. DO NOT incorporate user comments or context into these points.
7. NO blank line after "**주요 내용**" - bullet points start immediately on next line
8. MANDATORY: There MUST be a blank line between each bullet point in "주요 내용" section (except the first one after the header)
9. Extract ONLY essential information from the original content
10. Minimize text - be extremely concise, focus on fundamentals only
11. NO subjective interpretation - summarize what the original says, NOT its implications
12. NO analysis of what it means or what should be done - only what was said
13. Keep the entire summary under 150 words
14. Use clear, direct language
15. Focus on facts and key points from the original content only
16. At the end, generate exactly 3 hashtags starting with #
{context_instruction}
{language_instruction}

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
        max_length: int = 100000,
        user_context: Optional[str] = None,
        translate_to_korean: bool = False
    ) -> str:
        """
        Generate a structured summary of the content.
        
        Args:
            content: The text content to summarize
            content_type: Type of content ('youtube', 'web', 'pdf')
            title: Optional title to include (may be overridden by AI)
            max_length: Maximum content length to process
            user_context: Optional context about what the user wants to focus on
            translate_to_korean: Whether to translate the summary to Korean
            
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
        
        # Calculate number of bullet points based on content length
        content_length = len(content)
        if content_length < 2000:
            num_bullets = 3
        elif content_length < 5000:
            num_bullets = 4
        elif content_length < 10000:
            num_bullets = 5
        elif content_length < 20000:
            num_bullets = 6
        else:
            num_bullets = 7
        
        # Generate bullet point placeholders
        bullet_points = "\n\n".join([f"• [Essential point {i+1} - from original content only]" for i in range(num_bullets)])
        
        # Build context instruction
        if user_context:
            context_instruction = f"\n16. FOCUS AREAS: The user specifically wants to know about: \"{user_context}\"\n    Pay special attention to these aspects in your summary while maintaining the required format."
        else:
            context_instruction = ""

        # Build language instruction
        if translate_to_korean:
            language_instruction = "\n17. LANGUAGE: Generate the ENTIRE summary in Korean (한국어)."
        else:
            language_instruction = "\n17. LANGUAGE: Generate the summary in the same language as the original content."
        
        # Build the prompt
        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            content=content,
            bullet_points=bullet_points,
            context_instruction=context_instruction,
            language_instruction=language_instruction
        )
        
        try:
            # Generate summary using configured provider
            summary = self._call_ai(prompt, temperature=0.3)
            if summary:
                formatted_summary = summary.strip()
                # Apply spacing rules to ensure consistent layout
                return self._ensure_bullet_spacing(formatted_summary)
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
            # Match "주요 내용" or "AI 핵심요약"
            is_header = ('주요 내용' in line or 'AI 핵심요약' in line) and ('**' in line or ':' in line or not line.startswith(' '))
            
            if is_header:
                # If we were in key points, we're starting a new one (e.g. going from summary to details)
                in_key_points = True
                result_lines.append(line)
                continue
            
            # Check if we're leaving the key points section
            if in_key_points and line.strip() and not (line.strip().startswith('-') or line.strip().startswith('•')):
                # Check if it's a new section (starts with ** or #)
                if line.strip().startswith('**') or line.strip().startswith('#'):
                    in_key_points = False
                    result_lines.append(line)
                    continue
            
            # If we're in key points section and this is a bullet point
            if in_key_points and (line.strip().startswith('-') or line.strip().startswith('•')):
                # Ensure there's a blank line before this bullet (except the first one after a header)
                prev_line_is_header = result_lines and ('주요 내용' in result_lines[-1] or 'AI 핵심요약' in result_lines[-1])
                
                if result_lines and result_lines[-1].strip() and not prev_line_is_header and not (result_lines[-1].strip().startswith('-') or result_lines[-1].strip().startswith('•')):
                    result_lines.append('')  # Add blank line before bullet
                
                result_lines.append(line)
                
                # Ensure there's a blank line after this bullet (if not last bullet)
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if next_line.strip() and (next_line.strip().startswith('-') or next_line.strip().startswith('•')):
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

