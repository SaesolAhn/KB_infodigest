# InfoDigest

InfoDigest is a Telegram bot that summarizes web articles, YouTube videos, and
PDFs into a structured digest. It also includes a Streamlit dashboard for
reviewing past summaries.

## Features
- Telegram bot that accepts URLs and returns structured summaries
- Supports web pages, YouTube videos (with captions), and PDF documents
- Provider-agnostic AI client (Qwen or OpenAI via `ai_client.py`)
- MongoDB logging with an admin dashboard

## Setup
1. Install dependencies:

   pip install -r requirements.txt

2. Create a `.env` file with the required settings:

   TELEGRAM_BOT_TOKEN=your-telegram-bot-token
   MONGODB_URI=mongodb://localhost:27017
   MONGODB_DATABASE=infodigest
   MONGODB_COLLECTION=digest_logs
   MAX_TEXT_LENGTH=100000
   REQUEST_TIMEOUT=30

   # AI provider selection
   AI_PROVIDER=qwen   # or openai
   AI_TEMPERATURE=0.3

   # Qwen provider settings (if AI_PROVIDER=qwen)
   QWEN_API_KEY=your-qwen-key
   QWEN_MODEL=qwen-flash
   QWEN_API_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode

   # OpenAI provider settings (if AI_PROVIDER=openai)
   OPENAI_API_KEY=your-openai-key
   OPENAI_MODEL=gpt-4o-mini
   OPENAI_API_BASE_URL=https://api.openai.com

3. Start the bot:

   python bot.py

4. Start the dashboard (optional):

   streamlit run dashboard.py

## Usage
- Send a URL to the Telegram bot and wait for a summary.
- The bot logs each request to MongoDB for later review in the dashboard.

## Notes
- YouTube summaries require captions to be available.
- If your keys are quoted in `.env`, remove the quotes for Qwen/OpenAI keys.
