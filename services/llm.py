"""
LLM Service for InfoDigest Bot.
Handles AI summarization using the unified AI client.
"""

from typing import Optional, Callable

from models.schemas import ContentType


class LLMError(Exception):
    """Raised when LLM processing fails."""
    pass


# The strict summary format prompt
SUMMARY_PROMPT_TEMPLATE = """You are an expert content summarizer. Analyze the following {content_type} content and provide a structured summary.

You MUST follow this EXACT Markdown format:

**[Title of Content]**
*Type: {content_type_display}*

**One-Line Gist:**
[1 sentence takeaway - the most important insight]

**Key Points:**
- [Point 1 - most important]
- [Point 2]
- [Point 3]

**Actionable Insight:**
[Relevance to market/investment - what should the reader do with this information?]

RULES:
1. The title should be concise and descriptive
2. The one-line gist must be exactly ONE sentence
3. Key points should be 3-5 bullet points, each being 1-2 sentences max
4. Actionable insight should focus on practical implications
5. Keep the entire summary under 300 words
6. Use clear, professional language

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
        
        # Get display name for content type
        content_type_enum = ContentType.from_string(content_type)
        content_type_display = content_type_enum.value
        
        # Build the prompt
        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            content_type=content_type.lower(),
            content_type_display=content_type_display,
            content=content
        )
        
        try:
            # Generate summary using configured provider
            summary = self._call_ai(prompt, temperature=0.3)
            if summary:
                return summary.strip()
            raise LLMError("Empty response from AI model")
        except self._ai_error as e:
            raise LLMError(f"Failed to generate summary: {str(e)}") from e
        except Exception as e:
            raise LLMError(f"Failed to generate summary: {str(e)}") from e
    
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

