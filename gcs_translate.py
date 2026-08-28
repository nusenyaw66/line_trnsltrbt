from typing import Optional, Dict, Any
from google.cloud import translate_v2 as translate
import html
import hashlib
from functools import lru_cache
from datetime import datetime, timedelta

from premium_gating import is_ai_translation_mode


class PremiumRequiredError(Exception):
    """Raised when a premium-only translation feature is used without access."""


_client: Optional[translate.Client] = None
# Translation cache: {cache_key: (translated_text, timestamp)}
_translation_cache: Dict[str, tuple[str, datetime]] = {}
_cache_ttl = timedelta(hours=1)


def _get_client() -> translate.Client:
    """
    Always use Application Default Credentials (ADC).
    On Cloud Run, this automatically uses the attached service account.
    For local development, either:
    1. Use service account key file: Set GOOGLE_APPLICATION_CREDENTIALS env var
    2. Use ADC with impersonation: Requires 'Service Account Token Creator' role
    3. Use your own credentials: If you have Cloud Translation API access
    """
    global _client
    if _client is None:
        try:
            _client = translate.Client()  # ADC handles everything
        except Exception as e:
            print(f"ERROR: Failed to initialize Google Cloud Translate client: {e}")
            print("Make sure GOOGLE_APPLICATION_CREDENTIALS is set or running on GCP")
            raise
    return _client


def translate_text(text: str, target_language: str) -> str:
    """
    Translate text to target language with caching.
    
    Cache reduces API calls by ~80-90% for repeated translations.
    Cache key is based on text content and target language.
    """
    # Create cache key from text hash and target language
    text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
    cache_key = f"{target_language}:{text_hash}"
    
    # Check cache
    now = datetime.now()
    if cache_key in _translation_cache:
        cached_translation, cached_time = _translation_cache[cache_key]
        if now - cached_time < _cache_ttl:
            print(f"Translation cache hit for text (len={len(text)})")
            return cached_translation
        else:
            # Remove stale cache entry
            del _translation_cache[cache_key]
    
    # Cache miss - perform translation
    print(f"Translation cache miss, calling API (len={len(text)})")
    client = _get_client()
    # Use format_='text' to avoid HTML encoding, and decode any HTML entities
    result = client.translate(text, target_language=target_language, format_='text')
    translated = result["translatedText"]
    # Decode HTML entities (e.g., &#39; -> ')
    translated = html.unescape(translated)
    
    # Store in cache
    _translation_cache[cache_key] = (translated, now)
    
    # Cleanup old cache entries periodically (keep last 1000 entries)
    if len(_translation_cache) > 1000:
        # Remove oldest 200 entries
        sorted_keys = sorted(_translation_cache.keys(), 
                           key=lambda k: _translation_cache[k][1])
        for key in sorted_keys[:200]:
            del _translation_cache[key]
    
    return translated


def detect_and_translate(
    message: str,
    enabled: bool = True,
    source_lang: Optional[str] = None,
    target_lang: Optional[str] = None,
    mode: str = "pair",
    premium_access: bool = True,
) -> str:
    """
    Detect and translate message based on user settings.
    
    In pair mode, translation is bidirectional: source ↔ target.
    - If message is in source_lang → translate to target_lang
    - If message is in target_lang → translate to source_lang
    
    Args:
        message: Text to translate
        enabled: Whether translation is enabled
        source_lang: Source language code (for pair mode)
        target_lang: Target language code
        mode: "pair" (bidirectional), "american", "mandarin", or "japanese"
    
    Returns:
        Translated text, or original message if translation disabled/fails
    """
    if not enabled:
        return message

    if is_ai_translation_mode(mode) and not premium_access:
        raise PremiumRequiredError("Premium subscription required for AI translation modes")
    
    try:
        client = _get_client()
        detection = client.detect_language(message)
        detected_lang = detection["language"]
        
        # American mode: translate any detected language to en-US
        if mode == "american":
            if detected_lang == "en" or detected_lang.startswith("en-"):
                return message  # Already English
            return translate_text(message, "en-US")
        
        # Mandarin mode: translate any detected language to zh-TW
        if mode == "mandarin":
            if detected_lang == "zh-TW":
                return message  # Already Traditional Chinese
            return translate_text(message, "zh-TW")
        
        # Japanese mode: translate any detected language to ja
        if mode == "japanese":
            if detected_lang == "ja" or detected_lang.startswith("ja-"):
                return message  # Already Japanese
            return translate_text(message, "ja")
        
        # Pair mode: bidirectional translation (source ↔ target)
        if mode == "pair" and source_lang and target_lang:
            # Helper function to check if detected language matches a given language code
            def matches_lang(detected: str, lang_code: str) -> bool:
                """Check if detected language matches the given language code."""
                if lang_code in ("zh-CN", "zh-TW"):
                    both_chinese = source_lang in ("zh-CN", "zh-TW") and target_lang in ("zh-CN", "zh-TW")
                    if both_chinese:
                        # Distinguish scripts when translating Simplified ↔ Traditional.
                        if lang_code == "zh-TW":
                            return detected in {"zh-TW", "zh-Hant"}
                        return detected in {"zh", "zh-CN", "zh-Hans"}
                    return detected in {"zh", "zh-CN", "zh-TW", "zh-Hans", "zh-Hant"}
                if lang_code == "fil":
                    # Handle Filipino/Tagalog variants
                    return detected in {"fil", "tl"}
                if lang_code in ("fr", "it", "de", "ko"):
                    # Handle locale variants (e.g. fr-FR, it-IT, de-DE, ko-KR)
                    return detected == lang_code or (
                        len(lang_code) == 2 and detected.startswith(lang_code + "-")
                    )
                return detected == lang_code
            
            # Translate source → target
            if matches_lang(detected_lang, source_lang):
                return translate_text(message, target_lang)
            
            # Translate target → source (bidirectional)
            if matches_lang(detected_lang, target_lang):
                return translate_text(message, source_lang)
            
            # Neither source nor target detected, don't translate
            return message
        
        # Default behavior if no specific settings: detect and translate to English
        if detected_lang in {"zh", "zh-CN", "zh-TW"}:
            return translate_text(message, "en")
        if detected_lang == "en":
            return translate_text(message, "zh-TW")
        
        return message  # No translation if language not supported
    except Exception as e:
        print(f"ERROR in detect_and_translate: {e}")
        # Return original message if translation fails
        return message