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
from services.database import DatabaseService, DatabaseError
from utils.validators import extract_url_from_text, get_content_type, extract_comment_and_url

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
        self.db = DatabaseService(db_path=self.config.db_path)
        self.db.connect()
    
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
        
        # Extract comment and URL from message
        user_comment, url = extract_comment_and_url(message_text)
        if not url:
            return  # Silently ignore messages without URLs
        
        content_type = get_content_type(url)
        if not content_type:
            await update.message.reply_text(
                "⚠️ Could not determine the content type for this URL."
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
            
            # Step 3: Format and send message
            # Format: user comment > summary > source link
            # Make it aesthetic, eye-catching, and intuitive
            formatted_message_parts = []
            
            # Add user comment if provided (with visual separator)
            if user_comment:
                formatted_message_parts.append(f"💬 **{user_comment}**\n")
            
            # Add summary (already formatted by LLM with eye-catching title)
            formatted_message_parts.append(f"{summary}\n")
            
            # Add source link with visual separator
            formatted_message_parts.append(f"━━━━━━━━━━━━━━━━━━━━\n🔗 [원문 보기]({url})")
            
            formatted_message = "\n".join(formatted_message_parts)
            await processing_msg.edit_text(formatted_message, parse_mode="Markdown", disable_web_page_preview=True)
            
        except NoTranscriptError:
            error_message = "No transcript available for this video."
            await processing_msg.edit_text(f"⚠️ {error_message}")
            
        except PDFExtractionError as e:
            error_message = str(e)
            await processing_msg.edit_text(f"⚠️ {error_message}")
            
        except ExtractionError as e:
            error_message = f"Extraction failed: {str(e)}"
            logger.error(error_message)
            
            # Provide more specific error message based on error content
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
        
        # Step 4: Log to database
        try:
            self.db.save_log(
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
        except DatabaseError as e:
            logger.error(f"Failed to save log: {e}")
    
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
        self.db.close()


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

