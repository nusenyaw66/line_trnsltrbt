from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    AudioMessageContent,
    StickerMessageContent,
    GroupSource
)
from dotenv import load_dotenv
import os
import traceback
import json
import urllib.request
import urllib.error
import re
from typing import Dict, Any, Optional, cast
from google.cloud.firestore_v1 import Client
from google.cloud.firestore_v1.base_document import DocumentSnapshot

from gcs_translate import detect_and_translate, PremiumRequiredError as TranslatePremiumRequiredError
from gcs_audio import speech_to_text, download_line_audio
from rate_limiter import text_rate_limiter, voice_rate_limiter
from cache_manager import profile_cache
from subscription_access import has_premium_access as _has_premium_access_from_settings
from premium_gating import requires_premium_for_translation, requires_premium_for_voice
from i18n import (
    detect_ui_language,
    get_lang_display_name,
    get_localized_help_lines,
    get_localized_status_lines,
    get_localized_subscription_status_lines,
    get_text,
    normalize_lang,
    supported_lang_codes,
)
from subscription_commands import build_activate_group_updates, build_subscribe_message_key
from firestore_client import (
    get_group_activation as _get_group_activation_from_store,
    get_user_subscription as _get_user_subscription_from_store,
    save_group_activation,
    save_user_subscription,
)

load_dotenv()
CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
APP_VERSION = os.getenv('APP_VERSION', 'unknown')

app = Flask(__name__)

# Initialize LINE Bot API
if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET:
    print("ERROR: LINE_CHANNEL_ACCESS_TOKEN or LINE_CHANNEL_SECRET not set!")
    print("Please set these environment variables in your .env file")
    raise ValueError("LINE credentials not configured")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# Firestore client (initialized lazily)
# Each LINE user has their own isolated settings stored as a separate document
# Document ID = user_id, ensuring complete data isolation between users
_db_client: Optional[Client] = None
_COLLECTION_NAME = "user_settings"


def _user_settings_json_path() -> str:
    return os.getenv(
        "USER_SETTINGS_JSON_PATH",
        os.path.join(os.path.dirname(__file__), "user_settings.json"),
    )


def _default_user_settings() -> Dict[str, Any]:
    return {
        "enabled": False,
        "mode": "pair",
        "source_lang": None,
        "target_lang": None,
        "ui_lang": None,
        "subscribed": False,
        "subscription_expires_at": None,
        "plan_type": None,
        "subscription_activated_at": None,
    }


def _default_group_settings() -> Dict[str, Any]:
    return {
        "enabled": False,
        "mode": "pair",
        "source_lang": None,
        "target_lang": None,
        "ui_lang": None,
        "subscription_activated_by_user_id": None,
        "subscription_activated_at": None,
        "subscription_expires_at": None,
    }


def _load_json_settings_store() -> Dict[str, Any]:
    try:
        with open(_user_settings_json_path(), "r", encoding="utf-8") as settings_file:
            data = json.load(settings_file)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"ERROR loading settings from JSON fallback: {e}")
        return {}


def _save_json_settings_store(store: Dict[str, Any]) -> None:
    try:
        with open(_user_settings_json_path(), "w", encoding="utf-8") as settings_file:
            json.dump(store, settings_file, indent=2, ensure_ascii=False)
            settings_file.write("\n")
    except Exception as e:
        print(f"ERROR saving settings to JSON fallback: {e}")
        raise


