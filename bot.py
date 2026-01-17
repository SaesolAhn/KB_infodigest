"""
InfoDigest Telegram Bot - Main Entry Point.
Processes URLs (Web, YouTube, PDF) and replies with AI-generated summaries.
"""

import logging
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
from services.extractor import (
    ContentExtractor,
    ExtractionError,
    NoTranscriptError,
    PDFExtractionError,
)
from services.llm import LLMService, LLMError
from services.cache import CacheService, CacheError
from utils.validators import extract_url_from_text, get_content_type

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class InfoDigestBot:
    """
    Main bot class that orchestrates URL processing and summarization.
    """
    
    def __init__(self):
        """Initialize the bot with configuration."""
        self.config = get_config()
        self.extractor = ContentExtractor(timeout=self.config.request_timeout)
        self.llm = LLMService()
        self.cache = CacheService(
            cache_dir=self.config.cache_dir,
            default_ttl_days=self.config.cache_ttl_days
        )
    
    async def start_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        welcome_message = (
            "👋 **Welcome to InfoDigest Bot!**\n\n"
            "Send me a URL (article, YouTube video, or PDF) and I'll provide "
            "a structured summary.\n\n"
            "**Supported formats:**\n"
            "• Web articles\n"
            "• YouTube videos (with captions)\n"
            "• PDF documents\n\n"
            "Just paste a link to get started!"
        )
        await update.message.reply_text(welcome_message, parse_mode="Markdown")
    
    async def help_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command."""
        help_message = (
            "**InfoDigest Bot Help**\n\n"
            "**How to use:**\n"
            "1. Send any URL (article, YouTube, or PDF)\n"
            "2. Wait for the AI to analyze the content\n"
            "3. Receive a structured summary\n\n"
            "**Commands:**\n"
            "/start - Welcome message\n"
            "/help - This help message\n\n"
            "**Note:** YouTube videos must have captions/subtitles available."
        )
        await update.message.reply_text(help_message, parse_mode="Markdown")
    
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
        
        # Extract URL from message
        url = extract_url_from_text(message_text)
        if not url:
            return  # Silently ignore messages without URLs
        
        content_type = get_content_type(url)
        if not content_type:
            await update.message.reply_text(
                "⚠️ Could not determine the content type for this URL."
            )
            return
        
        # Check cache first
        cached = self.cache.get(url)
        if cached:
            logger.info(f"Cache hit for URL: {url}")
            await update.message.reply_text(
                cached['summary'],
                parse_mode="Markdown"
            )
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
            logger.info(f"Extracting content from: {url}")
            text, title, content_type = self.extractor.extract(url)
            raw_text_length = len(text)
            
            # Step 2: Generate summary
            logger.info(f"Generating summary for: {title}")
            summary = self.llm.summarize(
                content=text,
                content_type=content_type,
                title=title,
                max_length=self.config.max_text_length
            )
            
            # Step 3: Send summary
            await processing_msg.edit_text(summary, parse_mode="Markdown")
            
        except NoTranscriptError:
            error_message = "No transcript available for this video."
            await processing_msg.edit_text(f"⚠️ {error_message}")
            
        except PDFExtractionError as e:
            error_message = str(e)
            await processing_msg.edit_text(f"⚠️ {error_message}")
            
        except ExtractionError as e:
            error_message = f"Extraction failed: {str(e)}"
            logger.error(error_message)
            await processing_msg.edit_text(
                "⚠️ Could not extract content from this URL. "
                "Please check if the link is accessible."
            )
            
        except LLMError as e:
            error_message = f"AI error: {str(e)}"
            logger.error(error_message)
            await processing_msg.edit_text(
                "⚠️ Failed to generate summary. Please try again later."
            )
            
        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            logger.exception("Unexpected error processing message")
            await processing_msg.edit_text(
                "⚠️ An unexpected error occurred. Please try again."
            )
        
        # Calculate processing time
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # Step 4: Cache the result (only if successful)
        if summary and not error_message:
            try:
                self.cache.set(
                    url=url,
                    summary=summary,
                    title=title or "Unknown",
                    content_type=content_type or "web",
                    raw_text_length=raw_text_length,
                    processing_time_ms=processing_time_ms,
                )
                logger.info(f"Cached summary for URL: {url}")
            except CacheError as e:
                logger.warning(f"Failed to cache result: {e}")
    
    def run(self) -> None:
        """Start the bot polling loop."""
        logger.info("Starting InfoDigest Bot...")
        
        # Build application
        application = (
            Application.builder()
            .token(self.config.telegram_token)
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
        logger.info("Bot is running. Press Ctrl+C to stop.")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    def cleanup(self) -> None:
        """Clean up resources."""
        self.extractor.close()


def main():
    """Main entry point."""
    try:
        bot = InfoDigestBot()
        bot.run()
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        print(f"\n❌ Configuration Error: {e}")
        print("Please check your .env file and ensure all required variables are set.")
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception("Fatal error")
        raise


if __name__ == "__main__":
    main()

