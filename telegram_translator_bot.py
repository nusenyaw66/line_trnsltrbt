import json
import os
import re
import traceback
import urllib.error
import urllib.request
import hmac
from typing import Any, Dict, Optional, Union, cast

from dotenv import load_dotenv
from flask import Flask, abort, request
from google.cloud.firestore_v1 import Client
from google.cloud.firestore_v1.base_document import DocumentSnapshot

from gcs_audio import download_telegram_audio, speech_to_text
from gcs_translate import detect_and_translate
from rate_limiter import text_rate_limiter, voice_rate_limiter
from async_processor import async_processor

load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_SECRET_RAW = os.getenv('TELEGRAM_WEBHOOK_SECRET')
APP_VERSION = os.getenv('APP_VERSION', 'unknown')

app = Flask(__name__)

if not BOT_TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN not set!")
    print("Please set this environment variable in your .env file")
    raise ValueError("Telegram credentials not configured")

if not WEBHOOK_SECRET_RAW:
    print("ERROR: TELEGRAM_WEBHOOK_SECRET not set!")
    print("Please set this environment variable in your .env file")
    print("This is required for secure webhook authentication")
    raise ValueError("TELEGRAM_WEBHOOK_SECRET must be configured for security")

# Type assertion: WEBHOOK_SECRET is guaranteed to be str after the check above
WEBHOOK_SECRET: str = WEBHOOK_SECRET_RAW

_db_client: Optional[Client] = None
_COLLECTION_NAME = "user_settings"

AMERICAN_MODE_LANGUAGES = [
    "en-US", "zh-TW", "es-ES", "ja-JP", "ko-KR", "fr-FR", "de-DE", "it-IT",
    "pt-BR", "es-MX", "pt-PT", "zh-CN", "ru-RU", "ar-XA", "hi-IN", "th-TH",
    "id-ID", "vi-VN", "nl-NL", "pl-PL", "tr-TR", "fil-PH",
]


def _get_db() -> Client:
    global _db_client
    if _db_client is None:
        try:
            database_id = os.getenv('FIRESTORE_DATABASE_ID', 'line-trnsltrbt-db')
            _db_client = Client(database=database_id)
        except Exception as e:
            print(f"ERROR initializing Firestore client: {e}")
            raise
    return _db_client


def get_user_setting(user_id: str) -> Dict[str, Any]:
    try:
        db = _get_db()
        doc_ref = db.collection(_COLLECTION_NAME).document(user_id)
        doc = cast(DocumentSnapshot, doc_ref.get())
        if doc.exists:
            data = doc.to_dict()
            default_settings = {"enabled": False, "mode": "pair", "source_lang": None, "target_lang": None}
            default_settings.update(data or {})
            return default_settings
        return {"enabled": False, "mode": "pair", "source_lang": None, "target_lang": None}
    except Exception as e:
        print(f"ERROR loading user settings from Firestore: {e}")
        return {"enabled": False, "mode": "pair", "source_lang": None, "target_lang": None}


def update_user_setting(user_id: str, updates: Dict[str, Any]) -> None:
    try:
        db = _get_db()
        doc_ref = db.collection(_COLLECTION_NAME).document(user_id)
        current = get_user_setting(user_id)
        current.update(updates)
        doc_ref.set(current)
    except Exception as e:
        print(f"ERROR saving user settings to Firestore: {e}")
        raise


def get_thread_setting(thread_id: str) -> Dict[str, Any]:
    try:
        db = _get_db()
        doc_id = f"thread:{thread_id}"
        doc_ref = db.collection(_COLLECTION_NAME).document(doc_id)
        doc = cast(DocumentSnapshot, doc_ref.get())
        if doc.exists:
            data = doc.to_dict()
            default_settings = {"enabled": False, "mode": "pair", "source_lang": None, "target_lang": None}
            default_settings.update(data or {})
            return default_settings
        return {"enabled": False, "mode": "pair", "source_lang": None, "target_lang": None}
    except Exception as e:
        print(f"ERROR loading thread settings from Firestore: {e}")
        return {"enabled": False, "mode": "pair", "source_lang": None, "target_lang": None}


def update_thread_setting(thread_id: str, updates: Dict[str, Any]) -> None:
    try:
        db = _get_db()
        doc_id = f"thread:{thread_id}"
        doc_ref = db.collection(_COLLECTION_NAME).document(doc_id)
        current = get_thread_setting(thread_id)
        current.update(updates)
        doc_ref.set(current)
    except Exception as e:
        print(f"ERROR saving thread settings to Firestore: {e}")
        raise


