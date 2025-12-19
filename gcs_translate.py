from typing import Optional
from google.cloud import translate_v2 as translate


_client: Optional[translate.Client] = None


def _get_client() -> translate.Client:
    """
    Always use Application Default Credentials (ADC).
    On Cloud Run, this automatically uses the attached service account.
    No env vars or keys required in production.
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
    result = client.translate(text, target_language=target_language)
    return result["translatedText"]


# Usage: If message is Chinese, translate to English; if English, to Chinese.
# Detect language first:
def detect_and_translate(message: str) -> str:
    try:
        client = _get_client()
        detection = client.detect_language(message)
        source_lang = detection["language"]
        if source_lang in {"zh", "zh-CN", "zh-TW"}:
            return translate_text(message, "en")  # Chinese to English
        if source_lang == "en":
            return translate_text(message, "zh-TW")  # English to Chinese (use 'zh-CN' for Simplified)
        return message  # No translation if neither
    except Exception as e:
        print(f"ERROR in detect_and_translate: {e}")
        # Return original message if translation fails
        return message