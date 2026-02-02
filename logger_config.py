"""
Structured logging configuration for translation bot services.

Sets up Python logging with appropriate levels and formatting for production use.
Compatible with Google Cloud Logging for structured log ingestion.
"""
import logging
import sys
from typing import Any, Dict


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Set up structured logger for application.
    
    Args:
        name: Logger name (typically __name__ of calling module)
        level: Logging level (default: INFO)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid adding multiple handlers if logger is already configured
    if logger.handlers:
        return logger
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    
    # Create formatter for structured logging
    # Format compatible with Google Cloud Logging
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    
    return logger


def log_with_context(logger: logging.Logger, level: int, message: str, **context: Any) -> None:
    """
    Log message with additional context fields.
    
    Args:
        logger: Logger instance
        level: Log level (logging.INFO, logging.ERROR, etc.)
        message: Log message
        **context: Additional context fields to include
    """
    if context:
        context_str = " | ".join(f"{k}={v}" for k, v in context.items())
        full_message = f"{message} | {context_str}"
    else:
        full_message = message
    
    logger.log(level, full_message)


# Convenience functions for common logging patterns
def log_translation(logger: logging.Logger, user_id: str, source_lang: str, 
                   target_lang: str, success: bool, duration_ms: float = 0) -> None:
    """Log translation event with context."""
    log_with_context(
        logger, logging.INFO,
        "Translation completed" if success else "Translation failed",
        user_id=user_id,
        source_lang=source_lang,
        target_lang=target_lang,
        success=success,
        duration_ms=int(duration_ms)
    )


def log_api_call(logger: logging.Logger, api_name: str, success: bool, 
                duration_ms: float = 0, error: str = None) -> None:
    """Log external API call with context."""
    context: Dict[str, Any] = {
        'api': api_name,
        'success': success,
        'duration_ms': int(duration_ms)
    }
    if error:
        context['error'] = error
    
    log_with_context(
        logger,
        logging.INFO if success else logging.ERROR,
        f"API call {'succeeded' if success else 'failed'}: {api_name}",
        **context
    )


def log_webhook_event(logger: logging.Logger, platform: str, user_id: str, 
                     event_type: str) -> None:
    """Log webhook event receipt."""
    log_with_context(
        logger, logging.INFO,
        f"Webhook event received: {event_type}",
        platform=platform,
        user_id=user_id,
        event_type=event_type
    )
