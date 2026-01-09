from typing import Optional, Dict, Any
from google.cloud import translate_v2 as translate
import html


_client: Optional[translate.Client] = None


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
    client = _get_client()
    # Use format_='text' to avoid HTML encoding, and decode any HTML entities
    result = client.translate(text, target_language=target_language, format_='text')
    translated = result["translatedText"]
    # Decode HTML entities (e.g., &#39; -> ')
    return html.unescape(translated)


def detect_and_translate(
    message: str,
    enabled: bool = True,
    source_lang: Optional[str] = None,
    target_lang: Optional[str] = None,
    mode: str = "pair"
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
            if detected_lang in {"zh", "zh-CN", "zh-TW"}:
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
                if lang_code == "zh-TW":
                    # Handle Chinese variants
                    return detected in {"zh", "zh-CN", "zh-TW"}
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