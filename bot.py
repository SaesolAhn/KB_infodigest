"""
InfoDigest Telegram Bot - Main Entry Point.
Processes URLs (Web, YouTube, PDF) and replies with AI-generated summaries.
"""

import asyncio
import time
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

from config import get_config, ConfigurationError
from services.async_extractor import (
    AsyncContentExtractor,
    ExtractionError,
    NoTranscriptError,
    PDFExtractionError,
)
from services.llm import LLMService, LLMError
from services.async_database import AsyncDatabaseService, DatabaseError
from utils.validators import extract_url_from_text, get_content_type, extract_comment_and_url
from utils.logging_config import configure_logging, get_logger, bind_context, clear_context
from utils.rate_limiter import RateLimiter

# Configure structured logging
configure_logging(log_level="INFO", json_format=False)
logger = get_logger(__name__)


class InfoDigestBot:
    """
    Main bot class that orchestrates URL processing and summarization.
    """

    def __init__(self):
        """Initialize the bot with configuration."""
        self.config = get_config()
        self.extractor = AsyncContentExtractor(timeout=self.config.request_timeout)
        self.llm = LLMService()
        self.db = AsyncDatabaseService(db_path=self.config.db_path)
        self.rate_limiter = RateLimiter(max_requests=5, window_seconds=60)

    async def init(self):
        """Async initialization."""
        await self.db.init()
        logger.info("bot_initialized", db_path=self.config.db_path)

    async def start_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        welcome_message = (
            "👋 **Welcome to InfoDigest Bot!**\n\n"
            "Send me a URL (article, YouTube video, or PDF) with an optional comment, "
            "and I'll provide a concise, eye-catching summary.\n\n"
            "**Supported formats:**\n"
            "• Web articles\n"
            "• YouTube videos (with captions)\n"
            "• PDF documents\n\n"
            "**How to use:**\n"
            "Your comment (optional) + URL\n\n"
            "**You'll receive:**\n"
            "✨ Eye-catching title\n"
            "📋 핵심요약 (essential summary)\n"
            "🔗 Source link\n\n"
            "Just paste a link to get started!"
        )
        await update.message.reply_text(welcome_message, parse_mode="Markdown")
        logger.info(
            "command_start",
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id if update.effective_user else None
        )

    async def help_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command."""
        help_message = (
            "**InfoDigest Bot Help**\n\n"
            "**How to use:**\n"
            "1. Send a URL (article, YouTube, or PDF)\n"
            "2. Optionally add a comment before or after the URL\n"
            "3. Wait for the AI to analyze the content\n"
            "4. Receive a concise, eye-catching summary with:\n"
            "   ✨ Eye-catching title\n"
            "   📋 핵심요약 (essential points only)\n"
            "   🔗 Source link\n\n"
            "**Example:**\n"
            "`This is interesting https://example.com/article`\n\n"
            "**Commands:**\n"
            "/start - Welcome message\n"
            "/help - This help message\n\n"
            "**Note:** YouTube videos must have captions/subtitles available."
        )
        await update.message.reply_text(help_message, parse_mode="Markdown")
        logger.info(
            "command_help",
            chat_id=update.effective_chat.id
        )

    async def process_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Process incoming messages containing URLs.

        Extracts content, generates summary, and replies.
        """
        if not update.message or not update.message.text:
            return

        message_text = update.message.text
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id if update.effective_user else chat_id

        # Bind context for structured logging
        bind_context(chat_id=chat_id, user_id=user_id)

        # Check rate limit
        rate_result = self.rate_limiter.acquire(user_id)
        if not rate_result.allowed:
            await update.message.reply_text(
                f"⏳ {rate_result.message}\n"
                f"Remaining requests: {rate_result.remaining}"
            )
            logger.warning(
                "rate_limit_exceeded",
                reset_in=rate_result.reset_in_seconds
            )
            clear_context()
            return

        # Extract comment and URL from message
        user_comment, url = extract_comment_and_url(message_text)
        if not url:
            clear_context()
            return  # Silently ignore messages without URLs

        content_type = get_content_type(url)
        if not content_type:
            await update.message.reply_text(
                "⚠️ Could not determine the content type for this URL."
            )
            clear_context()
            return

        # Send processing indicator
        processing_msg = await update.message.reply_text(
            "🔄 Processing your link... Please wait."
        )

        start_time = time.time()
        error_message: Optional[str] = None
        summary: str = ""
        title: str = ""
        raw_text_length: int = 0

        try:
            # Step 1: Extract content
            logger.info("extraction_started", url=url, content_type=content_type)
            text, title, content_type = await self.extractor.extract(url)
            raw_text_length = len(text)
            logger.info(
                "extraction_completed",
                title=title,
                text_length=raw_text_length
            )

            # Step 2: Generate summary
            logger.info("summarization_started", title=title)
            summary = self.llm.summarize(
                content=text,
                content_type=content_type,
                title=title,
                max_length=self.config.max_text_length
            )
            logger.info("summarization_completed")

            # Step 3: Format and send message
            formatted_message_parts = []

            if user_comment:
                formatted_message_parts.append(f"💬 **{user_comment}**\n")

            formatted_message_parts.append(f"{summary}\n")
            formatted_message_parts.append(f"━━━━━━━━━━━━━━━━━━━━\n🔗 [원문 보기]({url})")

            formatted_message = "\n".join(formatted_message_parts)
            await processing_msg.edit_text(
                formatted_message,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )

        except NoTranscriptError:
            error_message = "No transcript available for this video."
            await processing_msg.edit_text(f"⚠️ {error_message}")
            logger.warning("no_transcript", url=url)

        except PDFExtractionError as e:
            error_message = str(e)
            await processing_msg.edit_text(f"⚠️ {error_message}")
            logger.warning("pdf_extraction_failed", url=url, error=error_message)

        except ExtractionError as e:
            error_message = f"Extraction failed: {str(e)}"
            logger.error("extraction_failed", url=url, error=error_message)

            error_str = str(e).lower()
            if "youtube" in error_str or "transcript" in error_str or "video" in error_str:
                await processing_msg.edit_text(
                    "⚠️ Could not extract content from this YouTube video. "
                    "The video may be private, unavailable, or have no captions available."
                )
            elif "pdf" in error_str:
                await processing_msg.edit_text(
                    "⚠️ Could not extract content from this PDF. "
                    "The file may be corrupted, password-protected, or contain only images."
                )
            else:
                await processing_msg.edit_text(
                    "⚠️ Could not extract content from this URL. "
                    "Please check if the link is accessible."
                )

        except LLMError as e:
            error_message = f"AI error: {str(e)}"
            logger.error("llm_failed", error=error_message)
            await processing_msg.edit_text(
                "⚠️ Failed to generate summary. Please try again later."
            )

        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            logger.exception("unexpected_error", error=error_message)
            await processing_msg.edit_text(
                "⚠️ An unexpected error occurred. Please try again."
            )

        # Calculate processing time
        processing_time_ms = int((time.time() - start_time) * 1000)

        # Step 4: Log to database
        try:
            await self.db.save_log(
                url=url,
                title=title or "Unknown",
                content_type=content_type or "web",
                summary=summary,
                raw_text_length=raw_text_length,
                chat_id=chat_id,
                message_id=processing_msg.message_id,
                processing_time_ms=processing_time_ms,
                error=error_message,
                user_comment=user_comment,
            )
            logger.info(
                "digest_saved",
                processing_time_ms=processing_time_ms,
                success=error_message is None
            )
        except DatabaseError as e:
            logger.error("database_save_failed", error=str(e))

        clear_context()

    async def cleanup(self):
        """Clean up resources."""
        await self.extractor.close()
        logger.info("bot_cleanup_completed")

    def run(self) -> None:
        """Start the bot polling loop."""
        logger.info("bot_starting")

        # Build application
        application = (
            Application.builder()
            .token(self.config.telegram_token)
            .post_init(self._post_init)
            .post_shutdown(self._post_shutdown)
            .build()
        )

        # Add handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self.process_message
            )
        )

        # Start polling
        logger.info("bot_polling_started")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    async def _post_init(self, application):
        """Called after application initialization."""
        await self.init()

    async def _post_shutdown(self, application):
        """Called during shutdown."""
        await self.cleanup()


def main():
    """Main entry point."""
    try:
        bot = InfoDigestBot()
        bot.run()
    except ConfigurationError as e:
        logger.error("configuration_error", error=str(e))
        print(f"\n❌ Configuration Error: {e}")
        print("Please check your .env file and ensure all required variables are set.")
    except KeyboardInterrupt:
        logger.info("bot_stopped_by_user")
    except Exception as e:
        logger.exception("fatal_error", error=str(e))
        raise


if __name__ == "__main__":
    main()
