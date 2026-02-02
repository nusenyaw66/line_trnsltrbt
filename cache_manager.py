"""
Cache manager for user profiles and other frequently accessed data.
Reduces API calls by caching user display names and other profile information.
"""
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
import threading


class ProfileCache:
    """
    Thread-safe cache for user profile information (display names, etc.).
    
    Uses time-based expiration (TTL) to ensure data freshness while reducing API calls.
    """
    
    def __init__(self, ttl_hours: int = 24):
        """
        Initialize profile cache.
        
        Args:
            ttl_hours: Time-to-live in hours (default 24 hours)
        """
        self.ttl = timedelta(hours=ttl_hours)
        # Cache format: {cache_key: (value, timestamp)}
        self.cache: Dict[str, Tuple[Optional[str], datetime]] = {}
        self.lock = threading.Lock()
    
    def get(self, user_id: str, group_id: Optional[str] = None) -> Optional[str]:
        """
        Get cached profile value for user.
        
        Args:
            user_id: User identifier
            group_id: Optional group/thread identifier for context-specific caching
            
        Returns:
            Cached value if found and not expired, None otherwise
        """
        cache_key = f"{user_id}:{group_id or 'direct'}"
        
        with self.lock:
            if cache_key in self.cache:
                value, timestamp = self.cache[cache_key]
                
                # Check if cache entry is still valid
                if datetime.now() - timestamp < self.ttl:
                    return value
                else:
                    # Remove expired entry
                    del self.cache[cache_key]
        
        return None
    
    def set(self, user_id: str, value: Optional[str], group_id: Optional[str] = None) -> None:
        """
        Store profile value in cache.
        
        Args:
            user_id: User identifier
            value: Value to cache (e.g., display name)
            group_id: Optional group/thread identifier
        """
        cache_key = f"{user_id}:{group_id or 'direct'}"
        
        with self.lock:
            self.cache[cache_key] = (value, datetime.now())
            
            # Cleanup old entries if cache grows too large
            if len(self.cache) > 1000:
                self._cleanup_old_entries()
    
    def _cleanup_old_entries(self) -> None:
        """Remove oldest 200 cache entries to prevent unbounded growth."""
        # Sort by timestamp (oldest first)
        sorted_keys = sorted(
            self.cache.keys(),
            key=lambda k: self.cache[k][1]
        )
        
        # Remove oldest 200 entries
        for key in sorted_keys[:200]:
            del self.cache[key]
        
        print(f"Profile cache cleanup: removed 200 old entries, {len(self.cache)} remaining")
    
    def invalidate(self, user_id: str, group_id: Optional[str] = None) -> None:
        """
        Invalidate cache entry for user.
        
        Args:
            user_id: User identifier
            group_id: Optional group/thread identifier
        """
        cache_key = f"{user_id}:{group_id or 'direct'}"
        
        with self.lock:
            if cache_key in self.cache:
                del self.cache[cache_key]
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self.lock:
            self.cache.clear()
    
    def size(self) -> int:
        """Get current cache size."""
        with self.lock:
            return len(self.cache)


# Global profile cache instance (24-hour TTL)
profile_cache = ProfileCache(ttl_hours=24)
