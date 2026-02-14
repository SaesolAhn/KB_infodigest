"""
InfoDigest Telegram Bot - Main Entry Point.
Processes URLs (Web, YouTube, PDF) and replies with AI-generated summaries.
"""

import asyncio
import time
import re
import html
import os
import tempfile
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
from services.stock_info import (
    AsyncStockInfoService,
    StockInfoError,
    StockInfo,
    StockQueryAmbiguousError,
    StockSearchCandidate,
)
from services.pykrx_chart import PykrxChartService
from utils.validators import extract_url_from_text, get_content_type
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
        self.stock_info = AsyncStockInfoService(timeout=self.config.request_timeout)
        self.pykrx_chart = PykrxChartService(default_period_days=31)
        self.llm = LLMService()
        self.db = AsyncDatabaseService(db_path=self.config.db_path)
        self.rate_limiter = RateLimiter(max_requests=5, window_seconds=60)
        self._chart_font_name: Optional[str] = None

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
            "/help - This help message\n"
            "/stock <name|code|url> - Stock snapshot from stock.naver.com\n\n"
            "**Stock example:**\n"
            "`/stock 삼성전자`\n"
            "`/stock 삼성전ㅈ` (typo auto-correct)\n"
            "`/stock 005930`\n"
            "`/stock NVDA.O`\n"
            "`/stock https://stock.naver.com/domestic/stock/005930`\n"
            "`/stock https://stock.naver.com/worldstock/stock/NVDA.O`\n\n"
            "차트: 가격 + 매매동향 차트가 가능하면 함께 전송합니다\n\n"
            "**Note:** YouTube videos must have captions/subtitles available."
        )
        await update.effective_message.reply_text(help_message, parse_mode="Markdown")
        logger.info(
            "command_help",
            chat_id=update.effective_chat.id
        )

    async def stock_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /stock command for stock.naver.com listed stocks."""
        if not update.effective_message:
            return

        chat_id = update.effective_chat.id
        user_id = update.effective_user.id if update.effective_user else chat_id
        bind_context(chat_id=chat_id, user_id=user_id)

        rate_result = self.rate_limiter.acquire(user_id)
        if not rate_result.allowed:
            await update.effective_message.reply_text(
                f"⏳ {rate_result.message}\n"
                f"Remaining requests: {rate_result.remaining}"
            )
            logger.warning("rate_limit_exceeded_stockinfo", reset_in=rate_result.reset_in_seconds)
            clear_context()
            return

        query = " ".join(context.args).strip() if context.args else ""
        if not query:
            await update.effective_message.reply_text(
                "Usage: /stock <stock name | 6-digit code | stock.naver.com URL>\n"
                "Examples: /stock 삼성전자, /stock 005930, /stock NVDA.O"
            )
            clear_context()
            return

        processing_msg = await update.effective_message.reply_text(
            "📈 Fetching stock info... Please wait."
        )

        try:
            stock = await self.stock_info.get_stock_info(query)
            await self._send_stock_response(
                context=context,
                chat_id=chat_id,
                stock=stock,
                status_message=processing_msg,
            )
            logger.info("stockinfo_completed", code=stock.code, name=stock.name)

        except StockQueryAmbiguousError as exc:
            suggestion_keyboard = self._build_stock_suggestion_keyboard(exc.candidates)
            await processing_msg.edit_text(
                f"⚠️ {exc}\n아래 후보 중에서 선택하세요.",
                reply_markup=suggestion_keyboard,
            )
            logger.warning("stockinfo_ambiguous_query", input=query, suggestion_count=len(exc.candidates))
        except ValueError as exc:
            await processing_msg.edit_text(f"⚠️ {exc}")
            logger.warning("stockinfo_invalid_input", input=query, error=str(exc))
        except StockInfoError as exc:
            await processing_msg.edit_text(f"⚠️ Could not fetch stock info: {exc}")
            logger.warning("stockinfo_failed", input=query, error=str(exc))
        except Exception as exc:
            await processing_msg.edit_text("⚠️ Unexpected error while fetching stock info.")
            logger.exception("stockinfo_unexpected_error", input=query, error=str(exc))
        finally:
            clear_context()

    def _format_stock_message(self, stock: StockInfo) -> str:
        """Format stock information for Telegram Markdown output (mobile-first)."""
        md = self._escape_markdown

        if stock.change_direction == "RISING":
            arrow = "🔺"
        elif stock.change_direction == "FALLING":
            arrow = "🔻"
        else:
            direction = self._get_change_direction(stock.change_value, stock.change_rate)
            arrow = "🔺" if direction > 0 else "🔻" if direction < 0 else "⏸️"

        change_parts = []
        if stock.change_value:
            change_parts.append(stock.change_value)
        if stock.change_rate:
            change_parts.append(f"({stock.change_rate})")
        change_text = " ".join(change_parts) if change_parts else "-"

        cur_suffix = f" {stock.currency}" if stock.currency and stock.currency != "KRW" else ""

        name_display = stock.name
        if stock.name_eng and stock.name_eng != stock.name:
            name_display = f"{stock.name} ({stock.name_eng})"

        meta_parts = [md(stock.code)]
        if stock.market:
            meta_parts.append(md(stock.market))
        if stock.industry:
            meta_parts.append(md(stock.industry))

        lines = [
            f"*{md(name_display)}*",
            " · ".join(meta_parts),
            "",
            f"*현재가* {md(stock.current_price or '-')}{md(cur_suffix)} {arrow} {md(change_text)}",
        ]

        day_parts = []
        if stock.prev_close:
            day_parts.append(f"전일 {md(stock.prev_close)}")
        if stock.open_price:
            day_parts.append(f"시가 {md(stock.open_price)}")
        if stock.high_price:
            day_parts.append(f"고가 {md(stock.high_price)}")
        if stock.low_price:
            day_parts.append(f"저가 {md(stock.low_price)}")
        if day_parts:
            lines.append(f"• {' / '.join(day_parts)}")

        lines.append("")
        lines.append("📌 *핵심*")

        if stock.market_cap:
            lines.append(f"• 시가총액 {md(stock.market_cap)}")

        trade_parts = []
        if stock.volume:
            trade_parts.append(f"거래량 {md(stock.volume)}")
        if stock.trading_value:
            trade_parts.append(f"거래대금 {md(stock.trading_value)}")
        if trade_parts:
            lines.append(f"• {' · '.join(trade_parts)}")

        if stock.foreign_rate:
            lines.append(f"• 외인소진율 {md(stock.foreign_rate)}")

        if stock.low_52w or stock.high_52w:
            lines.append(f"• 52주 {md(stock.low_52w or '-')} ~ {md(stock.high_52w or '-')}")

        valuation_lines: list[str] = []
        per_value = stock.estimated_per or stock.per
        eps_value = stock.estimated_eps or stock.eps
        if per_value or stock.pbr:
            part = []
            if per_value:
                part.append(f"PER {md(per_value)}")
            if stock.pbr:
                part.append(f"PBR {md(stock.pbr)}")
            valuation_lines.append(" · ".join(part))
        if eps_value or stock.bps:
            part = []
            if eps_value:
                part.append(f"EPS {md(eps_value)}")
            if stock.bps:
                part.append(f"BPS {md(stock.bps)}")
            valuation_lines.append(" · ".join(part))
        if stock.dividend_yield or stock.dividend_per_share:
            part = []
            if stock.dividend_yield:
                part.append(f"배당수익률 {md(stock.dividend_yield)}")
            if stock.dividend_per_share:
                part.append(f"주당배당금 {md(stock.dividend_per_share)}")
            valuation_lines.append(" · ".join(part))
        if stock.target_price or stock.analyst_rating:
            part = []
            if stock.target_price:
                part.append(f"목표가 {md(stock.target_price)}")
            if stock.analyst_rating:
                part.append(f"투자의견 {md(stock.analyst_rating)}")
            valuation_lines.append(" · ".join(part))

        if valuation_lines:
            lines.append("")
            lines.append("📐 *지표*")
            for val_line in valuation_lines:
                lines.append(f"• {val_line}")

        flow_line = self._build_inflow_breakdown_line(stock.deal_trends)
        if flow_line:
            lines.append("")
            lines.append("🧭 *수급(최근)*")
            lines.append(f"• {md(flow_line)}")

        news_lines = self._build_recent_item_lines(stock.recent_news)
        if news_lines:
            lines.append("")
            lines.append("📰 *최근 뉴스*")
            lines.extend(news_lines)

        report_lines = self._build_recent_item_lines(stock.recent_reports)
        if report_lines:
            lines.append("")
            lines.append("📑 *최근 리포트*")
            lines.extend(report_lines)

        lines.append("")
        if stock.as_of:
            lines.append(f"기준: {md(stock.as_of)}")
        if stock.search_note:
            lines.append(f"검색 보정: {md(stock.search_note)}")
        if stock.source_url:
            lines.append(f"출처: {md(stock.source_url)}")

        return "\n".join(lines)

    def _build_inflow_breakdown_line(self, deal_trends: Optional[list[dict[str, str]]]) -> Optional[str]:
        """Build latest investor inflow breakdown line in 개인/기관/외국인 order."""
        if not deal_trends:
            return None

        latest: Optional[dict[str, str]] = None
        latest_key = ""

        for trend in deal_trends:
            if not isinstance(trend, dict):
                continue

            date_raw = str(trend.get("date") or "").strip()
            date_digits = re.sub(r"[^0-9]", "", date_raw)
            date_key = date_digits if len(date_digits) >= 8 else ""

            if latest is None:
                latest = trend
                latest_key = date_key
                continue

            # Prefer date-aware max; fallback keeps the first valid row.
            if date_key and (not latest_key or date_key > latest_key):
                latest = trend
                latest_key = date_key

        if latest is None:
            return None

        date_raw = str(latest.get("date") or "").strip()
        date_digits = re.sub(r"[^0-9]", "", date_raw)
        if len(date_digits) >= 8:
            date_fmt = f"{date_digits[4:6]}/{date_digits[6:8]}"
        else:
            date_fmt = date_raw or "-"

        indiv = str(latest.get("individual") or "-")
        inst = str(latest.get("institution") or "-")
        foreign = str(latest.get("foreign") or "-")
        return f"{date_fmt} 개인 {indiv} · 기관 {inst} · 외국인 {foreign}"

    def _build_recent_item_lines(
        self,
        items: Optional[list[dict[str, str]]],
        limit: int = 3,
    ) -> list[str]:
        """Render compact recent news/report lines for markdown output."""
        if not items:
            return []

        lines: list[str] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue

            title = self._shorten_text(str(item.get("title") or "-"), max_len=56)
            source = str(item.get("source") or "").strip()
            raw_date = str(item.get("date") or "").strip()

            meta_parts = []
            date_fmt = self._format_short_date(raw_date)
            if source:
                meta_parts.append(self._escape_markdown(source))
            if date_fmt:
                meta_parts.append(self._escape_markdown(date_fmt))

            suffix = f" ({' · '.join(meta_parts)})" if meta_parts else ""
            lines.append(f"• {self._escape_markdown(title)}{suffix}")

        return lines

    def _escape_markdown(self, text: str) -> str:
        """Escape markdown-special characters for Telegram Markdown mode."""
        value = str(text or "")
        for ch in ("\\", "`", "*", "_", "[", "]", "(", ")"):
            value = value.replace(ch, f"\\{ch}")
        return value

    def _shorten_text(self, text: str, max_len: int = 60) -> str:
        """Shorten text for compact mobile message layout."""
        value = str(text or "").strip()
        if len(value) <= max_len:
            return value
        return value[: max_len - 1].rstrip() + "…"

    def _format_short_date(self, raw: str) -> str:
        """Format raw date as MM/DD when possible."""
        digits = re.sub(r"[^0-9]", "", str(raw or ""))
        if len(digits) >= 8:
            return f"{digits[4:6]}/{digits[6:8]}"
        return raw

    async def _send_stock_response(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        stock: StockInfo,
        status_message=None,
    ) -> None:
        """Send stock message with optional chart attachment."""
        message = self._format_stock_message(stock)
        chart_path = self._create_stock_chart_image(stock)

        # Text-only fallback
        if not chart_path:
            if status_message:
                await status_message.edit_text(
                    message,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            return

        try:
            # Remove status message first so chart+caption is the main response.
            if status_message:
                try:
                    await status_message.delete()
                except Exception:
                    pass

            if len(message) > 1024:
                with open(chart_path, "rb") as chart_file:
                    await context.bot.send_photo(chat_id=chat_id, photo=chart_file)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
            else:
                with open(chart_path, "rb") as chart_file:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=chart_file,
                        caption=message,
                        parse_mode="Markdown",
                    )
        finally:
            try:
                os.remove(chart_path)
            except OSError:
                pass

    def _create_stock_chart_image(self, stock: StockInfo) -> Optional[str]:
        """Render price + deal trend charts as a PNG image and return path."""
        chart = stock.chart_data
        use_pykrx_chart = self._should_use_pykrx_chart(stock)
        if use_pykrx_chart:
            try:
                trend_labels = chart.trend_labels if chart and chart.has_trend() else None
                personal_series = chart.personal_series if chart and chart.has_trend() else None
                institution_series = chart.institution_series if chart and chart.has_trend() else None
                foreign_series = chart.foreign_series if chart and chart.has_trend() else None

                pykrx_chart = self.pykrx_chart.generate_candlestick_with_volume(
                    code=stock.code,
                    title=stock.name,
                    period_days=31,
                    font_name=self._chart_font_name,
                    trend_labels=trend_labels,
                    personal_series=personal_series,
                    institution_series=institution_series,
                    foreign_series=foreign_series,
                )
                if pykrx_chart:
                    return pykrx_chart
            except Exception as exc:
                logger.warning("pykrx_chart_generation_failed", code=stock.code, error=str(exc))
            return None

        if not chart or not chart.has_any():
            return None

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from matplotlib import font_manager
        except Exception as exc:
            logger.warning("stock_chart_backend_unavailable", error=str(exc))
            return None

        self._configure_chart_style(plt, font_manager)

        plot_count = int(chart.has_price()) + int(chart.has_trend())
        if plot_count == 0:
            return None

        fig, axes = plt.subplots(
            nrows=plot_count,
            ncols=1,
            figsize=(10, 6 if plot_count == 2 else 4),
            constrained_layout=False,
        )
        if plot_count == 1:
            axes = [axes]

        axis_index = 0

        if chart.has_price():
            ax = axes[axis_index]
            axis_index += 1
            x = list(range(len(chart.price_series)))
            ax.plot(
                x,
                chart.price_series,
                color="#1A1A1A",
                linewidth=2.0,
                marker="o",
                markersize=3,
                markerfacecolor="#E3120B",
                markeredgewidth=0,
            )
            ax.set_title("Price (1M)", fontsize=11, loc="left", fontweight="bold", color="#1A1A1A")
            ax.grid(False)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["left"].set_color("#7D7D7D")
            ax.spines["bottom"].set_color("#7D7D7D")
            ax.spines["left"].set_linewidth(1.0)
            ax.spines["bottom"].set_linewidth(1.0)
            ax.tick_params(axis="both", colors="#2E2E2E", width=0.9, length=4, labelsize=8.5)
            self._apply_xtick_labels(ax, x, chart.price_labels)

        if chart.has_trend():
            ax = axes[axis_index]
            x = list(range(len(chart.trend_labels)))
            ax.axhline(0, color="#888888", linewidth=1, alpha=0.65)

            if len(chart.personal_series) == len(x):
                ax.plot(x, chart.personal_series, label="개인", color="#E3120B", linewidth=1.7)
            if len(chart.foreign_series) == len(x):
                ax.plot(x, chart.foreign_series, label="외국인", color="#005689", linewidth=1.7)
            if len(chart.institution_series) == len(x):
                ax.plot(x, chart.institution_series, label="기관", color="#767676", linewidth=1.7)

            ax.set_title("매매동향 (1M)", fontsize=11, loc="left", fontweight="bold", color="#1A1A1A")
            ax.grid(alpha=0.2, color="#E0E0E0", linewidth=0.7)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["left"].set_color("#7D7D7D")
            ax.spines["bottom"].set_color("#7D7D7D")
            ax.spines["left"].set_linewidth(1.0)
            ax.spines["bottom"].set_linewidth(1.0)
            ax.tick_params(axis="both", colors="#2E2E2E", width=0.9, length=4, labelsize=8.5)
            ax.legend(fontsize=9, loc="best")
            self._apply_xtick_labels(ax, x, chart.trend_labels)

        fig.patch.set_facecolor("#FAFAFA")
        fig.suptitle(
            f"{stock.name} ({stock.code})",
            fontsize=13,
            fontweight="bold",
            x=0.02,
            y=0.91,
            ha="left",
            color="#1A1A1A",
        )
        fig.text(0.02, 0.955, "THE STOCK BRIEFING", fontsize=8.5, color="#E3120B", weight="bold")
        fig.add_artist(
            plt.Line2D(
                [0.02, 0.18],
                [0.948, 0.948],
                transform=fig.transFigure,
                color="#E3120B",
                linewidth=2.2,
            )
        )
        fig.subplots_adjust(top=0.79, bottom=0.14, left=0.08, right=0.98, hspace=0.36)
        fig.text(0.98, 0.02, "Source: stock.naver.com", ha="right", fontsize=7.5, color="#777777")

        tmp_file = tempfile.NamedTemporaryFile(
            suffix=".png",
            prefix="stock_chart_",
            delete=False,
        )
        tmp_path = tmp_file.name
        tmp_file.close()

        fig.savefig(tmp_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return tmp_path

    def _should_use_pykrx_chart(self, stock: StockInfo) -> bool:
        """Use pykrx chart for all domestic stock codes."""
        return re.fullmatch(r"\d{6}", stock.code or "") is not None

    def _configure_chart_style(self, plt, font_manager) -> None:
        """Set Economist-like plotting style and Korean-capable font fallback."""
        if self._chart_font_name is None:
            candidate_fonts = [
                "Apple SD Gothic Neo",
                "AppleGothic",
                "NanumGothic",
                "NanumSquare",
                "Noto Sans CJK KR",
                "Noto Sans KR",
                "Malgun Gothic",
                "Arial Unicode MS",
                "DejaVu Sans",
            ]
            installed = {font.name for font in font_manager.fontManager.ttflist}
            self._chart_font_name = next(
                (font_name for font_name in candidate_fonts if font_name in installed),
                "DejaVu Sans",
            )

            if self._chart_font_name == "DejaVu Sans":
                logger.warning("stock_chart_korean_font_fallback", font=self._chart_font_name)

        plt.rcParams["font.family"] = self._chart_font_name
        plt.rcParams["axes.unicode_minus"] = False
        plt.rcParams["figure.facecolor"] = "#FAFAFA"
        plt.rcParams["axes.facecolor"] = "#FAFAFA"

    def _apply_xtick_labels(self, ax, x_values: list[int], labels: list[str]) -> None:
        """Apply sparse x-axis labels for readability."""
        if not x_values or not labels or len(labels) != len(x_values):
            return

        step = max(1, len(labels) // 6)
        tick_positions = x_values[::step]
        tick_labels = labels[::step]

        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=35, ha="right", fontsize=8)

    def _build_stock_suggestion_keyboard(
        self,
        candidates: list[StockSearchCandidate]
    ) -> InlineKeyboardMarkup:
        """Build inline keyboard for ambiguous stock query candidates."""
        keyboard = []
        for candidate in candidates[:3]:
            market_suffix = f" · {candidate.market}" if candidate.market else ""
            label = f"{candidate.name} ({candidate.code}){market_suffix}"
            # Use reuters_code if available (for world stocks)
            pick_code = candidate.reuters_code or candidate.code
            keyboard.append(
                [InlineKeyboardButton(label, callback_data=f"stockpick:{pick_code}")]
            )

        keyboard.append([InlineKeyboardButton("취소", callback_data="stockpick:cancel")])
        return InlineKeyboardMarkup(keyboard)

    def _get_change_direction(
        self,
        change_value: Optional[str],
        change_rate: Optional[str]
    ) -> int:
        """Return +1 / 0 / -1 based on change value or rate sign."""
        for raw in (change_value, change_rate):
            if not raw:
                continue
            text = raw.strip()
            if text.startswith("+"):
                return 1
            if text.startswith("-"):
                return -1
        return 0

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
        url = extract_url_from_text(message_text)
        if not url:
            clear_context()
            return  # Silently ignore messages without URLs

        user_comment = None
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
        user_id = update.effective_user.id if update.effective_user else chat_id
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
            
            prompt_msg = await update.effective_message.reply_text(
                "What would you like to do next?",
                reply_markup=reply_markup
            )

            # Schedule auto-finish job
            if context.job_queue:
                # Cancel existing jobs for this user if any (shouldn't happen with current flow but good practice)
                current_jobs = context.job_queue.get_jobs_by_name(f"auto_finish_{chat_id}")
                for job in current_jobs:
                    job.schedule_removal()

                context.job_queue.run_once(
                    self._auto_finish_job,
                    when=60, # 1 minute
                    chat_id=chat_id,
                    user_id=user_id,
                    data={
                        "prompt_message_id": prompt_msg.message_id,
                        "summary_message_id": processing_msg.message_id
                    },
                    name=f"auto_finish_{chat_id}"
                )
                logger.info("auto_finish_scheduled", chat_id=chat_id, delay=60)

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

    async def _auto_finish_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Automatically finish the session after timeout."""
        job = context.job
        chat_id = job.chat_id
        prompt_message_id = job.data.get("prompt_message_id")
        
        bind_context(chat_id=chat_id)
        logger.info("auto_finish_triggered", chat_id=chat_id)
        
        try:
            # Edit the prompt message to show it was auto-finished
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=prompt_message_id,
                text="✅ Summary complete! (Auto-finished)"
            )
            
            # Clear user data
            # Note: We need to access user_data specifically for the user in this chat
            # context.user_data in a job refers to the user_data of the user_id passed to run_once
            context.user_data.clear()
            logger.info("session_auto_finished", chat_id=chat_id)
            
        except Exception as e:
            logger.error("auto_finish_job_failed", error=str(e))
        finally:
            clear_context()

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
        
        # Cancel any pending auto-finish job for this user
        if context.job_queue:
            current_jobs = context.job_queue.get_jobs_by_name(f"auto_finish_{chat_id}")
            for job in current_jobs:
                job.schedule_removal()
            if current_jobs:
                logger.debug("auto_finish_job_cancelled", chat_id=chat_id)

        if data.startswith("stockpick:"):
            choice = data.split(":", 1)[1]

            if choice == "cancel":
                await query.edit_message_text("✅ Stock selection cancelled.")
                clear_context()
                return

            await query.edit_message_text("📈 Fetching stock info... Please wait.")

            try:
                stock = await self.stock_info.get_stock_info(choice)
                await self._send_stock_response(
                    context=context,
                    chat_id=chat_id,
                    stock=stock,
                    status_message=query.message,
                )
                logger.info("stockinfo_selected_candidate", code=choice, name=stock.name)
            except Exception as exc:
                logger.warning("stockinfo_candidate_fetch_failed", code=choice, error=str(exc))
                await query.edit_message_text(
                    "⚠️ Failed to fetch selected stock info. Please try /stock again."
                )
            clear_context()
            return

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
        await self.stock_info.close()
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
        application.add_handler(CommandHandler("stock", self.stock_command))
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
