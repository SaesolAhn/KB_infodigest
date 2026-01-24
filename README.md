# InfoDigest

InfoDigest is a Telegram bot that summarizes web articles, YouTube videos, and PDFs into structured, eye-catching digests using AI. It includes a Streamlit admin dashboard for reviewing past summaries.

## Features

- **Telegram Bot** - Send URLs and receive concise AI-generated summaries
- **Multi-source Support** - Web articles, YouTube videos (with captions), PDF documents
- **AI Provider Flexibility** - Supports Qwen and OpenAI (easily switchable)
- **SQLite Database** - Lightweight, serverless storage for all digests
- **Admin Dashboard** - Streamlit-based UI with filtering and statistics
- **Rate Limiting** - Per-user request throttling (5 requests/minute)
- **Async Architecture** - Non-blocking I/O for better performance
- **Structured Logging** - JSON-capable logging for production monitoring
- **Retry Logic** - Automatic retries with exponential backoff for API calls

## Project Structure

```
KB_infodigest/
├── bot.py                    # Main Telegram bot entry point
├── config.py                 # Configuration management
├── ai_client.py              # AI provider abstraction (Qwen/OpenAI)
├── dashboard.py              # Streamlit admin dashboard
├── services/
│   ├── extractor.py          # Sync content extraction
│   ├── async_extractor.py    # Async content extraction
│   ├── database.py           # Sync SQLite operations
│   ├── async_database.py     # Async SQLite operations
│   └── llm.py                # AI summarization service
├── models/
│   └── schemas.py            # Data models (DigestLog, ContentType)
├── utils/
│   ├── validators.py         # URL validation & content detection
│   ├── rate_limiter.py       # Per-user rate limiting
│   └── logging_config.py     # Structured logging setup
├── tests/                    # Test suite
│   ├── test_validators.py
│   ├── test_rate_limiter.py
│   ├── test_database.py
│   └── test_schemas.py
├── data/                     # SQLite database (auto-created)
├── requirements.txt
└── .env.example
```

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Required settings:
- `TELEGRAM_BOT_TOKEN` - Your Telegram bot token from @BotFather
- `AI_PROVIDER` - Choose `qwen` or `openai`
- API key for your chosen provider (`QWEN_API_KEY` or `OPENAI_API_KEY`)

Optional settings:
- `DASHBOARD_PASSWORD` - Password for admin dashboard (recommended for production)
- `DB_PATH` - Custom database location (default: `data/infodigest.db`)

### 3. Start the Bot

```bash
python bot.py
```

### 4. Start the Dashboard (Optional)

```bash
streamlit run dashboard.py
```

## Usage

### Telegram Bot

1. Start a chat with your bot
2. Send `/start` to see the welcome message
3. Send any URL (article, YouTube video, or PDF)
4. Optionally add a comment before or after the URL
5. Receive a formatted summary with:
   - Eye-catching title
   - Core summary (1 sentence)
   - Key points (3 bullets)
   - Source link

**Example:**
```
This looks interesting https://example.com/article
```

### Admin Dashboard

Access the dashboard at `http://localhost:8501` after running `streamlit run dashboard.py`.

Features:
- View all processed digests
- Filter by content type, time range, or errors
- See statistics (total digests, success rate, by type)
- Expandable summaries with metadata

## Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | - | Telegram bot token |
| `AI_PROVIDER` | Yes | - | `qwen` or `openai` |
| `QWEN_API_KEY` | If qwen | - | Qwen API key |
| `QWEN_MODEL` | If qwen | - | e.g., `qwen-flash`, `qwen-plus` |
| `OPENAI_API_KEY` | If openai | - | OpenAI API key |
| `OPENAI_MODEL` | If openai | - | e.g., `gpt-4o-mini`, `gpt-4` |
| `AI_TEMPERATURE` | No | `0.3` | Generation temperature |
| `DB_PATH` | No | `data/infodigest.db` | SQLite database path |
| `MAX_TEXT_LENGTH` | No | `100000` | Max chars to process |
| `REQUEST_TIMEOUT` | No | `30` | HTTP timeout (seconds) |
| `DASHBOARD_PASSWORD` | No | - | Dashboard login password |

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_validators.py
```

## Architecture Highlights

### Async Support
The bot uses async/await throughout for non-blocking I/O:
- `AsyncContentExtractor` - Async HTTP requests for content fetching
- `AsyncDatabaseService` - Async SQLite operations via `aiosqlite`
- Thread pools for CPU-bound tasks (PDF parsing, HTML extraction)

### Rate Limiting
Built-in rate limiter prevents abuse:
- 5 requests per user per 60 seconds
- Automatic window expiration
- Informative error messages with reset time

### Retry Logic
AI API calls include automatic retry:
- 3 attempts with exponential backoff (2s, 4s, 8s)
- Handles transient network failures gracefully

### Structured Logging
Production-ready logging with `structlog`:
- JSON output for log aggregation
- Context binding for request tracing
- Configurable log levels

## Notes

- YouTube summaries require captions/subtitles to be available
- PDF extraction works for text-based PDFs (OCR not supported)
- API keys should not be quoted in the `.env` file
- The database file is auto-created on first run

## License

MIT
