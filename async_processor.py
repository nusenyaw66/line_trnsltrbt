"""
Async webhook processor for handling long-running operations in the background.

Allows webhooks to respond immediately (within 20s timeout) while processing
time-consuming operations like audio translation asynchronously.
"""
from threading import Thread
from typing import Callable, Any
import traceback


def process_async(func: Callable, *args: Any, **kwargs: Any) -> Thread:
    """
    Execute function asynchronously in a background thread.
    
    Args:
        func: Function to execute
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func
    
    Returns:
        Thread object (already started)
    """
    def wrapper():
        try:
            func(*args, **kwargs)
        except Exception as e:
            print(f"ERROR in async processor: {e}")
            print(traceback.format_exc())
    
    thread = Thread(target=wrapper, daemon=True)
    thread.start()
    return thread


class AsyncWebhookProcessor:
    """
    Manages asynchronous webhook processing with optional callbacks.
    """
    
    def __init__(self):
        self.active_threads = []
    
    def submit(self, func: Callable, *args: Any, **kwargs: Any) -> Thread:
        """
        Submit task for async processing.
        
        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
        
        Returns:
            Thread object
        """
        thread = process_async(func, *args, **kwargs)
        self.active_threads.append(thread)
        
        # Cleanup completed threads
        self.active_threads = [t for t in self.active_threads if t.is_alive()]
        
        return thread
    
    def active_count(self) -> int:
        """Get number of active background threads."""
        self.active_threads = [t for t in self.active_threads if t.is_alive()]
        return len(self.active_threads)


# Global async processor instance
async_processor = AsyncWebhookProcessor()
