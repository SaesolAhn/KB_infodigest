"""
Cache Service for InfoDigest Bot.
Handles URL-based caching to avoid re-processing the same URLs.
"""

import json
import hashlib
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pathlib import Path


class CacheError(Exception):
    """Raised when cache operations fail."""
    pass


class CacheService:
    """
    Service for caching processed URLs and their summaries.
    Uses file-based storage with optional TTL (time-to-live).
    """
    
    def __init__(
        self,
        cache_dir: str = "cache",
        default_ttl_days: Optional[int] = None
    ):
        """
        Initialize cache service.
        
        Args:
            cache_dir: Directory to store cache files
            default_ttl_days: Default TTL in days (None = no expiration)
        """
        self.cache_dir = Path(cache_dir)
        self.default_ttl_days = default_ttl_days
        self.cache_dir.mkdir(exist_ok=True)
    
    def _get_url_hash(self, url: str) -> str:
        """Generate a hash for the URL to use as filename."""
        return hashlib.md5(url.encode()).hexdigest()
    
    def _get_cache_path(self, url: str) -> Path:
        """Get the cache file path for a URL."""
        url_hash = self._get_url_hash(url)
        return self.cache_dir / f"{url_hash}.json"
    
    def get(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached summary for a URL.
        
        Args:
            url: The URL to look up
            
        Returns:
            Cached data dict if found and not expired, None otherwise
        """
        cache_path = self._get_cache_path(url)
        
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Check expiration if TTL is set
            if self.default_ttl_days and 'cached_at' in data:
                cached_at = datetime.fromisoformat(data['cached_at'])
                expires_at = cached_at + timedelta(days=self.default_ttl_days)
                if datetime.utcnow() > expires_at:
                    # Cache expired, delete file
                    cache_path.unlink()
                    return None
            
            return data
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Corrupted cache file, delete it
            try:
                cache_path.unlink()
            except Exception:
                pass
            return None
    
    def set(
        self,
        url: str,
        summary: str,
        title: str,
        content_type: str,
        **metadata
    ) -> None:
        """
        Cache a summary for a URL.
        
        Args:
            url: The URL that was processed
            summary: The generated summary
            title: Content title
            content_type: Type of content
            **metadata: Additional metadata to store
        """
        cache_path = self._get_cache_path(url)
        
        data = {
            'url': url,
            'summary': summary,
            'title': title,
            'content_type': content_type,
            'cached_at': datetime.utcnow().isoformat(),
            **metadata
        }
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            raise CacheError(f"Failed to write cache: {e}")
    
    def delete(self, url: str) -> bool:
        """
        Delete a cached entry.
        
        Args:
            url: The URL to remove from cache
            
        Returns:
            True if deleted, False if not found
        """
        cache_path = self._get_cache_path(url)
        if cache_path.exists():
            try:
                cache_path.unlink()
                return True
            except Exception:
                return False
        return False
    
    def clear(self) -> int:
        """
        Clear all cached entries.
        
        Returns:
            Number of files deleted
        """
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
                count += 1
            except Exception:
                pass
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache stats
        """
        cache_files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in cache_files)
        
        return {
            'total_entries': len(cache_files),
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'cache_dir': str(self.cache_dir)
        }
