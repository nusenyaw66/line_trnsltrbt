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

from gcs_translate import detect_and_translate
from gcs_audio import speech_to_text, download_line_audio

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

# Common languages for american mode (prioritized list)
# Google Cloud Speech-to-Text language codes for multi-language recognition
# These are used when mode is "american" to detect any language and translate to English
AMERICAN_MODE_LANGUAGES = [
    "en-US",      # English (most common)
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
    "zh-CN",      # Chinese (Simplified)
    "ru-RU",      # Russian
    "ar-XA",      # Arabic
    "hi-IN",      # Hindi
    "th-TH",      # Thai
    "id-ID",      # Indonesian
    "vi-VN",      # Vietnamese
    "nl-NL",      # Dutch
    "pl-PL",      # Polish
    "tr-TR",      # Turkish
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
    
    Args:
        user_id: Unique LINE user ID (used as Firestore document ID)
    
    Returns:
        User settings dictionary with defaults if not found
    """
    try:
        db = _get_db()
        # Each user_id gets its own document - complete isolation
        doc_ref = db.collection(_COLLECTION_NAME).document(user_id)
        # Synchronous API - get() returns DocumentSnapshot directly (not awaitable)
        # Type cast needed because type checker incorrectly infers Awaitable
        doc = cast(DocumentSnapshot, doc_ref.get())
        
        if doc.exists:
            data = doc.to_dict()
            # Ensure all fields are present
            default_settings = {
                "enabled": False,
                "mode": "pair",
                "source_lang": None,
                "target_lang": None
            }
            default_settings.update(data or {})
            return default_settings
        else:
            # Return defaults for new users
            return {
                "enabled": False,
                "mode": "pair",
                "source_lang": None,
                "target_lang": None
            }
    except Exception as e:
        print(f"ERROR loading user settings from Firestore: {e}")
        # Return defaults on error
        return {
            "enabled": False,
            "mode": "pair",
            "source_lang": None,
            "target_lang": None
        }


def update_user_setting(user_id: str, updates: Dict[str, Any]) -> None:
    """
    Update user settings in Firestore.
    
    Updates are isolated to the specific user_id - no other users' data is affected.
    
    Args:
        user_id: Unique LINE user ID (used as Firestore document ID)
        updates: Dictionary of settings to update
    """
    try:
        db = _get_db()
        # Isolated document per user - updates only affect this user
        doc_ref = db.collection(_COLLECTION_NAME).document(user_id)
        
        # Get current settings or use defaults
        current = get_user_setting(user_id)
        current.update(updates)
        
        # Save to Firestore
        doc_ref.set(current)
    except Exception as e:
        print(f"ERROR saving user settings to Firestore: {e}")
        raise


def get_group_setting(group_id: str) -> Dict[str, Any]:
    """
    Get group settings from Firestore, returning defaults if not found.
    
    Args:
        group_id: Unique LINE group ID
    
    Returns:
        Group settings dictionary with defaults if not found
    """
    try:
        db = _get_db()
        # Use "group:{group_id}" as document ID to distinguish from user settings
        doc_id = f"group:{group_id}"
        doc_ref = db.collection(_COLLECTION_NAME).document(doc_id)
        doc = cast(DocumentSnapshot, doc_ref.get())
        
        if doc.exists:
            data = doc.to_dict()
            default_settings = {
                "enabled": False,
                "mode": "pair",
                "source_lang": None,
                "target_lang": None
            }
            default_settings.update(data or {})
            return default_settings
        else:
            return {
                "enabled": False,
                "mode": "pair",
                "source_lang": None,
                "target_lang": None
            }
    except Exception as e:
        print(f"ERROR loading group settings from Firestore: {e}")
        return {
            "enabled": False,
            "mode": "pair",
            "source_lang": None,
            "target_lang": None
        }


def update_group_setting(group_id: str, updates: Dict[str, Any]) -> None:
    """
    Update group settings in Firestore.
    
    Args:
        group_id: Unique LINE group ID
        updates: Dictionary of settings to update
    """
    try:
        db = _get_db()
        doc_id = f"group:{group_id}"
        doc_ref = db.collection(_COLLECTION_NAME).document(doc_id)
        
        # Get current settings or use defaults
        current = get_group_setting(group_id)
        current.update(updates)
        
        # Save to Firestore
        doc_ref.set(current)
    except Exception as e:
        print(f"ERROR saving group settings to Firestore: {e}")
        raise


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
        # /set language pair <source> <target>
        elif len(parts) >= 5 and parts[1] == 'language' and parts[2] == 'pair':
            source = parts[3]
            target = parts[4]
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
    
    # /status
    if command == '/status':
        if len(parts) >= 2 and parts[1] == 'version':
            return {"type": "status_version"}
        elif len(parts) >= 2 and parts[1] == 'help':
            return {"type": "status_help"}
        return {"type": "status"}
    
    return None


def get_user_display_name(user_id: str, group_id: Optional[str] = None) -> Optional[str]:
    """
    Get user's display name from LINE API.
    
    For group chats, uses the group member profile endpoint.
    For individual chats, uses the user profile endpoint.
    
    Returns None if profile cannot be retrieved (user not added as friend,
    user blocked the bot, or API error).
    
    Args:
        user_id: Unique LINE user ID
        group_id: Optional group ID for group chat contexts
    
    Returns:
        User's display name or None if unavailable
    """
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
        supported_languages = ["en", "zh-TW", "es", "ja", "th", "id"]
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

def handle_on_command(user_id: str, reply_token: str, group_id: Optional[str] = None) -> None:
    """Handle /on translate command."""
    if group_id:
        update_group_setting(group_id, {"enabled": True})
        send_reply(reply_token, "Translation enabled for this group ✓")
    else:
        update_user_setting(user_id, {"enabled": True})
        send_reply(reply_token, "Translation enabled ✓")


def handle_off_command(user_id: str, reply_token: str, group_id: Optional[str] = None) -> None:
    """Handle /off translate command."""
    if group_id:
        update_group_setting(group_id, {"enabled": False})
        send_reply(reply_token, "Translation disabled for this group ✓")
    else:
        update_user_setting(user_id, {"enabled": False})
        send_reply(reply_token, "Translation disabled ✓")


def normalize_language_code(code: str) -> str:
    """Normalize language code to Google Cloud format (case-insensitive input)."""
    code_lower = code.lower()
    # Map lowercase inputs to proper Google Cloud format
    code_map = {
        "en": "en",
        "zh-tw": "zh-TW",
        "zh-cn": "zh-TW",  # Map zh-cn to zh-TW (we only support Traditional Chinese)
        "es": "es",
        "ja": "ja",
        "jpn": "ja",  # Also accept jpn
        "th": "th",
        "id": "id",
        "ind": "id"  # Also accept ind
    }
    return code_map.get(code_lower, code)  # Return original if not in map


def handle_set_command(cmd_info: Dict[str, Any], user_id: str, reply_token: str, group_id: Optional[str] = None) -> None:
    """Handle /set commands."""
    if cmd_info["type"] == "set_on":
        # /set on - enable translation
        if group_id:
            update_group_setting(group_id, {"enabled": True})
            send_reply(reply_token, "Translation enabled for this group ✓")
        else:
            update_user_setting(user_id, {"enabled": True})
            send_reply(reply_token, "Translation enabled ✓")
    
    elif cmd_info["type"] == "set_off":
        # /set off - disable translation
        if group_id:
            update_group_setting(group_id, {"enabled": False})
            send_reply(reply_token, "Translation disabled for this group ✓")
        else:
            update_user_setting(user_id, {"enabled": False})
            send_reply(reply_token, "Translation disabled ✓")
    
    elif cmd_info["type"] == "set_pair":
        source_input = cmd_info["source"]
        target_input = cmd_info["target"]
        
        # Normalize to proper Google Cloud format (case-insensitive)
        source = normalize_language_code(source_input)
        target = normalize_language_code(target_input)
        
        # Supported Google Cloud language codes (proper format)
        supported_codes = ["en", "zh-TW", "es", "ja", "th", "id"]
        
        # Validate language codes
        if source not in supported_codes:
            supported = ", ".join(supported_codes)
            send_reply(reply_token, f"Invalid source language code: {source_input}\nSupported: {supported}")
            return
        
        if target not in supported_codes:
            supported = ", ".join(supported_codes)
            send_reply(reply_token, f"Invalid target language code: {target_input}\nSupported: {supported}")
            return
        
        # Use Google Cloud codes directly (now properly normalized)
        settings_update = {
            "enabled": True,
            "mode": "pair",
            "source_lang": source,
            "target_lang": target
        }
        if group_id:
            update_group_setting(group_id, settings_update)
            send_reply(reply_token, f"Language pair set for this group: {source} → {target} ✓")
        else:
            update_user_setting(user_id, settings_update)
            send_reply(reply_token, f"Language pair set: {source} → {target} ✓")
    
    elif cmd_info["type"] == "set_american":
        settings_update = {
            "enabled": True,
            "mode": "american",
            "source_lang": None,
            "target_lang": "en-US"
        }
        if group_id:
            update_group_setting(group_id, settings_update)
            send_reply(reply_token, "American mode enabled for this group ✓\nAll detected languages will be translated to American English.")
        else:
            update_user_setting(user_id, settings_update)
            send_reply(reply_token, "American mode enabled ✓\nAll detected languages will be translated to American English.")
    
    elif cmd_info["type"] == "set_mandarin":
        settings_update = {
            "enabled": True,
            "mode": "mandarin",
            "source_lang": None,
            "target_lang": "zh-TW"
        }
        if group_id:
            update_group_setting(group_id, settings_update)
            send_reply(reply_token, "Mandarin mode enabled for this group ✓\nAll detected languages will be translated to Traditional Chinese (Taiwan).")
        else:
            update_user_setting(user_id, settings_update)
            send_reply(reply_token, "Mandarin mode enabled ✓\nAll detected languages will be translated to Traditional Chinese (Taiwan).")
    
    elif cmd_info["type"] == "set_japanese":
        settings_update = {
            "enabled": True,
            "mode": "japanese",
            "source_lang": None,
            "target_lang": "ja"
        }
        if group_id:
            update_group_setting(group_id, settings_update)
            send_reply(reply_token, "Japanese mode enabled for this group ✓\nAll detected languages will be translated to Japanese.")
        else:
            update_user_setting(user_id, settings_update)
            send_reply(reply_token, "Japanese mode enabled ✓\nAll detected languages will be translated to Japanese.")


def handle_status_command(user_id: str, reply_token: str, group_id: Optional[str] = None, status_type: str = "status") -> None:
    """Handle /status command."""
    if status_type == "status_version":
        # Display version info
        version_info = [
            "Version Information:",
            f"TranslatorBot App Version: {APP_VERSION}",
            "Google Cloud API Version: 2.21.0",
            "",
            "Tesseract Technologies LLC, Meridian ID, USA"
        ]
        send_reply(reply_token, "\n".join(version_info))
        return
    
    if status_type == "status_help":
        # Display help information
        help_text = [
            "Add TranslatorBot to a group chat and enable translation for the group with following commands:",
            "",
            "Commands start with /",
            "/set on - enables translation for user",
            "/set off - disables translation for user",
            "/set language pair <source> <target> - sets specific language pair (e.g., /set language pair tc eng)",
            "/set american - sets mode to translate all languages to American English",
            "/set mandarin - sets mode to translate all languages to Traditional Chinese (Taiwan)",
            "/set japanese - sets mode to translate all languages to Japanese",
            "/status - returns current user settings",
            "/status version",
            "/status help",
            "",
            "Language options for /set language pair <source> <target>",
            '"en": "en",',
            '"zh-tw": "zh-TW",',
            '"zh-cn": "zh-TW",  # Map zh-cn to zh-TW (we only support Traditional Chinese)',
            '"es": "es",',
            '"ja": "ja",',
            '"jpn": "ja",  # Also accepts jpn',
            '"th": "th",',
            '"id": "id",',
            '"ind": "id"  # Also accepts ind',
            "",
            "Voice-to-text is only available to paid customers!",
            "See: https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types for supported languages."
           
        ]
        send_reply(reply_token, "\n".join(help_text))
        return
    
    # Regular status command
    if group_id:
        settings = get_group_setting(group_id)
        status_lines = ["Current Group Translation Settings:"]
    else:
        settings = get_user_setting(user_id)
        status_lines = ["Current Translation Settings:"]
    
    status_lines.append(f"Enabled: {'Yes' if settings['enabled'] else 'No'}")
    status_lines.append(f"Mode: {settings['mode']}")
    
    if settings['mode'] == 'pair':
        source = settings.get('source_lang', 'Not set')
        target = settings.get('target_lang', 'Not set')
        status_lines.append(f"Source: {source}")
        status_lines.append(f"Target: {target}")
    elif settings['mode'] == 'american':
        status_lines.append("Target: American English (en-US)")
    elif settings['mode'] == 'mandarin':
        status_lines.append("Target: Traditional Chinese (zh-TW)")
    elif settings['mode'] == 'japanese':
        status_lines.append("Target: Japanese (ja)")
    
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

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
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
        
        # Check if this is a group chat
        group_id = None
        if isinstance(event.source, GroupSource):
            group_id = event.source.group_id
            print(f"Message received in group: {group_id} from user: {user_id}")
        
        # Check if message is a switch command
        cmd_info = parse_switch_command(user_message)
        if cmd_info:
            if cmd_info["type"] in ["set_on", "set_off", "set_pair", "set_american", "set_mandarin", "set_japanese"]:
                handle_set_command(cmd_info, user_id, event.reply_token, group_id)
            elif cmd_info["type"] in ["status", "status_version", "status_help"]:
                handle_status_command(user_id, event.reply_token, group_id, cmd_info["type"])
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
        
        translated = detect_and_translate(
            user_message,
            enabled=settings["enabled"],
            source_lang=settings.get("source_lang"),
            target_lang=settings.get("target_lang"),
            mode=settings.get("mode", "pair")
        )
        
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
                    "/set language pair <source> <target>\n\n"
                    "Or use American mode:\n"
                    "/set american\n\n"
                    "Or use Mandarin mode:\n"
                    "/set mandarin\n\n"
                    "Or use Japanese mode:\n"
                    "/set japanese\n\n"
                    "Supported languages for pair mode: en, zh-TW, es, ja, th, id"
                )
            else:
                send_reply(
                    event.reply_token,
                    f"Voice translation is not enabled or language pair ({source_lang} → {target_lang}) is not supported.\n"
                    "Please ensure translation is enabled and both languages are supported.\n\n"
                    "Supported languages: en, zh-TW, es, ja, th, id\n"
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
                transcribed_text = speech_to_text(audio_content, primary_lang, alternative_language_codes=alternative_langs)
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
                        transcribed_text = speech_to_text(audio_content, primary, alternative_language_codes=alternatives)
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
                    mode="american"
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
                transcribed_text = speech_to_text(audio_content, primary_lang, alternative_language_codes=alternative_langs)
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
                        transcribed_text = speech_to_text(audio_content, primary, alternative_language_codes=alternatives)
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
                    mode="mandarin"
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
                transcribed_text = speech_to_text(audio_content, primary_lang, alternative_language_codes=alternative_langs)
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
                        transcribed_text = speech_to_text(audio_content, primary, alternative_language_codes=alternatives)
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
                    mode="japanese"
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
            "es": "es-ES",  # Spanish (Spain), can also use es-MX for Mexico
            "ja": "ja-JP",
            "th": "th-TH",
            "id": "id-ID"
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
                "Supported languages: en, zh-TW, es, ja, th, id"
            )
            return
        
        # Try both languages for speech recognition (since we don't know which one was spoken)
        # First try source language, then target language
        
        # Try source language first, with target language as alternative
        try:
            print(f"Attempting speech recognition with {source_lang} ({source_stt_code})...")
            transcribed_text = speech_to_text(audio_content, source_stt_code, alternative_language_codes=[target_stt_code])
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
                transcribed_text = speech_to_text(audio_content, target_stt_code, alternative_language_codes=[source_stt_code])
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
                "es": "Spanish",
                "ja": "Japanese",
                "th": "Thai",
                "id": "Indonesian"
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
                mode="pair"
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