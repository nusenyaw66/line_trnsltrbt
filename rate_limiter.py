"""
Rate limiting module for translation bot services.
Implements per-user rate limiting to prevent abuse and control costs.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List
import threading


class RateLimiter:
    """
    Simple in-memory rate limiter using sliding window algorithm.
    
    Thread-safe implementation for concurrent requests.
    """
    
    def __init__(self, max_requests: int, window_seconds: int):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum number of requests allowed in the time window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window = timedelta(seconds=window_seconds)
        self.requests: Dict[str, List[datetime]] = defaultdict(list)
        self.lock = threading.Lock()
    
    def is_allowed(self, user_id: str) -> bool:
        """
        Check if a request from user_id is allowed under rate limit.
        
        Args:
            user_id: Unique identifier for the user
            
        Returns:
            True if request is allowed, False if rate limit exceeded
        """
        with self.lock:
            now = datetime.now()
            
            # Clean old requests outside the time window
            self.requests[user_id] = [
                req_time for req_time in self.requests[user_id]
                if now - req_time < self.window
            ]
            
            # Check if user has exceeded rate limit
            if len(self.requests[user_id]) >= self.max_requests:
                return False
            
            # Add current request
            self.requests[user_id].append(now)
            return True
    
    def get_remaining(self, user_id: str) -> int:
        """
        Get number of remaining requests for user in current window.
        
        Args:
            user_id: Unique identifier for the user
            
        Returns:
            Number of requests remaining before rate limit
        """
        with self.lock:
            now = datetime.now()
            
            # Clean old requests
            self.requests[user_id] = [
                req_time for req_time in self.requests[user_id]
                if now - req_time < self.window
            ]
            
            return max(0, self.max_requests - len(self.requests[user_id]))
    
    def reset(self, user_id: str) -> None:
        """
        Reset rate limit for a specific user.
        
        Args:
            user_id: Unique identifier for the user
        """
        with self.lock:
            if user_id in self.requests:
                del self.requests[user_id]


# Global rate limiter instances
# Text messages: 60 per minute per user
text_rate_limiter = RateLimiter(max_requests=60, window_seconds=60)

# Voice messages: 10 per minute per user (more expensive)
voice_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)

# Global API rate limiter: 1000 per minute across all users
global_rate_limiter = RateLimiter(max_requests=1000, window_seconds=60)
