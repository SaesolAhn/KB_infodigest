# Repository Guidelines

## Project Structure & Module Organization
Core runtime files live at the repository root: `bot.py` (Telegram entrypoint), `dashboard.py` (Streamlit UI), `config.py`, and `ai_client.py`. Domain logic is organized by package:
- `services/`: extraction, AI summarization, and SQLite data access (sync + async variants)
- `models/`: shared schemas and enums
- `utils/`: validators, rate limiting, and logging helpers
- `tests/`: pytest suite mirroring module behavior (`test_*.py`)
- `data/`: runtime SQLite file (`infodigest.db`)

## Build, Test, and Development Commands
- `python -m venv venv && source venv/bin/activate`: create/use local virtualenv
- `pip install -r requirements.txt`: install dependencies
- `cp env.example .env`: initialize local configuration
- `python bot.py`: run the Telegram bot locally
- `streamlit run dashboard.py`: launch admin dashboard at `http://localhost:8501`
- `pytest`: run all tests
- `pytest --cov=. --cov-report=html`: generate coverage report in `htmlcov/`

## Coding Style & Naming Conventions
Follow existing Python style in this repo:
- 4-space indentation, PEP 8 spacing, and type hints for public functions
- `snake_case` for modules/functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants
- Keep functions focused; place cross-cutting helpers in `utils/` instead of duplicating logic
No formatter/linter config is committed yet; keep changes consistent with surrounding code.

## Testing Guidelines
Use `pytest` with settings in `pytest.ini` (`testpaths = tests`, `python_files = test_*.py`, async mode auto).
- Add or update tests for every behavior change
- Name tests clearly by behavior, e.g., `test_extract_url_from_text_handles_pdf_links`
- For async services, prefer async tests over sync wrappers

## Commit & Pull Request Guidelines
Recent history mixes conventional and imperative subjects. Prefer:
- `type: short imperative summary` (e.g., `feat: add async PDF retry handling`)
- Keep subject lines concise (about 72 chars or fewer)

For PRs, include:
- what changed and why
- test evidence (`pytest` output or coverage delta)
- config/env impacts (new variables, migrations)
- screenshots when changing `dashboard.py` UI

## Security & Configuration Tips
Never commit secrets from `.env`. Treat `data/infodigest.db` as local runtime state unless a change explicitly requires fixture data.
