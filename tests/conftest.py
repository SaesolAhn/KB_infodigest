"""
Pytest configuration and shared fixtures for InfoDigest Bot tests.
"""

import os
import tempfile
import pytest
import asyncio


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_db_path():
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def sample_urls():
    """Sample URLs for testing."""
    return {
        "youtube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "youtube_short": "https://youtu.be/dQw4w9WgXcQ",
        "youtube_shorts": "https://www.youtube.com/shorts/abc123def",
        "pdf": "https://example.com/document.pdf",
        "web": "https://example.com/article",
        "invalid": "not-a-url",
    }


@pytest.fixture
def sample_html():
    """Sample HTML content for testing."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Article | Example Site</title>
        <meta property="og:title" content="Test Article OG Title">
    </head>
    <body>
        <article>
            <h1>Test Article Title</h1>
            <p>This is a test article with enough content to pass the minimum
            threshold for content extraction. It contains multiple sentences
            and paragraphs to simulate real content.</p>
            <p>The content extraction should be able to pull this text and
            create a meaningful summary from it.</p>
        </article>
    </body>
    </html>
    """


@pytest.fixture
def sample_transcript():
    """Sample YouTube transcript data for testing."""
    return [
        {"text": "Hello and welcome to this video.", "start": 0.0, "duration": 2.5},
        {"text": "Today we will be discussing something interesting.", "start": 2.5, "duration": 3.0},
        {"text": "Let's get started with the main content.", "start": 5.5, "duration": 2.0},
    ]