def parse_switch_command(message: str) -> Optional[Dict[str, Any]]:
    message = message.strip()
    if not message.startswith('/'):
        return None
    parts = message.lower().split()
    if len(parts) == 0:
        return None
    command = parts[0]
    if command == '/set' and len(parts) >= 2:
        if parts[1] == 'on':
            return {"type": "set_on"}
        elif parts[1] == 'off':
            return {"type": "set_off"}
        elif len(parts) >= 5 and parts[1] == 'language' and parts[2] == 'pair':
            return {"type": "set_pair", "source": parts[3], "target": parts[4]}
        elif parts[1] == 'american':
            return {"type": "set_american"}
        elif parts[1] == 'mandarin':
            return {"type": "set_mandarin"}
        elif parts[1] == 'japanese':
            return {"type": "set_japanese"}
    if command == '/help':
        return {"type": "help"}
    if command == '/status':
        return {"type": "status"}
    return None


def get_telegram_user_display_name(from_obj: Dict[str, Any]) -> str:
    first = (from_obj.get("first_name") or "").strip()
    last = (from_obj.get("last_name") or "").strip()
    name = f"{first} {last}".strip()
    if name:
        return name
    username = from_obj.get("username")
    if username:
        return f"@{username}"
    return f"User ID: {from_obj.get('id', '')}"


def send_message(chat_id: Union[int, str], text: str) -> None:
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                result = json.loads(response.read().decode())
                if not result.get("ok"):
                    print(f"ERROR sending message: {result.get('description', 'unknown')}")
                else:
                    print(f"Message sent to chat_id={chat_id}")
            else:
                print(f"ERROR sending message: HTTP {response.status}")
    except urllib.error.HTTPError as e:
        body = e.read().decode() if hasattr(e, 'read') else None
        print(f"ERROR sending message: HTTP {e.code} {e.reason}")
        if body:
            print(f"  Error details: {body}")
    except Exception as e:
        print(f"ERROR sending message: {e}")
        print(traceback.format_exc())


def is_voice_translation_enabled(settings: Dict[str, Any]) -> bool:
    if not settings.get("enabled", False):
        return False
    mode = settings.get("mode")
    if mode == "pair":
        source_lang = settings.get("source_lang")
        target_lang = settings.get("target_lang")
        supported = ["en", "zh-TW", "es", "ja", "th", "id", "fil", "vi"]
        if source_lang and target_lang and source_lang in supported and target_lang in supported:
            return True
    elif mode in ("american", "mandarin", "japanese"):
        return True
    return False


def is_emoji_only(message: str) -> bool:
    stripped = message.strip()
    if not stripped:
        return True
    emoji_pattern = re.compile(
        r'^[\U0001F300-\U0001F9FF\U00002600-\U000026FF\U00002700-\U000027BF'
        r'\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
        r'\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U0000200D'
        r'\U0000FE00-\U0000FE0F\U0001F3FB-\U0001F3FF\U000020E3\s]*$',
        re.UNICODE
    )
    return bool(emoji_pattern.match(stripped))


def normalize_language_code(code: str) -> str:
    code_lower = code.lower()
    code_map = {
        "en": "en", "zh-tw": "zh-TW", "zh-cn": "zh-TW", "es": "es", "ja": "ja",
        "jpn": "ja", "th": "th", "id": "id", "ind": "id", "fil": "fil",
        "tl": "fil", "tagalog": "fil", "filipino": "fil",
        "fr": "fr", "french": "fr", "it": "it", "italian": "it", "ita": "it",
        "de": "de", "german": "de", "deu": "de", "ger": "de",
        "ko": "ko", "korean": "ko", "kor": "ko",
        "vi": "vi", "vie": "vi", "vietnamese": "vi",
    }
    return code_map.get(code_lower, code)


