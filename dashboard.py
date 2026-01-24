"""
InfoDigest Admin Dashboard - Streamlit Application.
View logs, statistics, and history of processed content.
Includes password authentication for security.
"""

import os
import hashlib
import streamlit as st
from datetime import datetime, timedelta
from typing import Optional

from config import get_config, ConfigurationError
from services.database import DatabaseService, DatabaseError
from models.schemas import DigestLog


# Page configuration
st.set_page_config(
    page_title="InfoDigest Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)


def check_password() -> bool:
    """
    Simple password authentication for the dashboard.

    Returns True if the user is authenticated.
    Password is set via DASHBOARD_PASSWORD environment variable.
    """
    # Get password from environment
    correct_password = os.getenv("DASHBOARD_PASSWORD")

    # If no password is set, show warning but allow access (development mode)
    if not correct_password:
        st.sidebar.warning(
            "⚠️ No DASHBOARD_PASSWORD set. "
            "Set it in your .env file for production use."
        )
        return True

    # Initialize session state
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    # If already authenticated, return True
    if st.session_state.password_correct:
        return True

    # Show login form
    st.markdown("## 🔐 Dashboard Login")
    st.markdown("Please enter the dashboard password to continue.")

    with st.form("login_form"):
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")

        if submit:
            # Hash comparison to prevent timing attacks
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            correct_hash = hashlib.sha256(correct_password.encode()).hexdigest()

            if password_hash == correct_hash:
                st.session_state.password_correct = True
                st.rerun()
            else:
                st.error("❌ Incorrect password. Please try again.")

    return False


def init_database() -> Optional[DatabaseService]:
    """Initialize database connection with error handling."""
    try:
        config = get_config()
        db = DatabaseService(db_path=config.db_path)
        db.connect()
        return db
    except ConfigurationError as e:
        st.error(f"⚠️ Configuration Error: {e}")
        st.info("Please ensure your .env file is properly configured.")
        return None
    except DatabaseError as e:
        st.error(f"⚠️ Database Error: {e}")
        st.info("Please ensure the database file path is accessible.")
        return None


def render_sidebar(db: DatabaseService):
    """Render sidebar with filters and stats."""
    st.sidebar.title("📊 InfoDigest")
    st.sidebar.markdown("---")

    # Logout button
    if os.getenv("DASHBOARD_PASSWORD"):
        if st.sidebar.button("🚪 Logout"):
            st.session_state.password_correct = False
            st.rerun()

    # Statistics
    st.sidebar.subheader("Statistics")
    stats = db.get_stats()

    col1, col2 = st.sidebar.columns(2)
    with col1:
        st.metric("Total Digests", stats["total_digests"])
    with col2:
        st.metric("Success Rate", f"{stats['success_rate']:.1f}%")

    # By content type
    if stats["by_type"]:
        st.sidebar.markdown("**By Type:**")
        for content_type, count in stats["by_type"].items():
            st.sidebar.text(f"• {content_type}: {count}")

    st.sidebar.markdown("---")

    # Filters
    st.sidebar.subheader("Filters")

    content_type_filter = st.sidebar.selectbox(
        "Content Type",
        ["All", "Video", "Article", "Report"],
        index=0
    )

    time_filter = st.sidebar.selectbox(
        "Time Range",
        ["All Time", "Today", "Last 7 Days", "Last 30 Days"],
        index=0
    )

    show_errors = st.sidebar.checkbox("Show only errors", value=False)

    return {
        "content_type": content_type_filter if content_type_filter != "All" else None,
        "time_range": time_filter,
        "errors_only": show_errors
    }


def build_filters(filter_config: dict) -> dict:
    """Build filter dictionary from UI selections."""
    filters = {}

    if filter_config["content_type"]:
        filters["content_type"] = filter_config["content_type"]

    if filter_config["errors_only"]:
        filters["error"] = {"$ne": None}

    if filter_config["time_range"] != "All Time":
        now = datetime.utcnow()
        if filter_config["time_range"] == "Today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif filter_config["time_range"] == "Last 7 Days":
            start = now - timedelta(days=7)
        else:  # Last 30 Days
            start = now - timedelta(days=30)
        filters["timestamp"] = {"$gte": start}

    return filters


def render_log_card(log: DigestLog):
    """Render a single log entry as a card."""
    with st.container():
        # Header
        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            st.markdown(f"### {log.title}")
        with col2:
            type_emoji = {
                "Video": "🎬",
                "Article": "📰",
                "Report": "📄"
            }.get(log.content_type.value, "📄")
            st.markdown(f"**{type_emoji} {log.content_type.value}**")
        with col3:
            st.markdown(f"*{log.timestamp.strftime('%Y-%m-%d %H:%M')}*")

        # URL (truncated for display, masked for privacy)
        url_display = log.url[:80] + "..." if len(log.url) > 80 else log.url
        st.markdown(f"🔗 [{url_display}]({log.url})")

        # User comment if provided
        if log.user_comment:
            st.info(f"💬 **Comment:** {log.user_comment}")

        # Error indicator
        if log.error:
            st.error(f"❌ Error: {log.error}")
        else:
            # Summary in expander
            with st.expander("View Summary", expanded=False):
                st.markdown(log.summary)

            # Metadata
            col1, col2, col3 = st.columns(3)
            with col1:
                st.caption(f"📏 {log.raw_text_length:,} characters")
            with col2:
                if log.processing_time_ms:
                    st.caption(f"⏱️ {log.processing_time_ms}ms")
            with col3:
                if log.chat_id:
                    # Partially mask chat ID for privacy
                    masked_id = f"***{str(log.chat_id)[-4:]}"
                    st.caption(f"💬 Chat: {masked_id}")

        st.markdown("---")


def main():
    """Main dashboard application."""
    # Check authentication first
    if not check_password():
        st.stop()

    st.title("📊 InfoDigest Dashboard")
    st.markdown("View and manage your content digests")
    st.markdown("---")

    # Initialize database
    db = init_database()
    if not db:
        st.stop()

    # Render sidebar and get filters
    filter_config = render_sidebar(db)
    filters = build_filters(filter_config)

    # Main content area
    col1, col2 = st.columns([3, 1])

    with col2:
        # Refresh button
        if st.button("🔄 Refresh"):
            st.rerun()

        # Items per page
        limit = st.selectbox("Show", [10, 25, 50, 100], index=1)

    with col1:
        st.subheader("Recent Digests")

    # Fetch logs
    try:
        logs = db.get_logs(limit=limit, filters=filters)
    except DatabaseError as e:
        st.error(f"Failed to fetch logs: {e}")
        st.stop()

    if not logs:
        st.info("No digests found matching your criteria.")
        st.markdown(
            "Send URLs to your Telegram bot to see them appear here!"
        )
    else:
        for log in logs:
            render_log_card(log)

    # Footer
    st.markdown("---")
    st.caption(
        "InfoDigest Dashboard • "
        f"Database: {db.db_path}"
    )


if __name__ == "__main__":
    main()