def _merge_settings(defaults: Dict[str, Any], data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = defaults.copy()
    merged.update(data or {})
    return merged


def _get_settings_from_json(doc_id: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    store = _load_json_settings_store()
    return _merge_settings(defaults, store.get(doc_id))


def _save_settings_to_json(doc_id: str, settings: Dict[str, Any]) -> None:
    store = _load_json_settings_store()
    store[doc_id] = settings
    _save_json_settings_store(store)

# Common languages for american mode (prioritized list)
# Google Cloud Speech-to-Text language codes for multi-language recognition
# These are used when mode is "american" to detect any language and translate to English
AMERICAN_MODE_LANGUAGES = [
    "en-US",      # English (most common)
    "zh-CN",      # Chinese (Simplified)
    "zh-TW",      # Chinese (Traditional)
    "es-ES",      # Spanish (Spain)
    "ja-JP",      # Japanese
    "ko-KR",      # Korean
    "fr-FR",      # French
    "de-DE",      # German
    "it-IT",      # Italian
    "pt-BR",      # Portuguese (Brazil)
    "es-MX",      # Spanish (Mexico)
    "pt-PT",      # Portuguese (Portugal)
    "ru-RU",      # Russian
    "ar-XA",      # Arabic
    "hi-IN",      # Hindi
    "th-TH",      # Thai
    "id-ID",      # Indonesian
    "vi-VN",      # Vietnamese
    "nl-NL",      # Dutch
    "pl-PL",      # Polish
    "tr-TR",      # Turkish
    "fil-PH",     # Filipino (Tagalog)
]


def _get_db() -> Client:
    """Get Firestore client, initializing if needed."""
    global _db_client
    if _db_client is None:
        try:
            # Use the specific database ID if provided, otherwise use default
            database_id = os.getenv('FIRESTORE_DATABASE_ID', 'line-trnsltrbt-db')
            _db_client = Client(database=database_id)
        except Exception as e:
            print(f"ERROR initializing Firestore client: {e}")
            print("Make sure the service account has Firestore permissions")
            raise
    return _db_client


def get_user_setting(user_id: str) -> Dict[str, Any]:
    """
    Get user settings from Firestore, returning defaults if not found.
    
    Each user's settings are stored in a separate Firestore document,
    ensuring complete isolation between different LINE users.
    Falls back to local JSON when Firestore is unavailable.
    
    Args:
        user_id: Unique LINE user ID (used as Firestore document ID)
    
    Returns:
        User settings dictionary with defaults if not found
    """
    defaults = _default_user_settings()
    try:
        db = _get_db()
        # Each user_id gets its own document - complete isolation
        doc_ref = db.collection(_COLLECTION_NAME).document(user_id)
        # Synchronous API - get() returns DocumentSnapshot directly (not awaitable)
        # Type cast needed because type checker incorrectly infers Awaitable
        doc = cast(DocumentSnapshot, doc_ref.get())
        
        if doc.exists:
            return _merge_settings(defaults, doc.to_dict())
        return defaults.copy()
    except Exception as e:
        print(f"ERROR loading user settings from Firestore: {e}")
        return _get_settings_from_json(user_id, defaults)


def update_user_setting(user_id: str, updates: Dict[str, Any]) -> None:
    """
    Update user settings in Firestore.
    
    Updates are isolated to the specific user_id - no other users' data is affected.
    Also persists to local JSON fallback for development/resilience.
    
    Args:
        user_id: Unique LINE user ID (used as Firestore document ID)
        updates: Dictionary of settings to update
    """
    current = get_user_setting(user_id)
    current.update(updates)

    firestore_error: Optional[Exception] = None
    try:
        db = _get_db()
        # Isolated document per user - updates only affect this user
        doc_ref = db.collection(_COLLECTION_NAME).document(user_id)
        doc_ref.set(current)
    except Exception as e:
        firestore_error = e
        print(f"ERROR saving user settings to Firestore: {e}")

    try:
        _save_settings_to_json(user_id, current)
    except Exception:
        if firestore_error is not None:
            raise firestore_error
        raise

    if firestore_error is not None:
        return


def save_user_setting(user_id: str, updates: Dict[str, Any]) -> None:
    """Save user settings updates (alias for update_user_setting)."""
    update_user_setting(user_id, updates)


def get_group_setting(group_id: str) -> Dict[str, Any]:
    """
    Get group settings from Firestore, returning defaults if not found.
    Falls back to local JSON when Firestore is unavailable.
    
    Args:
        group_id: Unique LINE group ID
    
    Returns:
        Group settings dictionary with defaults if not found
    """
    defaults = _default_group_settings()
    doc_id = f"group:{group_id}"
    try:
        db = _get_db()
        doc_ref = db.collection(_COLLECTION_NAME).document(doc_id)
        doc = cast(DocumentSnapshot, doc_ref.get())
        
        if doc.exists:
            return _merge_settings(defaults, doc.to_dict())
        return defaults.copy()
    except Exception as e:
        print(f"ERROR loading group settings from Firestore: {e}")
        return _get_settings_from_json(doc_id, defaults)


def update_group_setting(group_id: str, updates: Dict[str, Any]) -> None:
    """
    Update group settings in Firestore.
    Also persists to local JSON fallback for development/resilience.
    
    Args:
        group_id: Unique LINE group ID
        updates: Dictionary of settings to update
    """
    doc_id = f"group:{group_id}"
    current = get_group_setting(group_id)
    current.update(updates)

    firestore_error: Optional[Exception] = None
    try:
        db = _get_db()
        doc_ref = db.collection(_COLLECTION_NAME).document(doc_id)
        doc_ref.set(current)
    except Exception as e:
        firestore_error = e
        print(f"ERROR saving group settings to Firestore: {e}")

    try:
        _save_settings_to_json(doc_id, current)
    except Exception:
        if firestore_error is not None:
            raise firestore_error
        raise

    if firestore_error is not None:
        return


def save_group_setting(group_id: str, updates: Dict[str, Any]) -> None:
    """Save group settings updates (alias for update_group_setting)."""
    update_group_setting(group_id, updates)


def _has_subscription_data(subscription: Dict[str, Any]) -> bool:
    return bool(subscription.get("subscribed")) or subscription.get("plan_type") is not None


def _has_group_activation_data(activation: Dict[str, Any]) -> bool:
    return activation.get("subscription_activated_by_user_id") is not None


def _legacy_user_subscription(user_id: str) -> Dict[str, Any]:
    settings = get_user_setting(user_id)
    return {
        "subscribed": bool(settings.get("subscribed", False)),
        "subscription_expires_at": settings.get("subscription_expires_at"),
        "plan_type": settings.get("plan_type"),
        "subscription_activated_at": settings.get("subscription_activated_at"),
    }


def _legacy_group_activation(group_id: str) -> Dict[str, Any]:
    settings = get_group_setting(group_id)
    return {
        "subscription_activated_by_user_id": settings.get("subscription_activated_by_user_id"),
        "subscription_activated_at": settings.get("subscription_activated_at"),
        "subscription_expires_at": settings.get("subscription_expires_at"),
    }


def get_user_subscription(user_id: str) -> Dict[str, Any]:
    """Load personal subscription from dedicated store, with legacy user_settings fallback."""
    subscription = _get_user_subscription_from_store(user_id)
    if not _has_subscription_data(subscription):
        legacy = _legacy_user_subscription(user_id)
        if _has_subscription_data(legacy):
            return legacy
    return subscription


def get_group_subscription(group_id: str) -> Dict[str, Any]:
    """Load group activation from dedicated store, with legacy group settings fallback."""
    activation = _get_group_activation_from_store(group_id)
    if not _has_group_activation_data(activation):
        legacy = _legacy_group_activation(group_id)
        if _has_group_activation_data(legacy):
            return legacy
    return activation


def has_premium_access(user_id: str, group_id: Optional[str] = None) -> bool:
    """Return True when the user has active personal or group premium access."""
    user_settings = get_user_subscription(user_id)
    group_settings = get_group_subscription(group_id) if group_id else None
    return _has_premium_access_from_settings(
        user_id,
        user_settings,
        group_id=group_id,
        group_settings=group_settings,
    )


def parse_switch_command(message: str) -> Optional[Dict[str, Any]]:
    """Parse switch command from message. Returns command info or None if not a command."""
    message = message.strip()
    if not message.startswith('/'):
        return None
    
    parts = message.lower().split()
    if len(parts) == 0:
        return None
    
    command = parts[0]
    
    # /set commands - check these first before other /set commands
    if command == '/set' and len(parts) >= 2:
        # /set on
        if parts[1] == 'on':
            return {"type": "set_on"}
        # /set off
        elif parts[1] == 'off':
            return {"type": "set_off"}
        # /set pair <source> <target>
        elif len(parts) >= 4 and parts[1] == 'pair':
            source = parts[2]
            target = parts[3]
            return {"type": "set_pair", "source": source, "target": target}
        # /set american
        elif parts[1] == 'american':
            return {"type": "set_american"}
        # /set mandarin
        elif parts[1] == 'mandarin':
            return {"type": "set_mandarin"}
        # /set japanese
        elif parts[1] == 'japanese':
            return {"type": "set_japanese"}
        # /set lang <code>
        elif parts[1] == 'lang' and len(parts) >= 3:
            return {"type": "set_lang", "code": parts[2]}

    # /lang <code> (shorthand for /set lang)
    if command == '/lang' and len(parts) >= 2:
        return {"type": "set_lang", "code": parts[1]}

    # /subscribe
    if command == '/subscribe':
        return {"type": "subscribe"}

    # /activate group
    if command == '/activate' and len(parts) >= 2 and parts[1] == 'group':
        return {"type": "activate_group"}

    # /help
    if command == '/help':
        return {"type": "help"}
    # /status
    if command == '/status':
        if len(parts) >= 2 and parts[1] == 'subscription':
            return {"type": "status_subscription"}
        return {"type": "status"}

    return None


def get_user_display_name(user_id: str, group_id: Optional[str] = None) -> Optional[str]:
    """
    Get user's display name from LINE API with caching.
    
    For group chats, uses the group member profile endpoint.
    For individual chats, uses the user profile endpoint.
    
    Returns None if profile cannot be retrieved (user not added as friend,
    user blocked the bot, or API error).
    
    Cache reduces API calls by ~60% for repeated requests.
    
    Args:
        user_id: Unique LINE user ID
        group_id: Optional group ID for group chat contexts
    
    Returns:
        User's display name or None if unavailable
    """
    # Check cache first
    cached_name = profile_cache.get(user_id, group_id)
    if cached_name is not None:
        print(f"Profile cache hit for user {user_id}")
        return cached_name
    
    print(f"Profile cache miss, fetching from API for user {user_id}")
    
    if not CHANNEL_ACCESS_TOKEN:
        print("ERROR: CHANNEL_ACCESS_TOKEN not set, cannot retrieve profile")
        return None
    
    # Determine context and URL before try block to avoid unbound variable errors
    if group_id:
        # Group chat: use group member profile endpoint
        url = f"https://api.line.me/v2/bot/group/{group_id}/member/{user_id}"
        context = f"group {group_id}"
    else:
        # Individual chat: use user profile endpoint
        url = f"https://api.line.me/v2/bot/profile/{user_id}"
        context = "individual chat"
    
    try:
        
        headers = {
            "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                profile_data = json.loads(response.read().decode())
                display_name = profile_data.get("displayName")
                if display_name:
                    print(f"✓ Retrieved display name '{display_name}' for user {user_id} in {context}")
                    # Cache the result
                    profile_cache.set(user_id, display_name, group_id)
                return display_name
            else:
                print(f"WARNING: Unexpected status {response.status} when retrieving profile for user {user_id} in {context}")
                return None
                
    except urllib.error.HTTPError as e:
        # Detailed error handling for different HTTP status codes
        error_body = None
        try:
            error_body = e.read().decode()
        except:
            pass
        
        if e.code == 400:
            print(f"ERROR: Bad request when retrieving profile for user {user_id} in {context}: {e.code} {e.reason}")
            if error_body:
                print(f"  Error details: {error_body}")
        elif e.code == 401:
            print(f"ERROR: Authentication failed when retrieving profile. Check CHANNEL_ACCESS_TOKEN.")
        elif e.code == 403:
            print(f"ERROR: Forbidden - bot may not have permission to access profile for user {user_id} in {context}")
        elif e.code == 404:
            # User might not have added bot as friend, or blocked the bot, or not in group
            print(f"INFO: Profile not found for user {user_id} in {context} (user may not have added bot, blocked bot, or not in group)")
        else:
            print(f"ERROR: HTTP {e.code} {e.reason} when retrieving profile for user {user_id} in {context}")
            if error_body:
                print(f"  Error details: {error_body}")
                
    except urllib.error.URLError as e:
        print(f"ERROR: Network error when retrieving profile for user {user_id}: {e.reason}")
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON response when retrieving profile for user {user_id}: {e}")
    except Exception as e:
        print(f"ERROR retrieving user profile for {user_id}: {e}")
        print(traceback.format_exc())
    
    return None


def send_reply(reply_token: str, text: str) -> None:
    """Send reply message to user."""
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            # LINE Bot SDK v3 uses replyToken (camelCase) in the API
            # quickReply and quoteToken are optional parameters
            request = ReplyMessageRequest(
                replyToken=reply_token,  # type: ignore
                messages=[TextMessage(text=text)],  # type: ignore
                **{"quickReply": None, "quoteToken": None}  # type: ignore
            )
            line_bot_api.reply_message(request)
    except Exception as e:
        print(f"ERROR sending reply: {e}")
        print(traceback.format_exc())


def is_voice_translation_enabled(settings: Dict[str, Any]) -> bool:
    """
    Check if voice translation is enabled for the given settings.
    
    Voice translation is enabled when:
    - Translation is enabled
    - Mode is "pair" (with both source and target languages set and supported)
    - OR mode is "american" (translates any language to English)
    - OR mode is "mandarin" (translates any language to Traditional Chinese)
    - OR mode is "japanese" (translates any language to Japanese)
    
    Args:
        settings: User or group settings dictionary
    
    Returns:
        True if voice translation should be enabled
    """
    if not settings.get("enabled", False):
        return False
    
    mode = settings.get("mode")
    
    # Pair mode: requires both source and target languages
    if mode == "pair":
        source_lang = settings.get("source_lang")
        target_lang = settings.get("target_lang")
        # Supported languages for voice translation
        supported_languages = ["en", "zh-TW", "zh-CN", "es", "ja", "th", "id", "fil", "fr", "it", "de", "ko", "vi"]
        # Check if both languages are set and supported
        if source_lang and target_lang:
            if source_lang in supported_languages and target_lang in supported_languages:
                return True
    
    # American mode: translate any language to English
    elif mode == "american":
        return True  # American mode supports all languages that Speech-to-Text can recognize
    
    # Mandarin mode: translate any language to Traditional Chinese
    elif mode == "mandarin":
        return True  # Mandarin mode supports all languages that Speech-to-Text can recognize
    
    # Japanese mode: translate any language to Japanese
    elif mode == "japanese":
        return True  # Japanese mode supports all languages that Speech-to-Text can recognize
    
    return False


# Audio upload functions removed - no longer needed
# Voice translation now sends text messages instead of audio messages

def _resolve_ui_lang(user_id: str, group_id: Optional[str] = None) -> str:
    """Resolve the effective UI language for a user/group based on stored settings."""
    settings = get_group_setting(group_id) if group_id else get_user_setting(user_id)
    return detect_ui_language(
        user_id=user_id,
        group_id=group_id,
        ui_lang=settings.get("ui_lang"),
        target_lang=settings.get("target_lang"),
    )


def handle_on_command(user_id: str, reply_token: str, group_id: Optional[str] = None) -> None:
    """Handle /on translate command."""
    ui_lang = _resolve_ui_lang(user_id, group_id)
    if group_id:
        update_group_setting(group_id, {"enabled": True})
        send_reply(reply_token, get_text("translation_enabled_group", ui_lang))
    else:
        update_user_setting(user_id, {"enabled": True})
        send_reply(reply_token, get_text("translation_enabled", ui_lang))


def handle_off_command(user_id: str, reply_token: str, group_id: Optional[str] = None) -> None:
    """Handle /off translate command."""
    ui_lang = _resolve_ui_lang(user_id, group_id)
    if group_id:
        update_group_setting(group_id, {"enabled": False})
        send_reply(reply_token, get_text("translation_disabled_group", ui_lang))
    else:
        update_user_setting(user_id, {"enabled": False})
        send_reply(reply_token, get_text("translation_disabled", ui_lang))


def normalize_language_code(code: str) -> str:
    """Normalize language code to Google Cloud format (case-insensitive input)."""
    code_lower = code.lower()
    # Map lowercase inputs to proper Google Cloud format
    code_map = {
        "en": "en",
        "zh-tw": "zh-TW",
        "zh-hant": "zh-TW",
        "tw": "zh-TW",
        "zh-cn": "zh-CN",
        "zh-hans": "zh-CN",
        "cn": "zh-CN",
        "zh": "zh-CN",
        "es": "es",
        "ja": "ja",
        "jpn": "ja",  # Also accept jpn
        "th": "th",
        "id": "id",
        "ind": "id",  # Also accept ind
        "fil": "fil",  # Filipino
        "tl": "fil",  # Tagalog (maps to Filipino)
        "tagalog": "fil",  # Also accept tagalog
        "filipino": "fil",  # Also accept filipino
        "fr": "fr",  # French
        "french": "fr",
        "it": "it",  # Italian
        "italian": "it",
        "ita": "it",
        "de": "de",  # German
        "german": "de",
        "deu": "de",
        "ger": "de",
        "ko": "ko",  # Korean
        "korean": "ko",
        "kor": "ko",
        "vi": "vi",  # Vietnamese
        "vie": "vi",
        "vietnamese": "vi",
    }
    return code_map.get(code_lower, code)  # Return original if not in map


def handle_set_command(cmd_info: Dict[str, Any], user_id: str, reply_token: str, group_id: Optional[str] = None) -> None:
    """Handle /set commands."""
    ui_lang = _resolve_ui_lang(user_id, group_id)

    if cmd_info["type"] == "set_on":
        if group_id:
            update_group_setting(group_id, {"enabled": True})
            send_reply(reply_token, get_text("translation_enabled_group", ui_lang))
        else:
            update_user_setting(user_id, {"enabled": True})
            send_reply(reply_token, get_text("translation_enabled", ui_lang))

    elif cmd_info["type"] == "set_off":
        if group_id:
            update_group_setting(group_id, {"enabled": False})
            send_reply(reply_token, get_text("translation_disabled_group", ui_lang))
        else:
            update_user_setting(user_id, {"enabled": False})
            send_reply(reply_token, get_text("translation_disabled", ui_lang))

    elif cmd_info["type"] == "set_pair":
        source_input = cmd_info["source"]
        target_input = cmd_info["target"]

        source = normalize_language_code(source_input)
        target = normalize_language_code(target_input)

        supported_codes = ["en", "zh-TW", "zh-CN", "es", "ja", "th", "id", "fil", "fr", "it", "de", "ko", "vi"]

        if source not in supported_codes:
            supported = ", ".join(supported_codes)
            send_reply(
                reply_token,
                get_text("err_invalid_source", ui_lang, code=source_input, supported=supported),
            )
            return

        if target not in supported_codes:
            supported = ", ".join(supported_codes)
            send_reply(
                reply_token,
                get_text("err_invalid_target", ui_lang, code=target_input, supported=supported),
            )
            return

        settings_update = {
            "enabled": True,
            "mode": "pair",
            "source_lang": source,
            "target_lang": target,
        }
        if group_id:
            update_group_setting(group_id, settings_update)
            send_reply(
                reply_token,
                get_text("pair_set_group", ui_lang, source=source, target=target),
            )
        else:
            update_user_setting(user_id, settings_update)
            send_reply(
                reply_token,
                get_text("pair_set", ui_lang, source=source, target=target),
            )

    elif cmd_info["type"] == "set_american":
        settings_update = {
            "enabled": True,
            "mode": "american",
            "source_lang": None,
            "target_lang": "en-US",
        }
        if group_id:
            update_group_setting(group_id, settings_update)
            send_reply(reply_token, get_text("american_enabled_group", ui_lang))
        else:
            update_user_setting(user_id, settings_update)
            send_reply(reply_token, get_text("american_enabled", ui_lang))

    elif cmd_info["type"] == "set_mandarin":
        settings_update = {
            "enabled": True,
            "mode": "mandarin",
            "source_lang": None,
            "target_lang": "zh-TW",
        }
        if group_id:
            update_group_setting(group_id, settings_update)
            send_reply(reply_token, get_text("mandarin_enabled_group", ui_lang))
        else:
            update_user_setting(user_id, settings_update)
            send_reply(reply_token, get_text("mandarin_enabled", ui_lang))

    elif cmd_info["type"] == "set_japanese":
        settings_update = {
            "enabled": True,
            "mode": "japanese",
            "source_lang": None,
            "target_lang": "ja",
        }
        if group_id:
            update_group_setting(group_id, settings_update)
            send_reply(reply_token, get_text("japanese_enabled_group", ui_lang))
        else:
            update_user_setting(user_id, settings_update)
            send_reply(reply_token, get_text("japanese_enabled", ui_lang))

    elif cmd_info["type"] == "set_lang":
        handle_set_lang_command(cmd_info["code"], user_id, reply_token, group_id)


def handle_set_lang_command(code: str, user_id: str, reply_token: str, group_id: Optional[str] = None) -> None:
    """Handle /lang <code> and /set lang <code>.

    Validates the requested UI language code, persists it on user or group
    settings, and replies in the *new* language so the change is immediately
    visible.
    """
    canonical = normalize_lang(code)
    if not canonical:
        # Reply in the user's current UI lang (best-effort) so the error itself
        # is still understandable.
        current_ui = _resolve_ui_lang(user_id, group_id)
        send_reply(
            reply_token,
            get_text("err_unknown_ui_lang", current_ui, code=code),
        )
        return

    if group_id:
        update_group_setting(group_id, {"ui_lang": canonical})
        msg_key = "lang_set_group"
    else:
        update_user_setting(user_id, {"ui_lang": canonical})
        msg_key = "lang_set"

    # Reply in the newly-selected language so the user immediately sees it.
    send_reply(
        reply_token,
        get_text(msg_key, canonical, lang_name=get_lang_display_name(canonical, canonical)),
    )


def handle_subscribe_command(user_id: str, reply_token: str, group_id: Optional[str] = None) -> None:
    """Handle /subscribe — show subscription info or active status."""
    ui_lang = _resolve_ui_lang(user_id, group_id)
    user_subscription = get_user_subscription(user_id)
    message_key, kwargs = build_subscribe_message_key(user_id, user_subscription)
    send_reply(reply_token, get_text(message_key, ui_lang, **kwargs))


def handle_activate_group_command(
    user_id: str,
    reply_token: str,
    group_id: Optional[str] = None,
) -> None:
    """Handle /activate group — apply personal subscription to the current group."""
    ui_lang = _resolve_ui_lang(user_id, group_id)
    user_subscription = get_user_subscription(user_id)
    result = build_activate_group_updates(user_id, user_subscription, group_id)
    if result.ok and result.group_updates is not None and group_id:
        save_group_activation(group_id, result.group_updates)
    send_reply(reply_token, get_text(result.message_key, ui_lang, **result.message_kwargs))


def handle_status_subscription_command(
    user_id: str,
    reply_token: str,
    group_id: Optional[str] = None,
) -> None:
    """Handle /status subscription — show personal and group subscription status."""
    ui_lang = _resolve_ui_lang(user_id, group_id)
    user_subscription = get_user_subscription(user_id)
    group_subscription = get_group_subscription(group_id) if group_id else None
    status_lines = get_localized_subscription_status_lines(
        user_settings=user_subscription,
        lang=ui_lang,
        user_id=user_id,
        group_settings=group_subscription,
        is_group=bool(group_id),
    )
    send_reply(reply_token, "\n".join(status_lines))


def handle_status_command(user_id: str, reply_token: str, group_id: Optional[str] = None, status_type: str = "status") -> None:
    """Handle /status and /help commands (localized)."""
    if group_id:
        settings = get_group_setting(group_id)
    else:
        settings = get_user_setting(user_id)

    ui_lang = detect_ui_language(
        user_id=user_id,
        group_id=group_id,
        ui_lang=settings.get("ui_lang"),
        target_lang=settings.get("target_lang"),
    )

    if status_type == "help":
        help_lines = get_localized_help_lines(lang=ui_lang, version=APP_VERSION, platform="LINE")
        send_reply(reply_token, "\n".join(help_lines))
        return

    status_lines = get_localized_status_lines(
        enabled=bool(settings.get("enabled")),
        mode=settings.get("mode", "pair"),
        source=settings.get("source_lang"),
        target=settings.get("target_lang"),
        lang=ui_lang,
        is_group=bool(group_id),
        ui_lang=settings.get("ui_lang"),
    )
    send_reply(reply_token, "\n".join(status_lines))


def is_emoji_only(message: str) -> bool:
    """
    Check if message contains only emojis/LINE icons (no regular text).
    
    Args:
        message: The message text to check
    
    Returns:
        True if message contains only emojis/icons, False otherwise
    """
    # Remove whitespace
    stripped = message.strip()
    
    # Empty message is considered emoji-only
    if not stripped:
        return True
    
    # Regex pattern for emoji Unicode ranges
    # This covers most emoji ranges including:
    # - Emoticons and symbols
    # - Miscellaneous symbols and pictographs
    # - Supplemental symbols and pictographs
    # - Symbols and pictographs extended-A
    # - Skin tone modifiers
    # - Variation selectors
    # - Zero-width joiner (for composite emojis)
    emoji_pattern = re.compile(
        r'^[\U0001F300-\U0001F9FF\U00002600-\U000026FF\U00002700-\U000027BF'
        r'\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
        r'\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U0000200D'
        r'\U0000FE00-\U0000FE0F\U0001F3FB-\U0001F3FF\U000020E3\s]*$',
        re.UNICODE
    )
    
    # Check if the entire message matches emoji pattern
    return bool(emoji_pattern.match(stripped))

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint for liveness probe."""
    return {'status': 'healthy', 'service': 'line-translator-bot', 'version': APP_VERSION}, 200

@app.route('/ready', methods=['GET'])
def ready():
    """Readiness check endpoint - verifies dependencies are accessible."""
    try:
        # Check Firestore connection
        db = _get_db()
        # Quick connectivity check - try to access collection
        db.collection('_health_check').limit(1).get()
        
        return {
            'status': 'ready',
            'service': 'line-translator-bot',
            'version': APP_VERSION,
            'checks': {
                'firestore': 'ok',
                'line_api': 'configured' if CHANNEL_ACCESS_TOKEN else 'missing'
            }
        }, 200
    except Exception as e:
        return {
            'status': 'not ready',
            'service': 'line-translator-bot',
            'error': str(e)
        }, 503

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
    if not signature:
        print("Missing X-Line-Signature header")
        abort(401)
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)
    except Exception as e:
        print(f"ERROR in webhook handler: {e}")
        print(traceback.format_exc())
        abort(500)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    try:
        user_message = event.message.text
        # Extract unique user ID from LINE event - this ensures each user's
        # settings are completely isolated in Firestore
        user_id = event.source.user_id if hasattr(event.source, 'user_id') else None
        
        if not user_id:
            print("WARNING: Could not extract user_id from event")
            print(f"Event source type: {type(event.source)}")
            return
        
        # Check rate limit for text messages
        if not text_rate_limiter.is_allowed(user_id):
            print(f"Rate limit exceeded for user {user_id}")
            ui_lang = _resolve_ui_lang(
                user_id,
                event.source.group_id if isinstance(event.source, GroupSource) else None,
            )
            send_reply(event.reply_token, get_text("err_rate_limit_text", ui_lang))
            return
        
        # Check if this is a group chat
        group_id = None
        if isinstance(event.source, GroupSource):
            group_id = event.source.group_id
            print(f"Message received in group: {group_id} from user: {user_id}")
        
        # Check if message is a switch command
        cmd_info = parse_switch_command(user_message)
        if cmd_info:
            if cmd_info["type"] in ["set_on", "set_off", "set_pair", "set_american", "set_mandarin", "set_japanese", "set_lang"]:
                handle_set_command(cmd_info, user_id, event.reply_token, group_id)
            elif cmd_info["type"] in ["status", "help"]:
                handle_status_command(user_id, event.reply_token, group_id, cmd_info["type"])
            elif cmd_info["type"] == "subscribe":
                handle_subscribe_command(user_id, event.reply_token, group_id)
            elif cmd_info["type"] == "activate_group":
                handle_activate_group_command(user_id, event.reply_token, group_id)
            elif cmd_info["type"] == "status_subscription":
                handle_status_subscription_command(user_id, event.reply_token, group_id)
            return
        
        # Skip translation if message contains only emojis/LINE icons
        if is_emoji_only(user_message):
            print(f"Skipping translation for emoji-only message from user {user_id}")
            return
        
        # Skip translation if message contains only emojis/LINE icons
        if is_emoji_only(user_message):
            print(f"Skipping translation for emoji-only message from user {user_id}")
            return
        
        # Not a command, apply translation based on settings
        # In group chats, use group settings; otherwise use user settings
        if group_id:
            settings = get_group_setting(group_id)
        else:
            settings = get_user_setting(user_id)

        premium_access = has_premium_access(user_id, group_id)
        if requires_premium_for_translation(settings.get("mode", "pair"), settings["enabled"]):
            if not premium_access:
                ui_lang = _resolve_ui_lang(user_id, group_id)
                send_reply(event.reply_token, get_text("err_premium_required", ui_lang))
                return
        
        try:
            translated = detect_and_translate(
                user_message,
                enabled=settings["enabled"],
                source_lang=settings.get("source_lang"),
                target_lang=settings.get("target_lang"),
                mode=settings.get("mode", "pair"),
                premium_access=premium_access,
            )
        except TranslatePremiumRequiredError:
            ui_lang = _resolve_ui_lang(user_id, group_id)
            send_reply(event.reply_token, get_text("err_premium_required", ui_lang))
            return
        
        # Only send reply if translation occurred and is different from original
        if translated != user_message and settings["enabled"]:
            # Try to get user's display name, fallback to user ID if unavailable
            # Pass group_id for proper profile retrieval in group chats
            display_name = get_user_display_name(user_id, group_id)
            user_identifier = display_name if display_name else f"User ID: {user_id}"
            reply_text = f"{user_identifier}:\n{translated}"
            send_reply(event.reply_token, reply_text)
    except Exception as e:
        print(f"ERROR in handle_message: {e}")
        print(traceback.format_exc())


@handler.add(MessageEvent, message=StickerMessageContent)
def handle_sticker_message(event):
    """Handle sticker messages - skip translation for stickers."""
    try:
        user_id = event.source.user_id if hasattr(event.source, 'user_id') else None
        if user_id:
            print(f"Skipping translation for sticker message from user {user_id}")
        # Stickers are not translated, just return
        return
    except Exception as e:
        print(f"ERROR in handle_sticker_message: {e}")
        print(traceback.format_exc())


@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio_message(event):
    """
    Handle audio/voice messages for voice translation.
    Processes when:
    - Translation is enabled
    - Mode is "pair" (with both source and target languages set and supported)
    - OR mode is "american" (translates any language to English)
    - OR mode is "mandarin" (translates any language to Traditional Chinese)
    - OR mode is "japanese" (translates any language to Japanese)
    """
    try:
        user_id = event.source.user_id if hasattr(event.source, 'user_id') else None
        
        if not user_id:
            print("WARNING: Could not extract user_id from audio event")
            return
        
        # Check rate limit for voice messages (more expensive, lower limit)
        if not voice_rate_limiter.is_allowed(user_id):
            print(f"Voice rate limit exceeded for user {user_id}")
            ui_lang = _resolve_ui_lang(
                user_id,
                event.source.group_id if isinstance(event.source, GroupSource) else None,
            )
            send_reply(event.reply_token, get_text("err_rate_limit_voice", ui_lang))
            return
        
        # Check if this is a group chat
        group_id = None
        if isinstance(event.source, GroupSource):
            group_id = event.source.group_id
            print(f"Audio message received in group: {group_id} from user: {user_id}")
        
        # Get user's display name for reply messages (fallback to user ID if unavailable)
        display_name = get_user_display_name(user_id, group_id)
        user_identifier = display_name if display_name else f"User ID: {user_id}"
        
        # Get user/group settings
        if group_id:
            settings = get_group_setting(group_id)
        else:
            settings = get_user_setting(user_id)

        premium_access = has_premium_access(user_id, group_id)
        if requires_premium_for_voice() and not premium_access:
            ui_lang = _resolve_ui_lang(user_id, group_id)
            send_reply(event.reply_token, get_text("err_premium_required", ui_lang))
            return
        
        # Check if voice translation is enabled
        if not is_voice_translation_enabled(settings):
            # Voice translation not enabled, send informative message
            mode = settings.get("mode")
            source_lang = settings.get("source_lang")
            target_lang = settings.get("target_lang")
            
            if mode == "american":
                send_reply(
                    event.reply_token,
                    "Voice translation is not enabled.\n"
                    "Please enable translation using:\n"
                    "/set american"
                )
            elif mode == "mandarin":
                send_reply(
                    event.reply_token,
                    "Voice translation is not enabled.\n"
                    "Please enable translation using:\n"
                    "/set mandarin"
                )
            elif mode == "japanese":
                send_reply(
                    event.reply_token,
                    "Voice translation is not enabled.\n"
                    "Please enable translation using:\n"
                    "/set japanese"
                )
            elif not source_lang or not target_lang:
                send_reply(
                    event.reply_token,
                    "Voice translation requires a language pair to be set.\n"
                    "Please set a language pair using:\n"
                    "/set pair <source> <target>\n\n"
                    "Or use American mode:\n"
                    "/set american\n\n"
                    "Or use Mandarin mode:\n"
                    "/set mandarin\n\n"
                    "Or use Japanese mode:\n"
                    "/set japanese\n\n"
                    "Supported languages for pair mode: en, zh-TW, zh-CN, es, ja, th, id, fil, vi, fr, it, de, ko"
                )
            else:
                send_reply(
                    event.reply_token,
                    f"Voice translation is not enabled or language pair ({source_lang} → {target_lang}) is not supported.\n"
                    "Please ensure translation is enabled and both languages are supported.\n\n"
                    "Supported languages: en, zh-TW, zh-CN, es, ja, th, id, fil, vi, fr, it, de, ko\n"
                    "Or use American mode: /set american\n"
                    "Or use Mandarin mode: /set mandarin\n"
                    "Or use Japanese mode: /set japanese"
                )
            return
        
        # Get audio message ID
        message_id = event.message.id
        
        if not CHANNEL_ACCESS_TOKEN:
            send_reply(event.reply_token, "Error: Channel access token not configured.")
            return
        
        # Download audio from LINE
        try:
            audio_content = download_line_audio(message_id, CHANNEL_ACCESS_TOKEN)
        except Exception as e:
            print(f"ERROR downloading audio: {e}")
            send_reply(event.reply_token, "Could not download audio. Please try again.")
            return
        
        mode = settings.get("mode")
        transcribed_text = None
        detected_language = None
        recognition_errors = []
        
        # Handle american mode
        if mode == "american":
            # American mode: try multiple languages to detect any language
            # Google Cloud Speech-to-Text supports up to 4 alternative languages per request
            # We'll try language groups sequentially
            
            # Try first group: English + top 4 alternatives
            primary_lang = AMERICAN_MODE_LANGUAGES[0]
            alternative_langs = AMERICAN_MODE_LANGUAGES[1:5]  # Max 4 alternatives
            
            print(f"Attempting speech recognition (American mode) with {primary_lang} and alternatives: {alternative_langs}")
            try:
                transcribed_text = speech_to_text(audio_content, primary_lang, alternative_language_codes=alternative_langs, premium_access=True)
                if transcribed_text and transcribed_text.strip():
                    print(f"✓ Speech recognized (American mode): {transcribed_text}")
                else:
                    raise Exception("Recognition returned empty transcript")
            except Exception as e:
                error_msg = f"Recognition failed for first language group: {str(e)}"
                print(error_msg)
                recognition_errors.append(error_msg)
                transcribed_text = None
            
            # If first group failed, try next groups (5 languages per group)
            if not transcribed_text:
                for group_start in range(5, len(AMERICAN_MODE_LANGUAGES), 5):
                    group_languages = AMERICAN_MODE_LANGUAGES[group_start:group_start + 5]
                    if not group_languages:
                        break
                    
                    primary = group_languages[0]
                    alternatives = group_languages[1:5]  # Max 4 alternatives
                    
                    print(f"Attempting speech recognition (American mode) with {primary} and alternatives: {alternatives}")
                    try:
                        transcribed_text = speech_to_text(audio_content, primary, alternative_language_codes=alternatives, premium_access=True)
                        if transcribed_text and transcribed_text.strip():
                            print(f"✓ Speech recognized (American mode): {transcribed_text}")
                            break
                        else:
                            raise Exception("Recognition returned empty transcript")
                    except Exception as e:
                        error_msg = f"Recognition failed for language group starting with {primary}: {str(e)}"
                        print(error_msg)
                        recognition_errors.append(error_msg)
                        continue
            
            # If all attempts failed, send error message
            if not transcribed_text or not transcribed_text.strip():
                error_details = "\n".join(recognition_errors[-3:]) if recognition_errors else "Unknown error"  # Show last 3 errors
                print(f"All speech recognition attempts failed (American mode). Errors: {error_details}")
                send_reply(
                    event.reply_token,
                    "Could not recognize speech. Please ensure:\n"
                    "- Audio is clear and not too quiet\n"
                    "- You're speaking in a supported language\n"
                    "- Try speaking more slowly or clearly\n\n"
                    "Note: Only languages supported by Google Cloud Speech-to-Text can be recognized."
                )
                return
            
            # Translate transcribed text to English using american mode
            try:
                translated_text = detect_and_translate(
                    transcribed_text,
                    enabled=True,
                    source_lang=None,  # Let it auto-detect
                    target_lang="en-US",
                    mode="american",
                    premium_access=True,
                )
                
                print(f"Translated (American mode): {transcribed_text} -> {translated_text}")
                
            except Exception as e:
                print(f"ERROR translating text (American mode): {e}")
                # Fallback: send transcribed text
                send_reply(
                    event.reply_token,
                    f"{user_identifier}:\nTranscribed: {transcribed_text}\n(Translation to English failed)"
                )
                return
            
            # Send translated text
            try:
                reply_text = f"{user_identifier}:\n{translated_text}"
                send_reply(event.reply_token, reply_text)
                
                print(f"Voice translation completed (American mode)")
                print(f"Original: {transcribed_text}")
                print(f"Translated: {translated_text}")
                
            except Exception as e:
                print(f"ERROR sending reply: {e}")
                print(traceback.format_exc())
                try:
                    send_reply(event.reply_token, f"{user_identifier}:\n{translated_text}")
                except:
                    pass
            
            return
        
        # Handle mandarin mode
        if mode == "mandarin":
            # Mandarin mode: try multiple languages to detect any language
            # Google Cloud Speech-to-Text supports up to 4 alternative languages per request
            # We'll try language groups sequentially
            
            # Try first group: Traditional Chinese + top 4 alternatives
            primary_lang = "zh-TW"
            alternative_langs = AMERICAN_MODE_LANGUAGES[:4]  # Use first 4 from the list (excluding zh-TW if present)
            # Remove zh-TW from alternatives if it's there, and ensure we have 4 alternatives
            alternative_langs = [lang for lang in alternative_langs if lang != "zh-TW"][:4]
            if len(alternative_langs) < 4:
                # Add more languages if needed
                additional = [lang for lang in AMERICAN_MODE_LANGUAGES[4:] if lang != "zh-TW"][:4-len(alternative_langs)]
                alternative_langs.extend(additional)
            
            print(f"Attempting speech recognition (Mandarin mode) with {primary_lang} and alternatives: {alternative_langs}")
            try:
                transcribed_text = speech_to_text(audio_content, primary_lang, alternative_language_codes=alternative_langs, premium_access=True)
                if transcribed_text and transcribed_text.strip():
                    print(f"✓ Speech recognized (Mandarin mode): {transcribed_text}")
                else:
                    raise Exception("Recognition returned empty transcript")
            except Exception as e:
                error_msg = f"Recognition failed for first language group: {str(e)}"
                print(error_msg)
                recognition_errors.append(error_msg)
                transcribed_text = None
            
            # If first group failed, try next groups (5 languages per group)
            if not transcribed_text:
                for group_start in range(0, len(AMERICAN_MODE_LANGUAGES), 5):
                    group_languages = AMERICAN_MODE_LANGUAGES[group_start:group_start + 5]
                    if not group_languages:
                        break
                    
                    # Skip if zh-TW is already primary
                    if group_languages[0] == "zh-TW" and group_start == 0:
                        continue
                    
                    primary = group_languages[0]
                    alternatives = [lang for lang in group_languages[1:5] if lang != "zh-TW"]  # Max 4 alternatives, exclude zh-TW
                    # Ensure we have alternatives
                    if len(alternatives) < 4:
                        additional = [lang for lang in AMERICAN_MODE_LANGUAGES if lang not in alternatives and lang != "zh-TW"][:4-len(alternatives)]
                        alternatives.extend(additional)
                    
                    print(f"Attempting speech recognition (Mandarin mode) with {primary} and alternatives: {alternatives}")
                    try:
                        transcribed_text = speech_to_text(audio_content, primary, alternative_language_codes=alternatives, premium_access=True)
                        if transcribed_text and transcribed_text.strip():
                            print(f"✓ Speech recognized (Mandarin mode): {transcribed_text}")
                            break
                        else:
                            raise Exception("Recognition returned empty transcript")
                    except Exception as e:
                        error_msg = f"Recognition failed for language group starting with {primary}: {str(e)}"
                        print(error_msg)
                        recognition_errors.append(error_msg)
                        continue
            
            # If all attempts failed, send error message
            if not transcribed_text or not transcribed_text.strip():
                error_details = "\n".join(recognition_errors[-3:]) if recognition_errors else "Unknown error"  # Show last 3 errors
                print(f"All speech recognition attempts failed (Mandarin mode). Errors: {error_details}")
                send_reply(
                    event.reply_token,
                    "Could not recognize speech. Please ensure:\n"
                    "- Audio is clear and not too quiet\n"
                    "- You're speaking in a supported language\n"
                    "- Try speaking more slowly or clearly\n\n"
                    "Note: Only languages supported by Google Cloud Speech-to-Text can be recognized."
                )
                return
            
            # Translate transcribed text to Traditional Chinese using mandarin mode
            try:
                translated_text = detect_and_translate(
                    transcribed_text,
                    enabled=True,
                    source_lang=None,  # Let it auto-detect
                    target_lang="zh-TW",
                    mode="mandarin",
                    premium_access=True,
                )
                
                print(f"Translated (Mandarin mode): {transcribed_text} -> {translated_text}")
                
            except Exception as e:
                print(f"ERROR translating text (Mandarin mode): {e}")
                # Fallback: send transcribed text
                send_reply(
                    event.reply_token,
                    f"{user_identifier}:\nTranscribed: {transcribed_text}\n(Translation to Traditional Chinese failed)"
                )
                return
            
            # Send translated text
            try:
                reply_text = f"{user_identifier}:\n{translated_text}"
                send_reply(event.reply_token, reply_text)
                
                print(f"Voice translation completed (Mandarin mode)")
                print(f"Original: {transcribed_text}")
                print(f"Translated: {translated_text}")
                
            except Exception as e:
                print(f"ERROR sending reply: {e}")
                print(traceback.format_exc())
                try:
                    send_reply(event.reply_token, f"{user_identifier}:\n{translated_text}")
                except:
                    pass
            
            return
        
        # Handle japanese mode
        if mode == "japanese":
            # Japanese mode: try multiple languages to detect any language
            # Google Cloud Speech-to-Text supports up to 4 alternative languages per request
            # We'll try language groups sequentially
            
            # Try first group: Japanese + top 4 alternatives
            primary_lang = "ja-JP"
            alternative_langs = AMERICAN_MODE_LANGUAGES[:4]  # Use first 4 from the list (excluding ja-JP if present)
            # Remove ja-JP from alternatives if it's there, and ensure we have 4 alternatives
            alternative_langs = [lang for lang in alternative_langs if lang != "ja-JP"][:4]
            if len(alternative_langs) < 4:
                # Add more languages if needed
                additional = [lang for lang in AMERICAN_MODE_LANGUAGES[4:] if lang != "ja-JP"][:4-len(alternative_langs)]
                alternative_langs.extend(additional)
            
            print(f"Attempting speech recognition (Japanese mode) with {primary_lang} and alternatives: {alternative_langs}")
            try:
                transcribed_text = speech_to_text(audio_content, primary_lang, alternative_language_codes=alternative_langs, premium_access=True)
                if transcribed_text and transcribed_text.strip():
                    print(f"✓ Speech recognized (Japanese mode): {transcribed_text}")
                else:
                    raise Exception("Recognition returned empty transcript")
            except Exception as e:
                error_msg = f"Recognition failed for first language group: {str(e)}"
                print(error_msg)
                recognition_errors.append(error_msg)
                transcribed_text = None
            
            # If first group failed, try next groups (5 languages per group)
            if not transcribed_text:
                for group_start in range(0, len(AMERICAN_MODE_LANGUAGES), 5):
                    group_languages = AMERICAN_MODE_LANGUAGES[group_start:group_start + 5]
                    if not group_languages:
                        break
                    
                    # Skip if ja-JP is the primary language (we already tried it)
                    if group_languages[0] == "ja-JP":
                        continue
                    
                    primary = group_languages[0]
                    alternatives = [lang for lang in group_languages[1:5] if lang != "ja-JP"]  # Max 4 alternatives, exclude ja-JP
                    # Ensure we have alternatives
                    if len(alternatives) < 4:
                        additional = [lang for lang in AMERICAN_MODE_LANGUAGES if lang not in alternatives and lang != "ja-JP"][:4-len(alternatives)]
                        alternatives.extend(additional)
                    
                    print(f"Attempting speech recognition (Japanese mode) with {primary} and alternatives: {alternatives}")
                    try:
                        transcribed_text = speech_to_text(audio_content, primary, alternative_language_codes=alternatives, premium_access=True)
                        if transcribed_text and transcribed_text.strip():
                            print(f"✓ Speech recognized (Japanese mode): {transcribed_text}")
                            break
                        else:
                            raise Exception("Recognition returned empty transcript")
                    except Exception as e:
                        error_msg = f"Recognition failed for language group starting with {primary}: {str(e)}"
                        print(error_msg)
                        recognition_errors.append(error_msg)
                        continue
            
            # If all attempts failed, send error message
            if not transcribed_text or not transcribed_text.strip():
                error_details = "\n".join(recognition_errors[-3:]) if recognition_errors else "Unknown error"  # Show last 3 errors
                print(f"All speech recognition attempts failed (Japanese mode). Errors: {error_details}")
                send_reply(
                    event.reply_token,
                    "Could not recognize speech. Please ensure:\n"
                    "- Audio is clear and not too quiet\n"
                    "- You're speaking in a supported language\n"
                    "- Try speaking more slowly or clearly\n\n"
                    "Note: Only languages supported by Google Cloud Speech-to-Text can be recognized."
                )
                return
            
            # Translate transcribed text to Japanese using japanese mode
            try:
                translated_text = detect_and_translate(
                    transcribed_text,
                    enabled=True,
                    source_lang=None,  # Let it auto-detect
                    target_lang="ja",
                    mode="japanese",
                    premium_access=True,
                )
                
                print(f"Translated (Japanese mode): {transcribed_text} -> {translated_text}")
                
            except Exception as e:
                print(f"ERROR translating text (Japanese mode): {e}")
                # Fallback: send transcribed text
                send_reply(
                    event.reply_token,
                    f"{user_identifier}:\nTranscribed: {transcribed_text}\n(Translation to Japanese failed)"
                )
                return
            
            # Send translated text
            try:
                reply_text = f"{user_identifier}:\n{translated_text}"
                send_reply(event.reply_token, reply_text)
                
                print(f"Voice translation completed (Japanese mode)")
                print(f"Original: {transcribed_text}")
                print(f"Translated: {translated_text}")
                
            except Exception as e:
                print(f"ERROR sending reply: {e}")
                print(traceback.format_exc())
                try:
                    send_reply(event.reply_token, f"{user_identifier}:\n{translated_text}")
                except:
                    pass
            
            return
        
        # Handle pair mode (existing logic)
        # Determine source and target languages
        source_lang = settings.get("source_lang")
        target_lang = settings.get("target_lang")
        
        # Validate that languages are set
        if not source_lang or not target_lang:
            send_reply(event.reply_token, "Error: Language pair not properly configured.")
            return
        
        # Map translation language codes to Speech-to-Text language codes
        # Google Cloud Speech-to-Text uses specific locale codes
        stt_language_map = {
            "en": "en-US",
            "zh-TW": "zh-TW",
            "zh-CN": "zh-CN",
            "es": "es-ES",  # Spanish (Spain), can also use es-MX for Mexico
            "ja": "ja-JP",
            "th": "th-TH",
            "id": "id-ID",
            "fil": "fil-PH",  # Filipino (Tagalog)
            "fr": "fr-FR",
            "it": "it-IT",
            "de": "de-DE",
            "ko": "ko-KR",
            "vi": "vi-VN",
        }
        
        # Get Speech-to-Text codes for both languages
        source_stt_code = stt_language_map.get(source_lang)
        target_stt_code = stt_language_map.get(target_lang)
        
        # Validate that both languages are supported
        if not source_stt_code or not target_stt_code:
            unsupported = []
            if not source_stt_code:
                unsupported.append(source_lang)
            if not target_stt_code:
                unsupported.append(target_lang)
            send_reply(
                event.reply_token,
                f"Error: Unsupported language(s) for voice translation: {', '.join(unsupported)}\n"
                "Supported languages: en, zh-TW, zh-CN, es, ja, th, id, fil, fr, it, de, ko, vi"
            )
            return
        
        # Try both languages for speech recognition (since we don't know which one was spoken)
        # First try source language, then target language
        
        # Try source language first, with target language as alternative
        try:
            print(f"Attempting speech recognition with {source_lang} ({source_stt_code})...")
            transcribed_text = speech_to_text(audio_content, source_stt_code, alternative_language_codes=[target_stt_code], premium_access=True)
            if transcribed_text and transcribed_text.strip():
                detected_language = source_lang
                print(f"✓ Speech recognized in {source_lang}: {transcribed_text}")
            else:
                raise Exception("Recognition returned empty transcript")
        except Exception as e:
            error_msg = f"Recognition failed for {source_lang}: {str(e)}"
            print(error_msg)
            recognition_errors.append(error_msg)
            transcribed_text = None
        
        # If source language failed, try target language with source language as alternative
        if not transcribed_text:
            try:
                print(f"Attempting speech recognition with {target_lang} ({target_stt_code})...")
                transcribed_text = speech_to_text(audio_content, target_stt_code, alternative_language_codes=[source_stt_code], premium_access=True)
                if transcribed_text and transcribed_text.strip():
                    detected_language = target_lang
                    print(f"✓ Speech recognized in {target_lang}: {transcribed_text}")
                else:
                    raise Exception("Recognition returned empty transcript")
            except Exception as e2:
                error_msg = f"Recognition failed for {target_lang}: {str(e2)}"
                print(error_msg)
                recognition_errors.append(error_msg)
        
        # If both attempts failed, send error message
        if not transcribed_text or not transcribed_text.strip():
            error_details = "\n".join(recognition_errors) if recognition_errors else "Unknown error"
            print(f"All speech recognition attempts failed. Errors: {error_details}")
            # Get language names for error message
            lang_names = {
                "en": "English",
                "zh-TW": "Traditional Chinese",
                "zh-CN": "Simplified Chinese",
                "es": "Spanish",
                "ja": "Japanese",
                "th": "Thai",
                "id": "Indonesian",
                "fil": "Filipino",
                "fr": "French",
                "it": "Italian",
                "de": "German",
                "ko": "Korean",
                "vi": "Vietnamese",
            }
            source_name = lang_names.get(source_lang, source_lang)
            target_name = lang_names.get(target_lang, target_lang)
            
            send_reply(
                event.reply_token,
                f"Could not recognize speech. Please ensure:\n"
                f"- Audio is clear and not too quiet\n"
                f"- You're speaking in {source_name} or {target_name}\n"
                f"- Try speaking more slowly or clearly"
            )
            return
        
        if not transcribed_text or not transcribed_text.strip():
            send_reply(event.reply_token, "Could not transcribe audio. Please try again with clearer audio.")
            return
        
        # Translate the transcribed text
        try:
            # Determine target language for translation
            if detected_language == source_lang:
                translation_target = target_lang
            else:
                translation_target = source_lang
            
            translated_text = detect_and_translate(
                transcribed_text,
                enabled=True,
                source_lang=detected_language,
                target_lang=translation_target,
                mode="pair",
                premium_access=True,
            )
            
            print(f"Translated: {transcribed_text} -> {translated_text}")
            
        except Exception as e:
            print(f"ERROR translating text: {e}")
            # Fallback: send transcribed text
            send_reply(
                event.reply_token,
                f"{user_identifier}:\nTranscribed: {transcribed_text}\n(Translation failed)"
            )
            return
        
        # Send translated text as text message (no audio generation)
        try:
            # Format the response with original and translated text
            reply_text = f"{user_identifier}:\n{translated_text}"
            send_reply(event.reply_token, reply_text)
            
            print(f"Voice translation completed: {detected_language} -> {translation_target}")
            print(f"Original: {transcribed_text}")
            print(f"Translated: {translated_text}")
            
        except Exception as e:
            print(f"ERROR sending reply: {e}")
            print(traceback.format_exc())
            # Try to send a simpler message
            try:
                send_reply(event.reply_token, f"{user_identifier}:\n{translated_text}")
            except:
                pass  # If we can't send reply, just log the error
            
    except Exception as e:
        print(f"ERROR in handle_audio_message: {e}")
        print(traceback.format_exc())
        try:
            send_reply(event.reply_token, "An error occurred processing the audio message. Please try again.")
        except:
            pass  # If we can't send reply, just log the error

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)