def handle_set_command(cmd_info: Dict[str, Any], chat_id: Union[int, str], user_id: str, thread_id: Optional[str] = None) -> None:
    if cmd_info["type"] == "set_on":
        if thread_id:
            update_thread_setting(thread_id, {"enabled": True})
            send_message(chat_id, "Translation enabled for this conversation ✓")
        else:
            update_user_setting(user_id, {"enabled": True})
            send_message(chat_id, "Translation enabled ✓")
    elif cmd_info["type"] == "set_off":
        if thread_id:
            update_thread_setting(thread_id, {"enabled": False})
            send_message(chat_id, "Translation disabled for this conversation ✓")
        else:
            update_user_setting(user_id, {"enabled": False})
            send_message(chat_id, "Translation disabled ✓")
    elif cmd_info["type"] == "set_pair":
        source = normalize_language_code(cmd_info["source"])
        target = normalize_language_code(cmd_info["target"])
        supported_codes = ["en", "zh-TW", "es", "ja", "th", "id", "fil", "fr", "it", "de", "ko", "vi"]
        if source not in supported_codes:
            send_message(chat_id, f"Invalid source language code: {cmd_info['source']}\nSupported: {', '.join(supported_codes)}")
            return
        if target not in supported_codes:
            send_message(chat_id, f"Invalid target language code: {cmd_info['target']}\nSupported: {', '.join(supported_codes)}")
            return
        settings_update = {"enabled": True, "mode": "pair", "source_lang": source, "target_lang": target}
        if thread_id:
            update_thread_setting(thread_id, settings_update)
            send_message(chat_id, f"Language pair set for this conversation: {source} → {target} ✓")
        else:
            update_user_setting(user_id, settings_update)
            send_message(chat_id, f"Language pair set: {source} → {target} ✓")
    elif cmd_info["type"] == "set_american":
        settings_update = {"enabled": True, "mode": "american", "source_lang": None, "target_lang": "en-US"}
        if thread_id:
            update_thread_setting(thread_id, settings_update)
            send_message(chat_id, "American mode enabled for this conversation ✓\nAll detected languages will be translated to American English.")
        else:
            update_user_setting(user_id, settings_update)
            send_message(chat_id, "American mode enabled ✓\nAll detected languages will be translated to American English.")
    elif cmd_info["type"] == "set_mandarin":
        settings_update = {"enabled": True, "mode": "mandarin", "source_lang": None, "target_lang": "zh-TW"}
        if thread_id:
            update_thread_setting(thread_id, settings_update)
            send_message(chat_id, "Mandarin mode enabled for this conversation ✓\nAll detected languages will be translated to Traditional Chinese (Taiwan).")
        else:
            update_user_setting(user_id, settings_update)
            send_message(chat_id, "Mandarin mode enabled ✓\nAll detected languages will be translated to Traditional Chinese (Taiwan).")
    elif cmd_info["type"] == "set_japanese":
        settings_update = {"enabled": True, "mode": "japanese", "source_lang": None, "target_lang": "ja"}
        if thread_id:
            update_thread_setting(thread_id, settings_update)
            send_message(chat_id, "Japanese mode enabled for this conversation ✓\nAll detected languages will be translated to Japanese.")
        else:
            update_user_setting(user_id, settings_update)
            send_message(chat_id, "Japanese mode enabled ✓\nAll detected languages will be translated to Japanese.")


