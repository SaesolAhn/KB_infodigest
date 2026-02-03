"""
InfoDigest Telegram Bot - Main Entry Point.
Processes URLs (Web, YouTube, PDF) and replies with AI-generated summaries.
"""

import asyncio
import time
import re
import html
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
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

# Conversation states
AWAITING_CONTEXT = "awaiting_context"
AWAITING_TRANSLATION = "awaiting_translation"


def is_korean(text: str) -> bool:
    """Check if text contains any Hangul characters."""
    return bool(re.search(r'[\uac00-\ud7af]', text))



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
        )
        await update.effective_message.reply_text(welcome_message, parse_mode="Markdown")
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
            "   📋 AI insight (essential points only)\n"
            "   🔗 Source link\n\n"
            "**Example:**\n"
            "`This is interesting https://example.com/article`\n\n"
            "**Commands:**\n"
            "/start - Welcome message\n"
            "/help - This help message\n\n"
            "**Note:** YouTube videos must have captions/subtitles available."
        )
        await update.effective_message.reply_text(help_message, parse_mode="Markdown")
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
        Process incoming messages containing URLs or conversation responses.

        Handles multi-step conversation flow:
        1. URL detected -> Ask for context
        2. Context provided -> Generate summary
        3. Request caption
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
            await update.effective_message.reply_text(
                f"⏳ {rate_result.message}\n"
                f"Remaining requests: {rate_result.remaining}"
            )
            logger.warning(
                "rate_limit_exceeded",
                reset_in=rate_result.reset_in_seconds
            )
            clear_context()
            return

        # Get conversation state
        user_state = context.user_data.get('state')
        
        # Handle conversation states
        if user_state == AWAITING_CONTEXT:
            # User is responding with context for their URL
            await self._handle_context_response(update, context, message_text)
            clear_context()
            return

        # No active conversation - check if this is a new URL
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

        # Store URL and content type in user data
        context.user_data['url'] = url
        context.user_data['content_type'] = content_type
        context.user_data['user_comment'] = user_comment
        context.user_data['state'] = AWAITING_CONTEXT

        # Ask user why they sent this URL
        keyboard = [
            [InlineKeyboardButton("Just summarize", callback_data="context:default")],
            [InlineKeyboardButton("Let me explain", callback_data="context:custom")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.effective_message.reply_text(
            "📎 I received your link!\n\n"
            "What would you like to know from this content?",
            reply_markup=reply_markup
        )
        logger.info("url_received", url=url, content_type=content_type)
        clear_context()

    async def _handle_context_response(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user_context: str
    ) -> None:
        """Handle user's response explaining what they want to focus on."""
        url = context.user_data.get('url')
        content_type = context.user_data.get('content_type')
        user_comment = context.user_data.get('user_comment')
        
        if not url or not content_type:
            await update.effective_message.reply_text("⚠️ Session expired. Please send the URL again.")
            context.user_data.clear()
            return

        # Send processing indicator
        processing_msg = await update.effective_message.reply_text(
            "🔄 Processing your link... Please wait."
        )

        await self._process_and_summarize(
            update,
            context,
            url,
            content_type,
            user_comment,
            user_context,
            processing_msg
        )

    async def _process_and_summarize(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        url: str,
        content_type: str,
        user_comment: Optional[str],
        user_context: Optional[str],
        processing_msg,
        pre_extracted_text: Optional[str] = None,
        pre_extracted_title: Optional[str] = None
    ) -> None:
        """Extract content and generate summary."""
        chat_id = update.effective_chat.id
        start_time = time.time()
        error_message: Optional[str] = None
        summary: str = ""
        title: str = ""
        raw_text_length: int = 0

        try:
            # Step 1: Extract content if not already provided
            if pre_extracted_text:
                text = pre_extracted_text
                title = pre_extracted_title or "Unknown"
                logger.info("using_pre_extracted_content", title=title)
            else:
                logger.info("extraction_started", url=url, content_type=content_type)
                text, title, content_type = await self.extractor.extract(url)
            
            raw_text_length = len(text)
            logger.info(
                "extraction_completed",
                title=title,
                text_length=raw_text_length
            )

            # Step 1.5: Check language and ask for translation if needed
            is_content_korean = is_korean(text)
            translate_pref = context.user_data.get('translate_to_korean')
            
            if not is_content_korean and translate_pref is None:
                # Store intermediate state
                context.user_data['extracted_text'] = text
                context.user_data['extracted_title'] = title
                context.user_data['extracted_type'] = content_type
                context.user_data['user_context'] = user_context
                context.user_data['processing_msg_id'] = processing_msg.message_id
                context.user_data['state'] = AWAITING_TRANSLATION
                
                keyboard = [
                    [InlineKeyboardButton("Yes, translate to Korean", callback_data="translate:yes")],
                    [InlineKeyboardButton("No, keep original", callback_data="translate:no")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await processing_msg.edit_text(
                    "🌐 The content is not in Korean. Would you like to translate the summary to Korean?",
                    reply_markup=reply_markup
                )
                return

            # Step 2: Generate summary with optional context
            logger.info("summarization_started", title=title, has_context=bool(user_context))
            translate_to_korean = (translate_pref == "yes") or is_content_korean
            
            summary = self.llm.summarize(
                content=text,
                content_type=content_type,
                title=title,
                max_length=self.config.max_text_length,
                user_context=user_context,
                translate_to_korean=translate_to_korean
            )
            logger.info("summarization_completed")

            # Step 3: Format and send message
            formatted_parts = []
            
            # 3a. Add Quote (User Context/Comment)
            quote_text = user_context if user_context else user_comment
            if quote_text:
                escaped_quote = html.escape(quote_text)
                formatted_parts.append(f"<blockquote>{escaped_quote}</blockquote>")
                formatted_parts.append("")

            # 3b. Add Summary (Convert Markdown-ish to HTML)
            # Escape HTML special characters first
            safe_summary = html.escape(summary)
            # Convert Bold: **text** -> <b>text</b>
            safe_summary = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', safe_summary)
            # Convert Italic: *text* -> <i>text</i>
            safe_summary = re.sub(r'\*(.*?)\*', r'<i>\1</i>', safe_summary)
            # Convert Heading: # [text] -> <b>[\1]</b> (Add space before AI 핵심요약)
            safe_summary = re.sub(r'#\s*\[(.*?)\]', r'\n<b>[\1]</b>', safe_summary)
            
            # The summary from LLM already has spacing handled by _ensure_bullet_spacing
            formatted_parts.append(safe_summary)
            
            # 3c. Add Link
            escaped_url = html.escape(url)
            formatted_parts.append(f"\n원본링크: <a href=\"{escaped_url}\">{escaped_url}</a>")
            
            formatted_message = "\n".join(formatted_parts)
            
            await processing_msg.edit_text(
                formatted_message,
                parse_mode="HTML",
                disable_web_page_preview=False
            )

            # Store summary data for next action
            context.user_data['summary'] = summary
            context.user_data['summary_message_id'] = processing_msg.message_id
            context.user_data['url'] = url
            context.user_data['full_formatted_message'] = formatted_message

            # Ask what to do next
            keyboard = [
                [InlineKeyboardButton("📤 Send to Channel", callback_data="action:send_channel")],
                [InlineKeyboardButton("✅ Finish", callback_data="action:finish")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.effective_message.reply_text(
                "What would you like to do next?",
                reply_markup=reply_markup
            )

        except NoTranscriptError:
            error_message = "No transcript available for this video."
            await processing_msg.edit_text(f"⚠️ {error_message}")
            logger.warning("no_transcript", url=url)
            context.user_data.clear()

        except PDFExtractionError as e:
            error_message = str(e)
            await processing_msg.edit_text(f"⚠️ {error_message}")
            logger.warning("pdf_extraction_failed", url=url, error=error_message)
            context.user_data.clear()

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
            context.user_data.clear()

        except LLMError as e:
            error_message = f"AI error: {str(e)}"
            logger.error("llm_failed", error=error_message)
            await processing_msg.edit_text(
                "⚠️ Failed to generate summary. Please try again later."
            )
            context.user_data.clear()

        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            logger.exception("unexpected_error", error=error_message)
            await processing_msg.edit_text(
                "⚠️ An unexpected error occurred. Please try again."
            )
            context.user_data.clear()

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

    async def _send_to_channel(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """Send summary to configured Telegram channel."""
        summary = context.user_data.get('summary')
        url = context.user_data.get('url')
        formatted_message = context.user_data.get('full_formatted_message')
        
        if not url:
            return False

        try:
            # Get channel ID from config
            channel_id = getattr(self.config, 'telegram_channel_id', None)
            
            if not channel_id:
                await update.callback_query.message.reply_text(
                    "⚠️ Channel not configured. Please set TELEGRAM_CHANNEL_ID in .env file."
                )
                return False
            
            # Format message for channel
            channel_message = formatted_message or f"원본링크: {url}"
            
            # Send to channel
            await context.bot.send_message(
                chat_id=channel_id,
                text=channel_message,
                parse_mode="HTML",
                disable_web_page_preview=False
            )
            
            logger.info("sent_to_channel", channel_id=channel_id, url=url)
            return True
            
        except Exception as e:
            logger.error("send_to_channel_failed", error=str(e))
            await update.callback_query.message.reply_text(
                f"⚠️ Failed to send to channel: {str(e)}"
            )
            return False

    async def handle_callback_query(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle inline keyboard button presses."""
        query = update.callback_query
        await query.answer()
        
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id if update.effective_user else chat_id
        bind_context(chat_id=chat_id, user_id=user_id)

        data = query.data
        
        if data.startswith("context:"):
            action = data.split(":")[1]
            
            if action == "default":
                # User chose "Just summarize" - proceed with no specific context
                await query.edit_message_text(
                    "🔄 Processing your link... Please wait."
                )
                
                url = context.user_data.get('url')
                content_type = context.user_data.get('content_type')
                user_comment = context.user_data.get('user_comment')
                
                if url and content_type:
                    await self._process_and_summarize(
                        update,
                        context,
                        url,
                        content_type,
                        user_comment,
                        None,  # No specific context
                        query.message
                    )
                else:
                    await query.edit_message_text("⚠️ Session expired. Please send the URL again.")
                    context.user_data.clear()
                    
            elif action == "custom":
                # User chose "Let me explain"
                await query.edit_message_text(
                    "💬 Please tell me what you'd like to know from this content:"
                )
                # State remains AWAITING_CONTEXT, waiting for user's text response
                
        elif data.startswith("translate:"):
            pref = data.split(":")[1]
            context.user_data['translate_to_korean'] = pref
            
            # Resume processing
            text = context.user_data.get('extracted_text')
            title = context.user_data.get('extracted_title')
            content_type = context.user_data.get('extracted_type')
            user_context = context.user_data.get('user_context')
            url = context.user_data.get('url')
            user_comment = context.user_data.get('user_comment')
            
            if text and url:
                await query.edit_message_text("🔄 Generating summary... Please wait.")
                
                await self._process_and_summarize(
                    update,
                    context,
                    url,
                    content_type,
                    user_comment,
                    user_context,
                    query.message,
                    pre_extracted_text=text,
                    pre_extracted_title=title
                )
            else:
                await query.edit_message_text("⚠️ Session expired. Please send the URL again.")
                context.user_data.clear()
                
        elif data.startswith("action:"):
            action = data.split(":")[1]
            
            if action == "send_channel":
                # User chose to send to channel
                success = await self._send_to_channel(update, context)
                if success:
                    await query.edit_message_text("✅ Sent to channel!")
                    context.user_data.clear()
                else:
                    # Don't clear user data if sending failed
                    pass
                    
            elif action == "finish":
                # User chose to finish
                await query.edit_message_text("✅ Summary complete!")
                context.user_data.clear()
                
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
        application.add_handler(CallbackQueryHandler(self.handle_callback_query))
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
