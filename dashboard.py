"""
InfoDigest Admin Dashboard - Streamlit Application.
View cached summaries and statistics.
"""

import streamlit as st
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import json

from config import get_config, ConfigurationError
from services.cache import CacheService, CacheError


# Page configuration
st.set_page_config(
    page_title="InfoDigest Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)


def init_cache() -> Optional[CacheService]:
    """Initialize cache service with error handling."""
    try:
        config = get_config()
        cache = CacheService(
            cache_dir=config.cache_dir,
            default_ttl_days=config.cache_ttl_days
        )
        return cache
    except ConfigurationError as e:
        st.error(f"⚠️ Configuration Error: {e}")
        st.info("Please ensure your .env file is properly configured.")
        return None
    except Exception as e:
        st.error(f"⚠️ Cache Error: {e}")
        return None


def load_all_cache_entries(cache: CacheService) -> List[Dict[str, Any]]:
    """Load all entries from cache directory."""
    entries = []
    cache_dir = Path(cache.cache_dir)
    
    for cache_file in cache_dir.glob("*.json"):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                entries.append(data)
        except Exception:
            continue
    
    # Sort by cached_at timestamp (newest first)
    entries.sort(
        key=lambda x: x.get('cached_at', ''),
        reverse=True
    )
    return entries


def render_sidebar(cache: CacheService, entries: List[Dict[str, Any]]):
    """Render sidebar with filters and stats."""
    st.sidebar.title("📊 InfoDigest")
    st.sidebar.markdown("---")
    
    # Statistics
    st.sidebar.subheader("Statistics")
    stats = cache.get_stats()
    
    col1, col2 = st.sidebar.columns(2)
    with col1:
        st.metric("Total Cached", len(entries))
    with col2:
        st.metric("Cache Size", f"{stats['total_size_mb']} MB")
    
    # By content type
    type_counts = {}
    for entry in entries:
        content_type = entry.get('content_type', 'Unknown')
        type_counts[content_type] = type_counts.get(content_type, 0) + 1
    
    if type_counts:
        st.sidebar.markdown("**By Type:**")
        for content_type, count in sorted(type_counts.items()):
            st.sidebar.text(f"• {content_type}: {count}")
    
    st.sidebar.markdown("---")
    
    # Filters
    st.sidebar.subheader("Filters")
    
    content_type_filter = st.sidebar.selectbox(
        "Content Type",
        ["All", "Video", "Article", "Report", "web", "youtube", "pdf"],
        index=0
    )
    
    time_filter = st.sidebar.selectbox(
        "Time Range",
        ["All Time", "Today", "Last 7 Days", "Last 30 Days"],
        index=0
    )
    
    return {
        "content_type": content_type_filter if content_type_filter != "All" else None,
        "time_range": time_filter,
    }


def filter_entries(
    entries: List[Dict[str, Any]],
    filter_config: dict
) -> List[Dict[str, Any]]:
    """Filter cache entries based on UI selections."""
    filtered = entries
    
    # Filter by content type
    if filter_config["content_type"]:
        filtered = [
            e for e in filtered
            if e.get('content_type', '').lower() == filter_config["content_type"].lower()
        ]
    
    # Filter by time range
    if filter_config["time_range"] != "All Time":
        now = datetime.utcnow()
        if filter_config["time_range"] == "Today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif filter_config["time_range"] == "Last 7 Days":
            start = now - timedelta(days=7)
        else:  # Last 30 Days
            start = now - timedelta(days=30)
        
        filtered = [
            e for e in filtered
            if 'cached_at' in e
        ]
        filtered = [
            e for e in filtered
            if datetime.fromisoformat(e['cached_at']) >= start
        ]
    
    return filtered


def render_cache_card(entry: Dict[str, Any]):
    """Render a single cache entry as a card."""
    with st.container():
        # Header
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col1:
            title = entry.get('title', 'Unknown')
            st.markdown(f"### {title}")
        with col2:
            content_type = entry.get('content_type', 'Unknown')
            type_emoji = {
                "Video": "🎬",
                "Article": "📰",
                "Report": "📄",
                "youtube": "🎬",
                "web": "📰",
                "pdf": "📄"
            }.get(content_type, "📄")
            st.markdown(f"**{type_emoji} {content_type}**")
        with col3:
            if 'cached_at' in entry:
                try:
                    cached_at = datetime.fromisoformat(entry['cached_at'])
                    st.markdown(f"*{cached_at.strftime('%Y-%m-%d %H:%M')}*")
                except Exception:
                    st.markdown("*Unknown*")
            else:
                st.markdown("*Unknown*")
        
        # URL
        url = entry.get('url', '')
        if url:
            st.markdown(f"🔗 [{url}]({url})")
        
        # Summary in expander
        summary = entry.get('summary', '')
        if summary:
            with st.expander("View Summary", expanded=False):
                st.markdown(summary)
        
        # Metadata
        col1, col2, col3 = st.columns(3)
        with col1:
            if 'raw_text_length' in entry:
                st.caption(f"📏 {entry['raw_text_length']:,} characters")
        with col2:
            if 'processing_time_ms' in entry:
                st.caption(f"⏱️ {entry['processing_time_ms']}ms")
        with col3:
            if 'cached_at' in entry:
                try:
                    cached_at = datetime.fromisoformat(entry['cached_at'])
                    age = datetime.utcnow() - cached_at
                    if age.days > 0:
                        st.caption(f"🕐 {age.days} days ago")
                    elif age.seconds > 3600:
                        st.caption(f"🕐 {age.seconds // 3600} hours ago")
                    else:
                        st.caption(f"🕐 {age.seconds // 60} minutes ago")
                except Exception:
                    pass
        
        st.markdown("---")


def main():
    """Main dashboard application."""
    st.title("📊 InfoDigest Dashboard")
    st.markdown("View your cached content digests")
    st.markdown("---")
    
    # Initialize cache
    cache = init_cache()
    if not cache:
        st.stop()
    
    # Load all cache entries
    try:
        all_entries = load_all_cache_entries(cache)
    except Exception as e:
        st.error(f"Failed to load cache entries: {e}")
        st.stop()
    
    # Render sidebar and get filters
    filter_config = render_sidebar(cache, all_entries)
    filtered_entries = filter_entries(all_entries, filter_config)
    
    # Main content area
    col1, col2 = st.columns([3, 1])
    
    with col2:
        # Refresh button
        if st.button("🔄 Refresh"):
            st.rerun()
        
        # Items per page
        limit = st.selectbox("Show", [10, 25, 50, 100], index=1)
        
        # Clear cache button
        if st.button("🗑️ Clear Cache", type="secondary"):
            if st.session_state.get('confirm_clear', False):
                try:
                    deleted = cache.clear()
                    st.success(f"Cleared {deleted} cache entries")
                    st.session_state['confirm_clear'] = False
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to clear cache: {e}")
            else:
                st.session_state['confirm_clear'] = True
                st.warning("Click again to confirm clearing all cache")
    
    with col1:
        st.subheader(f"Cached Digests ({len(filtered_entries)} total)")
    
    # Display entries
    if not filtered_entries:
        st.info("No cached digests found matching your criteria.")
        st.markdown(
            "Send URLs to your Telegram bot to see them appear here!"
        )
    else:
        # Apply limit
        display_entries = filtered_entries[:limit]
        
        for entry in display_entries:
            render_cache_card(entry)
        
        if len(filtered_entries) > limit:
            st.info(f"Showing {limit} of {len(filtered_entries)} entries. Use the sidebar to filter.")
    
    # Footer
    st.markdown("---")
    stats = cache.get_stats()
    st.caption(
        f"InfoDigest Dashboard • "
        f"Cache directory: {stats['cache_dir']} • "
        f"Total size: {stats['total_size_mb']} MB"
    )


if __name__ == "__main__":
    main()