def handle_status_command(chat_id: Union[int, str], thread_id: Optional[str] = None, status_type: str = "status") -> None:
    if status_type == "help":
        help_text = [
            "Add Translator Bot to a Group and enable translation with following commands:",
            "",
            "Commands start with /",
            "/set american - Translate All languages to American English",
            "/set mandarin - Translate All languages to Traditional Chinese (Taiwan)",
            "/set japanese - Translate All languages to Japanese",
            "/set language pair <lang1> <lang2> - sets specific language pair (e.g., /set language pair zh-tw en)",
            "Language options for /set language pair:",
            '   "zh-TW"  # Mandarin (we only support Traditional Chinese),',
            '   "ja"  # Japanese, also accepts "jpn",',
            '   "th"  # Thai,',
            '   "id"  # Indonesian, also accepts "ind",',
            '   "fil"  # Filipino, also accepts "filipino", "tagalog", "tl",',
            '   "vi"  # Vietnamese, also accepts "vie", "vietnamese",',
            '   "en", "fr", "de", "it", "es", "ko"  # English, French, German, Italian, Spanish, Korean',
            "/set off - disables translation",
            "/status - returns current user settings",
            "/help - returns this help message",
            "", "Voice-to-text is only available to paid customers!",
            "", f"Translator Bot for Telegram App. Version: {APP_VERSION}",
            "", "Copyright 2026 Tesseract Tech. LLC, Meridian  ID, USA",
            "Website: www.tssrct.us",
            "", "For Translate All modes, see: https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types for supported languages."        
        ]
        send_message(chat_id, "\n".join(help_text))
        return
    if thread_id:
        settings = get_thread_setting(thread_id)
        status_lines = ["Current Conversation Translation Settings:"]
    else:
        settings = get_user_setting(str(chat_id) if isinstance(chat_id, int) else chat_id)
        status_lines = ["Current Translation Settings:"]
    status_lines.append(f"Enabled: {'Yes' if settings['enabled'] else 'No'}")
    status_lines.append(f"Mode: {settings['mode']}")
    if settings['mode'] == 'pair':
        status_lines.append(f"Languages: {settings.get('source_lang', 'Not set')} <--> {settings.get('target_lang', 'Not set')}")
    elif settings['mode'] == 'american':
        status_lines.append("Target: American English (en-US)")
    elif settings['mode'] == 'mandarin':
        status_lines.append("Target: Traditional Chinese (zh-TW)")
    elif settings['mode'] == 'japanese':
        status_lines.append("Target: Japanese (ja)")
    send_message(chat_id, "\n".join(status_lines))


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint for liveness probe."""
    return {'status': 'healthy', 'service': 'telegram-translator-bot', 'version': APP_VERSION}, 200

@app.route('/ready', methods=['GET'])
def ready():
    """Readiness check endpoint - verifies dependencies are accessible."""
    try:
        # Check Firestore connection
        db = _get_db()
        # Quick connectivity check
        db.collection('_health_check').limit(1).get()
        
        return {
            'status': 'ready',
            'service': 'telegram-translator-bot',
            'version': APP_VERSION,
            'checks': {
                'firestore': 'ok',
                'telegram_api': 'configured' if BOT_TOKEN else 'missing'
            }
        }, 200
    except Exception as e:
        return {
            'status': 'not ready',
            'service': 'telegram-translator-bot',
            'error': str(e)
        }, 503

@app.route("/webhook", methods=['POST'])
def webhook():
    body = request.get_data()
    # Verify webhook secret using constant-time comparison to prevent timing attacks
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    # WEBHOOK_SECRET is guaranteed to be str (validated at startup)
    if not secret_header or not hmac.compare_digest(secret_header, WEBHOOK_SECRET):  # type: ignore[arg-type]
        print("Invalid or missing webhook secret")
        abort(403)
    try:
        data = json.loads(body.decode('utf-8'))
    except Exception as e:
        print(f"ERROR decoding webhook body: {e}")
        print(traceback.format_exc())
        return 'OK', 200  # Accept so Telegram does not retry
    if "message" not in data:
        return 'OK', 200
    message = data["message"]
    chat = message.get("chat", {})
    from_obj = message.get("from") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return 'OK', 200
    user_id = str(from_obj.get("id", ""))
    thread_id = str(chat_id) if chat.get("type") in ("group", "supergroup") else None
    try:
        if "text" in message:
            text = message.get("text") or ""
            handle_text_message(chat_id, user_id, text, thread_id, from_obj)
        elif "voice" in message:
            voice = message.get("voice") or {}
            file_id = voice.get("file_id")
            if file_id:
                handle_voice_message(chat_id, user_id, file_id, from_obj, thread_id)
        return 'OK', 200
    except Exception as e:
        print(f"ERROR in webhook handler: {e}")
        print(traceback.format_exc())
        return 'OK', 200  # Accept so Telegram does not retry; error is in logs


def handle_text_message(
    chat_id: Union[int, str],
    user_id: str,
    message_text: str,
    thread_id: Optional[str] = None,
    from_obj: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        # Check rate limit for text messages
        if not text_rate_limiter.is_allowed(user_id):
            print(f"Rate limit exceeded for user {user_id}")
            send_message(chat_id, "Rate limit exceeded. Please slow down (max 60 messages per minute).")
            return
        
        cmd_info = parse_switch_command(message_text)
        if cmd_info:
            if cmd_info["type"] in ["set_on", "set_off", "set_pair", "set_american", "set_mandarin", "set_japanese"]:
                handle_set_command(cmd_info, chat_id, user_id, thread_id)
            elif cmd_info["type"] in ["status", "help"]:
                handle_status_command(chat_id, thread_id, cmd_info["type"])
            return
        if is_emoji_only(message_text):
            return
        if thread_id:
            settings = get_thread_setting(thread_id)
        else:
            settings = get_user_setting(user_id)
        translated = detect_and_translate(
            message_text,
            enabled=settings["enabled"],
            source_lang=settings.get("source_lang"),
            target_lang=settings.get("target_lang"),
            mode=settings.get("mode", "pair")
        )
        if translated != message_text and settings["enabled"]:
            user_identifier = get_telegram_user_display_name(from_obj or {"id": user_id})
            reply_text = f"{user_identifier}:\n{translated}"
            send_message(chat_id, reply_text)
    except Exception as e:
        print(f"ERROR in handle_text_message: {e}")
        print(traceback.format_exc())


def handle_voice_message(
    chat_id: Union[int, str],
    user_id: str,
    file_id: str,
    from_obj: Dict[str, Any],
    thread_id: Optional[str] = None,
) -> None:
    try:
        # Check rate limit for voice messages (more expensive, lower limit)
        if not voice_rate_limiter.is_allowed(user_id):
            print(f"Voice rate limit exceeded for user {user_id}")
            send_message(chat_id, "Voice message rate limit exceeded. Please slow down (max 10 voice messages per minute).")
            return
        
        if thread_id:
            settings = get_thread_setting(thread_id)
        else:
            settings = get_user_setting(user_id)
        user_identifier = get_telegram_user_display_name(from_obj)

        if not is_voice_translation_enabled(settings):
            mode = settings.get("mode")
            source_lang = settings.get("source_lang")
            target_lang = settings.get("target_lang")
            if mode == "american":
                send_message(chat_id, "Voice translation is not enabled.\nPlease enable translation using:\n/set american")
            elif mode == "mandarin":
                send_message(chat_id, "Voice translation is not enabled.\nPlease enable translation using:\n/set mandarin")
            elif mode == "japanese":
                send_message(chat_id, "Voice translation is not enabled.\nPlease enable translation using:\n/set japanese")
            elif not source_lang or not target_lang:
                send_message(chat_id, "Voice translation requires a language pair.\n/set language pair <source> <target>\nOr /set american, /set mandarin, /set japanese")
            else:
                send_message(chat_id, f"Voice translation not enabled or pair ({source_lang} → {target_lang}) not supported.")
            return

        if not file_id:
            send_message(chat_id, "Could not get voice file. Please try again.")
            return
        try:
            if BOT_TOKEN is None:
                raise ValueError("BOT_TOKEN is not set.")
            audio_content = download_telegram_audio(file_id, BOT_TOKEN)
        except Exception as e:
            print(f"ERROR downloading Telegram voice: {e}")
            send_message(chat_id, "Could not download audio. Please try again.")
            return

        mode = settings.get("mode")
        transcribed_text = None
        recognition_errors = []

        if mode == "american":
            primary_lang = AMERICAN_MODE_LANGUAGES[0]
            alternative_langs = AMERICAN_MODE_LANGUAGES[1:5]
            try:
                transcribed_text = speech_to_text(audio_content, primary_lang, alternative_language_codes=alternative_langs)
            except Exception as e:
                recognition_errors.append(str(e))
            if not transcribed_text:
                for group_start in range(5, len(AMERICAN_MODE_LANGUAGES), 5):
                    group_languages = AMERICAN_MODE_LANGUAGES[group_start:group_start + 5]
                    if not group_languages:
                        break
                    primary = group_languages[0]
                    alternatives = group_languages[1:5]
                    try:
                        transcribed_text = speech_to_text(audio_content, primary, alternative_language_codes=alternatives)
                        if transcribed_text and transcribed_text.strip():
                            break
                    except Exception as e:
                        recognition_errors.append(str(e))
            if not transcribed_text or not transcribed_text.strip():
                send_message(chat_id, "Could not recognize speech. Please ensure audio is clear and try again.")
                return
            try:
                translated_text = detect_and_translate(transcribed_text, enabled=True, source_lang=None, target_lang="en-US", mode="american")
            except Exception as e:
                send_message(chat_id, f"{user_identifier}:\nTranscribed: {transcribed_text}\n(Translation failed)")
                return
            send_message(chat_id, f"{user_identifier}:\n{translated_text}")
            return

        if mode == "mandarin":
            primary_lang = "zh-TW"
            alternative_langs = [lang for lang in AMERICAN_MODE_LANGUAGES[:4] if lang != "zh-TW"][:4]
            try:
                transcribed_text = speech_to_text(audio_content, primary_lang, alternative_language_codes=alternative_langs)
            except Exception as e:
                recognition_errors.append(str(e))
            if not transcribed_text:
                for group_start in range(0, len(AMERICAN_MODE_LANGUAGES), 5):
                    group_languages = AMERICAN_MODE_LANGUAGES[group_start:group_start + 5]
                    if not group_languages or group_languages[0] == "zh-TW":
                        continue
                    primary = group_languages[0]
                    alternatives = [lang for lang in group_languages[1:5] if lang != "zh-TW"][:4]
                    try:
                        transcribed_text = speech_to_text(audio_content, primary, alternative_language_codes=alternatives)
                        if transcribed_text and transcribed_text.strip():
                            break
                    except Exception as e:
                        recognition_errors.append(str(e))
            if not transcribed_text or not transcribed_text.strip():
                send_message(chat_id, "Could not recognize speech. Please ensure audio is clear and try again.")
                return
            try:
                translated_text = detect_and_translate(transcribed_text, enabled=True, source_lang=None, target_lang="zh-TW", mode="mandarin")
            except Exception as e:
                send_message(chat_id, f"{user_identifier}:\nTranscribed: {transcribed_text}\n(Translation failed)")
                return
            send_message(chat_id, f"{user_identifier}:\n{translated_text}")
            return

        if mode == "japanese":
            primary_lang = "ja-JP"
            alternative_langs = [lang for lang in AMERICAN_MODE_LANGUAGES[:4] if lang != "ja-JP"][:4]
            try:
                transcribed_text = speech_to_text(audio_content, primary_lang, alternative_language_codes=alternative_langs)
            except Exception as e:
                recognition_errors.append(str(e))
            if not transcribed_text:
                for group_start in range(0, len(AMERICAN_MODE_LANGUAGES), 5):
                    group_languages = AMERICAN_MODE_LANGUAGES[group_start:group_start + 5]
                    if not group_languages or group_languages[0] == "ja-JP":
                        continue
                    primary = group_languages[0]
                    alternatives = [lang for lang in group_languages[1:5] if lang != "ja-JP"][:4]
                    try:
                        transcribed_text = speech_to_text(audio_content, primary, alternative_language_codes=alternatives)
                        if transcribed_text and transcribed_text.strip():
                            break
                    except Exception as e:
                        recognition_errors.append(str(e))
            if not transcribed_text or not transcribed_text.strip():
                send_message(chat_id, "Could not recognize speech. Please ensure audio is clear and try again.")
                return
            try:
                translated_text = detect_and_translate(transcribed_text, enabled=True, source_lang=None, target_lang="ja", mode="japanese")
            except Exception as e:
                send_message(chat_id, f"{user_identifier}:\nTranscribed: {transcribed_text}\n(Translation failed)")
                return
            send_message(chat_id, f"{user_identifier}:\n{translated_text}")
            return

        source_lang = settings.get("source_lang")
        target_lang = settings.get("target_lang")
        if not source_lang or not target_lang:
            send_message(chat_id, "Error: Language pair not properly configured.")
            return
        stt_language_map = {
            "en": "en-US", "zh-TW": "zh-TW", "es": "es-ES", "ja": "ja-JP",
            "th": "th-TH", "id": "id-ID", "fil": "fil-PH",
            "fr": "fr-FR", "it": "it-IT", "de": "de-DE", "ko": "ko-KR",
            "vi": "vi-VN",
        }
        source_stt_code = stt_language_map.get(source_lang)
        target_stt_code = stt_language_map.get(target_lang)
        if not source_stt_code or not target_stt_code:
            send_message(chat_id, f"Unsupported language(s) for voice. Supported: en, zh-TW, es, ja, th, id, fil, fr, it, de, ko, vi")
            return
        try:
            transcribed_text = speech_to_text(audio_content, source_stt_code, alternative_language_codes=[target_stt_code])
            detected_language = source_lang
        except Exception as e:
            recognition_errors.append(str(e))
            try:
                transcribed_text = speech_to_text(audio_content, target_stt_code, alternative_language_codes=[source_stt_code])
                detected_language = target_lang
            except Exception as e2:
                recognition_errors.append(str(e2))
                send_message(chat_id, "Could not recognize speech. Please ensure you speak in the configured language pair.")
                return
        if not transcribed_text or not transcribed_text.strip():
            send_message(chat_id, "Could not transcribe audio. Please try again with clearer audio.")
            return
        translation_target = target_lang if detected_language == source_lang else source_lang
        try:
            translated_text = detect_and_translate(transcribed_text, enabled=True, source_lang=detected_language, target_lang=translation_target, mode="pair")
        except Exception as e:
            send_message(chat_id, f"{user_identifier}:\nTranscribed: {transcribed_text}\n(Translation failed)")
            return
        send_message(chat_id, f"{user_identifier}:\n{translated_text}")
    except Exception as e:
        print(f"ERROR in handle_voice_message: {e}")
        print(traceback.format_exc())
        try:
            send_message(chat_id, "An error occurred processing the voice message. Please try again.")
        except Exception as _:
            pass


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
