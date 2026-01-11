from flask import Flask, request, abort
from dotenv import load_dotenv
import os
import traceback
import json
import urllib.request
import urllib.error
import re
import hmac
import hashlib
from typing import Dict, Any, Optional, cast
from google.cloud.firestore_v1 import Client
from google.cloud.firestore_v1.base_document import DocumentSnapshot

from gcs_translate import detect_and_translate
from gcs_audio import speech_to_text, download_messenger_audio, download_messenger_audio_from_url

load_dotenv()
PAGE_ACCESS_TOKEN = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
APP_SECRET = os.getenv('FACEBOOK_APP_SECRET')
VERIFY_TOKEN = os.getenv('FACEBOOK_VERIFY_TOKEN', 'my_verify_token_123')
APP_VERSION = os.getenv('APP_VERSION', 'unknown')

app = Flask(__name__)

# Initialize Facebook Messenger Bot
if not PAGE_ACCESS_TOKEN or not APP_SECRET:
    print("ERROR: FACEBOOK_PAGE_ACCESS_TOKEN or FACEBOOK_APP_SECRET not set!")
    print("Please set these environment variables in your .env file")
    raise ValueError("Facebook credentials not configured")

# Firestore client (initialized lazily)
# Each Facebook user has their own isolated settings stored as a separate document
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
            # both Line and Messenger bots use the same database ID line-trnsltrbt-db
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
    ensuring complete isolation between different Facebook users.
    
    Args:
        user_id: Unique Facebook user ID (used as Firestore document ID)
    
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
            print(f"DEBUG: User settings found for user_id={user_id}: {data}")
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
            print(f"DEBUG: User settings NOT found for user_id={user_id}, using defaults")
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
        user_id: Unique Facebook user ID (used as Firestore document ID)
        updates: Dictionary of settings to update
    """
    try:
        db = _get_db()
        # Isolated document per user - updates only affect this user
        doc_ref = db.collection(_COLLECTION_NAME).document(user_id)
        
        # Get current settings or use defaults
        current = get_user_setting(user_id)
        current.update(updates)
        
        print(f"DEBUG: Saving user settings for user_id={user_id}: {current}")
        # Save to Firestore
        doc_ref.set(current)
        print(f"DEBUG: User settings saved successfully for user_id={user_id}")
    except Exception as e:
        print(f"ERROR saving user settings to Firestore: {e}")
        raise


def get_thread_setting(thread_id: str) -> Dict[str, Any]:
    """
    Get thread/conversation settings from Firestore, returning defaults if not found.
    
    Args:
        thread_id: Unique Facebook thread/conversation ID
    
    Returns:
        Thread settings dictionary with defaults if not found
    """
    try:
        db = _get_db()
        # Use "thread:{thread_id}" as document ID to distinguish from user settings
        doc_id = f"thread:{thread_id}"
        doc_ref = db.collection(_COLLECTION_NAME).document(doc_id)
        doc = cast(DocumentSnapshot, doc_ref.get())
        
        if doc.exists:
            data = doc.to_dict()
            print(f"DEBUG: Thread settings found for thread_id={thread_id}: {data}")
            default_settings = {
                "enabled": False,
                "mode": "pair",
                "source_lang": None,
                "target_lang": None
            }
            default_settings.update(data or {})
            return default_settings
        else:
            print(f"DEBUG: Thread settings NOT found for thread_id={thread_id}, using defaults")
            return {
                "enabled": False,
                "mode": "pair",
                "source_lang": None,
                "target_lang": None
            }
    except Exception as e:
        print(f"ERROR loading thread settings from Firestore: {e}")
        return {
            "enabled": False,
            "mode": "pair",
            "source_lang": None,
            "target_lang": None
        }


def update_thread_setting(thread_id: str, updates: Dict[str, Any]) -> None:
    """
    Update thread/conversation settings in Firestore.
    
    Args:
        thread_id: Unique Facebook thread/conversation ID
        updates: Dictionary of settings to update
    """
    try:
        db = _get_db()
        doc_id = f"thread:{thread_id}"
        doc_ref = db.collection(_COLLECTION_NAME).document(doc_id)
        
        # Get current settings or use defaults
        current = get_thread_setting(thread_id)
        current.update(updates)
        
        print(f"DEBUG: Saving thread settings for thread_id={thread_id}: {current}")
        # Save to Firestore
        doc_ref.set(current)
        print(f"DEBUG: Thread settings saved successfully for thread_id={thread_id}")
    except Exception as e:
        print(f"ERROR saving thread settings to Firestore: {e}")
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


def get_user_display_name(user_id: str) -> Optional[str]:
    """
    Get user's display name from Facebook Graph API.
    
    Returns None if profile cannot be retrieved (user blocked the bot, or API error).
    
    Args:
        user_id: Unique Facebook user ID
    
    Returns:
        User's display name or None if unavailable
    """
    if not PAGE_ACCESS_TOKEN:
        print("ERROR: PAGE_ACCESS_TOKEN not set, cannot retrieve profile")
        return None
    
    try:
        # Facebook Graph API endpoint for user profile
        url = f"https://graph.facebook.com/v21.0/{user_id}?fields=first_name,last_name&access_token={PAGE_ACCESS_TOKEN}"
        
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                profile_data = json.loads(response.read().decode())
                first_name = profile_data.get("first_name", "")
                last_name = profile_data.get("last_name", "")
                display_name = f"{first_name} {last_name}".strip()
                if display_name:
                    print(f"✓ Retrieved display name '{display_name}' for user {user_id}")
                return display_name if display_name else None
            else:
                print(f"WARNING: Unexpected status {response.status} when retrieving profile for user {user_id}")
                return None
                
    except urllib.error.HTTPError as e:
        error_body = None
        try:
            error_body = e.read().decode()
        except:
            pass
        
        if e.code == 400:
            print(f"ERROR: Bad request when retrieving profile for user {user_id}: {e.code} {e.reason}")
            if error_body:
                print(f"  Error details: {error_body}")
        elif e.code == 401:
            print(f"ERROR: Authentication failed when retrieving profile. Check PAGE_ACCESS_TOKEN.")
        elif e.code == 403:
            print(f"ERROR: Forbidden - bot may not have permission to access profile for user {user_id}")
        elif e.code == 404:
            print(f"INFO: Profile not found for user {user_id} (user may have blocked bot or privacy settings)")
        else:
            print(f"ERROR: HTTP {e.code} {e.reason} when retrieving profile for user {user_id}")
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


def send_message(recipient_id: str, text: str) -> None:
    """Send message to user via Facebook Messenger API."""
    try:
        url = f"https://graph.facebook.com/v21.0/me/messages"
        headers = {
            "Content-Type": "application/json"
        }
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
            "messaging_type": "RESPONSE"
        }
        
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        req.add_header("Authorization", f"Bearer {PAGE_ACCESS_TOKEN}")
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                result = json.loads(response.read().decode())
                if result.get("error"):
                    print(f"ERROR sending message: {result['error']}")
                else:
                    print(f"✓ Message sent to {recipient_id}")
            else:
                print(f"ERROR sending message: HTTP {response.status}")
                error_body = response.read().decode()
                print(f"  Error details: {error_body}")
                
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if hasattr(e, 'read') else None
        print(f"ERROR sending message: HTTP {e.code} {e.reason}")
        if error_body:
            print(f"  Error details: {error_body}")
    except Exception as e:
        print(f"ERROR sending message: {e}")
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
        settings: User or thread settings dictionary
    
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


def is_emoji_only(message: str) -> bool:
    """
    Check if message contains only emojis (no regular text).
    
    Args:
        message: The message text to check
    
    Returns:
        True if message contains only emojis, False otherwise
    """
    # Remove whitespace
    stripped = message.strip()
    
    # Empty message is considered emoji-only
    if not stripped:
        return True
    
    # Regex pattern for emoji Unicode ranges
    emoji_pattern = re.compile(
        r'^[\U0001F300-\U0001F9FF\U00002600-\U000026FF\U00002700-\U000027BF'
        r'\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
        r'\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U0000200D'
        r'\U0000FE00-\U0000FE0F\U0001F3FB-\U0001F3FF\U000020E3\s]*$',
        re.UNICODE
    )
    
    # Check if the entire message matches emoji pattern
    return bool(emoji_pattern.match(stripped))


def handle_set_command(cmd_info: Dict[str, Any], user_id: str, thread_id: Optional[str] = None) -> None:
    """Handle /set commands."""
    if cmd_info["type"] == "set_on":
        # /set on - enable translation
        if thread_id:
            update_thread_setting(thread_id, {"enabled": True})
            send_message(user_id, "Translation enabled for this conversation ✓")
        else:
            update_user_setting(user_id, {"enabled": True})
            send_message(user_id, "Translation enabled ✓")
    
    elif cmd_info["type"] == "set_off":
        # /set off - disable translation
        if thread_id:
            update_thread_setting(thread_id, {"enabled": False})
            send_message(user_id, "Translation disabled for this conversation ✓")
        else:
            update_user_setting(user_id, {"enabled": False})
            send_message(user_id, "Translation disabled ✓")
    
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
            send_message(user_id, f"Invalid source language code: {source_input}\nSupported: {supported}")
            return
        
        if target not in supported_codes:
            supported = ", ".join(supported_codes)
            send_message(user_id, f"Invalid target language code: {target_input}\nSupported: {supported}")
            return
        
        # Use Google Cloud codes directly (now properly normalized)
        settings_update = {
            "enabled": True,
            "mode": "pair",
            "source_lang": source,
            "target_lang": target
        }
        if thread_id:
            update_thread_setting(thread_id, settings_update)
            send_message(user_id, f"Language pair set for this conversation: {source} → {target} ✓")
        else:
            update_user_setting(user_id, settings_update)
            send_message(user_id, f"Language pair set: {source} → {target} ✓")
    
    elif cmd_info["type"] == "set_american":
        settings_update = {
            "enabled": True,
            "mode": "american",
            "source_lang": None,
            "target_lang": "en-US"
        }
        if thread_id:
            update_thread_setting(thread_id, settings_update)
            send_message(user_id, "American mode enabled for this conversation ✓\nAll detected languages will be translated to American English.")
        else:
            update_user_setting(user_id, settings_update)
            send_message(user_id, "American mode enabled ✓\nAll detected languages will be translated to American English.")
    
    elif cmd_info["type"] == "set_mandarin":
        settings_update = {
            "enabled": True,
            "mode": "mandarin",
            "source_lang": None,
            "target_lang": "zh-TW"
        }
        if thread_id:
            update_thread_setting(thread_id, settings_update)
            send_message(user_id, "Mandarin mode enabled for this conversation ✓\nAll detected languages will be translated to Traditional Chinese (Taiwan).")
        else:
            update_user_setting(user_id, settings_update)
            send_message(user_id, "Mandarin mode enabled ✓\nAll detected languages will be translated to Traditional Chinese (Taiwan).")
    
    elif cmd_info["type"] == "set_japanese":
        settings_update = {
            "enabled": True,
            "mode": "japanese",
            "source_lang": None,
            "target_lang": "ja"
        }
        if thread_id:
            update_thread_setting(thread_id, settings_update)
            send_message(user_id, "Japanese mode enabled for this conversation ✓\nAll detected languages will be translated to Japanese.")
        else:
            update_user_setting(user_id, settings_update)
            send_message(user_id, "Japanese mode enabled ✓\nAll detected languages will be translated to Japanese.")


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


def handle_status_command(user_id: str, thread_id: Optional[str] = None, status_type: str = "status") -> None:
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
        send_message(user_id, "\n".join(version_info))
        return
    
    if status_type == "status_help":
        # Display help information
        help_text = [
            "Add TranslatorBot to a conversation and enable translation with following commands:",
            "",
            "Commands start with /",
            "/set on - enables translation for user",
            "/set off - disables translation for user",
            "/set language pair <source> <target> - sets specific language pair (e.g., /set language pair zh-tw en)",
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
        send_message(user_id, "\n".join(help_text))
        return
    
    # Regular status command
    if thread_id:
        settings = get_thread_setting(thread_id)
        status_lines = ["Current Conversation Translation Settings:"]
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
    
    send_message(user_id, "\n".join(status_lines))


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """
    Verify Facebook webhook signature.
    
    Args:
        payload: Raw request body
        signature: X-Hub-Signature-256 header value (format: "sha256=...")
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not signature or not APP_SECRET:
        return False
    
    # Extract hash from signature (format: "sha256=HASH")
    if not signature.startswith("sha256="):
        return False
    
    expected_hash = signature[7:]  # Remove "sha256=" prefix
    
    # Calculate HMAC SHA256
    calculated_hash = hmac.new(
        APP_SECRET.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    # Compare hashes (constant-time comparison)
    return hmac.compare_digest(expected_hash, calculated_hash)


@app.route("/webhook", methods=['GET'])
def webhook_verify():
    """Handle webhook verification (GET request from Facebook)."""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge', '')
    
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        print("Webhook verified successfully")
        return challenge, 200
    else:
        print(f"Webhook verification failed: mode={mode}, token={token}")
        abort(403)


@app.route("/webhook", methods=['POST'])
def webhook():
    """Handle webhook events (POST request from Facebook)."""
    # Verify signature
    signature = request.headers.get('X-Hub-Signature-256', '')
    body = request.get_data()
    
    if not verify_webhook_signature(body, signature):
        print("Invalid webhook signature")
        abort(403)
    
    try:
        data = json.loads(body.decode('utf-8'))
        
        # Facebook sends events in entry array
        if 'object' in data and data['object'] == 'page':
            for entry in data.get('entry', []):
                # Process messaging events
                for event in entry.get('messaging', []):
                    handle_messaging_event(event)
        
        return 'OK', 200
        
    except Exception as e:
        print(f"ERROR in webhook handler: {e}")
        print(traceback.format_exc())
        abort(500)


def handle_messaging_event(event: Dict[str, Any]) -> None:
    """Handle a messaging event from Facebook."""
    try:
        sender_id = event.get('sender', {}).get('id')
        recipient_id = event.get('recipient', {}).get('id')
        
        if not sender_id:
            print("WARNING: No sender ID in event")
            return
        
        # Get thread ID if available (for group conversations)
        thread_id = None
        if 'thread' in event:
            thread_id = event['thread'].get('thread_id')
            print(f"DEBUG: Thread ID found in event: {thread_id}")
        else:
            print(f"DEBUG: No thread ID in event (1-on-1 conversation)")
        
        # Handle message events
        if 'message' in event:
            message = event['message']
            
            # Handle text messages
            if 'text' in message:
                handle_text_message(sender_id, message['text'], thread_id)
            
            # Handle audio/voice messages
            # Facebook Messenger sends audio as either 'audio' or 'file' type
            elif 'attachments' in message:
                for attachment in message['attachments']:
                    attachment_type = attachment.get('type', '').lower()
                    if attachment_type == 'audio' or (attachment_type == 'file' and 'audio' in attachment.get('mime_type', '').lower()):
                        handle_audio_message(sender_id, attachment, thread_id)
                        break  # Process only the first audio attachment
        
        # Handle postback events (button clicks, etc.)
        elif 'postback' in event:
            # Handle postback if needed
            pass
            
    except Exception as e:
        print(f"ERROR in handle_messaging_event: {e}")
        print(traceback.format_exc())


def handle_text_message(user_id: str, message_text: str, thread_id: Optional[str] = None) -> None:
    """Handle incoming text message."""
    try:
        # Check if message is a switch command
        cmd_info = parse_switch_command(message_text)
        if cmd_info:
            if cmd_info["type"] in ["set_on", "set_off", "set_pair", "set_american", "set_mandarin", "set_japanese"]:
                handle_set_command(cmd_info, user_id, thread_id)
            elif cmd_info["type"] in ["status", "status_version", "status_help"]:
                handle_status_command(user_id, thread_id, cmd_info["type"])
            return
        
        # Skip translation if message contains only emojis
        if is_emoji_only(message_text):
            print(f"Skipping translation for emoji-only message from user {user_id}")
            return
        
        # Not a command, apply translation based on settings
        # In group conversations, use thread settings; otherwise use user settings
        print(f"DEBUG: handle_text_message - user_id={user_id}, thread_id={thread_id}")
        if thread_id:
            settings = get_thread_setting(thread_id)
            print(f"DEBUG: Using thread settings for thread_id={thread_id}: enabled={settings.get('enabled')}, mode={settings.get('mode')}")
        else:
            settings = get_user_setting(user_id)
            print(f"DEBUG: Using user settings for user_id={user_id}: enabled={settings.get('enabled')}, mode={settings.get('mode')}")
        
        translated = detect_and_translate(
            message_text,
            enabled=settings["enabled"],
            source_lang=settings.get("source_lang"),
            target_lang=settings.get("target_lang"),
            mode=settings.get("mode", "pair")
        )
        
        # Only send reply if translation occurred and is different from original
        if translated != message_text and settings["enabled"]:
            # Try to get user's display name, fallback to user ID if unavailable
            display_name = get_user_display_name(user_id)
            user_identifier = display_name if display_name else f"User ID: {user_id}"
            reply_text = f"{user_identifier}:\n{translated}"
            send_message(user_id, reply_text)
            
    except Exception as e:
        print(f"ERROR in handle_text_message: {e}")
        print(traceback.format_exc())




def handle_audio_message(user_id: str, attachment: Dict[str, Any], thread_id: Optional[str] = None) -> None:
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
        # Get user/thread settings
        print(f"DEBUG: handle_audio_message - user_id={user_id}, thread_id={thread_id}")
        if thread_id:
            settings = get_thread_setting(thread_id)
            print(f"DEBUG: Using thread settings for thread_id={thread_id}: enabled={settings.get('enabled')}, mode={settings.get('mode')}")
        else:
            settings = get_user_setting(user_id)
            print(f"DEBUG: Using user settings for user_id={user_id}: enabled={settings.get('enabled')}, mode={settings.get('mode')}")
        
        # Get user's display name for reply messages (fallback to user ID if unavailable)
        display_name = get_user_display_name(user_id)
        user_identifier = display_name if display_name else f"User ID: {user_id}"
        
        # Check if voice translation is enabled
        if not is_voice_translation_enabled(settings):
            # Voice translation not enabled, send informative message
            mode = settings.get("mode")
            source_lang = settings.get("source_lang")
            target_lang = settings.get("target_lang")
            
            if mode == "american":
                send_message(
                    user_id,
                    "Voice translation is not enabled.\n"
                    "Please enable translation using:\n"
                    "/set american"
                )
            elif mode == "mandarin":
                send_message(
                    user_id,
                    "Voice translation is not enabled.\n"
                    "Please enable translation using:\n"
                    "/set mandarin"
                )
            elif mode == "japanese":
                send_message(
                    user_id,
                    "Voice translation is not enabled.\n"
                    "Please enable translation using:\n"
                    "/set japanese"
                )
            elif not source_lang or not target_lang:
                send_message(
                    user_id,
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
                send_message(
                    user_id,
                    f"Voice translation is not enabled or language pair ({source_lang} → {target_lang}) is not supported.\n"
                    "Please ensure translation is enabled and both languages are supported.\n\n"
                    "Supported languages: en, zh-TW, es, ja, th, id\n"
                    "Or use American mode: /set american\n"
                    "Or use Mandarin mode: /set mandarin\n"
                    "Or use Japanese mode: /set japanese"
                )
            return
        
        # Debug: Log the attachment structure to understand the format
        print(f"DEBUG: Audio attachment structure: {json.dumps(attachment, indent=2)}")
        
        # Facebook Messenger audio attachments can come in different formats:
        # 1. Direct URL in payload: {"payload": {"url": "https://..."}}
        # 2. Attachment ID in payload: {"payload": {"attachment_id": "..."}}
        # 3. ID field at root: {"id": "..."}
        payload = attachment.get('payload', {})
        attachment_url = payload.get('url')
        attachment_id = payload.get('attachment_id') or attachment.get('id')
        
        # Check if access token is available
        if not PAGE_ACCESS_TOKEN:
            print("ERROR: PAGE_ACCESS_TOKEN not set, cannot download audio")
            send_message(user_id, "Error: Bot configuration error. Please contact administrator.")
            return
        
        # Try to download audio - either directly from URL or via attachment ID
        try:
            if attachment_url:
                # Direct URL provided - download directly
                print(f"DEBUG: Using direct URL: {attachment_url}")
                audio_content = download_messenger_audio_from_url(attachment_url, PAGE_ACCESS_TOKEN)
            elif attachment_id:
                # Attachment ID provided - fetch URL first then download
                print(f"DEBUG: Using attachment ID: {attachment_id}")
                audio_content = download_messenger_audio(attachment_id, PAGE_ACCESS_TOKEN)
            else:
                # Neither URL nor ID found
                error_msg = f"Error: Could not get audio attachment ID or URL. Attachment structure: {json.dumps(attachment, indent=2)}"
                print(error_msg)
                send_message(user_id, "Error: Could not get audio attachment. Please try sending the audio message again.")
                return
        except Exception as e:
            print(f"ERROR downloading audio: {e}")
            print(f"DEBUG: Attachment that failed: {json.dumps(attachment, indent=2)}")
            send_message(user_id, "Could not download audio. Please try again.")
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
                send_message(
                    user_id,
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
                send_message(
                    user_id,
                    f"{user_identifier}:\nTranscribed: {transcribed_text}\n(Translation to English failed)"
                )
                return
            
            # Send translated text
            try:
                reply_text = f"{user_identifier}:\n{translated_text}"
                send_message(user_id, reply_text)
                
                print(f"Voice translation completed (American mode)")
                print(f"Original: {transcribed_text}")
                print(f"Translated: {translated_text}")
                
            except Exception as e:
                print(f"ERROR sending reply: {e}")
                print(traceback.format_exc())
            
            return
        
        # Handle mandarin mode (similar to american mode)
        if mode == "mandarin":
            # Mandarin mode: try multiple languages to detect any language
            primary_lang = "zh-TW"
            alternative_langs = [lang for lang in AMERICAN_MODE_LANGUAGES[:4] if lang != "zh-TW"][:4]
            if len(alternative_langs) < 4:
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
            
            # If first group failed, try next groups
            if not transcribed_text:
                for group_start in range(0, len(AMERICAN_MODE_LANGUAGES), 5):
                    group_languages = AMERICAN_MODE_LANGUAGES[group_start:group_start + 5]
                    if not group_languages:
                        break
                    
                    if group_languages[0] == "zh-TW" and group_start == 0:
                        continue
                    
                    primary = group_languages[0]
                    alternatives = [lang for lang in group_languages[1:5] if lang != "zh-TW"][:4]
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
                error_details = "\n".join(recognition_errors[-3:]) if recognition_errors else "Unknown error"
                print(f"All speech recognition attempts failed (Mandarin mode). Errors: {error_details}")
                send_message(
                    user_id,
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
                send_message(
                    user_id,
                    f"{user_identifier}:\nTranscribed: {transcribed_text}\n(Translation to Traditional Chinese failed)"
                )
                return
            
            # Send translated text
            try:
                reply_text = f"{user_identifier}:\n{translated_text}"
                send_message(user_id, reply_text)
                
                print(f"Voice translation completed (Mandarin mode)")
                print(f"Original: {transcribed_text}")
                print(f"Translated: {translated_text}")
                
            except Exception as e:
                print(f"ERROR sending reply: {e}")
                print(traceback.format_exc())
            
            return
        
        # Handle japanese mode (similar to american mode)
        if mode == "japanese":
            # Japanese mode: try multiple languages to detect any language
            primary_lang = "ja-JP"
            alternative_langs = [lang for lang in AMERICAN_MODE_LANGUAGES[:4] if lang != "ja-JP"][:4]
            if len(alternative_langs) < 4:
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
            
            # If first group failed, try next groups
            if not transcribed_text:
                for group_start in range(0, len(AMERICAN_MODE_LANGUAGES), 5):
                    group_languages = AMERICAN_MODE_LANGUAGES[group_start:group_start + 5]
                    if not group_languages:
                        break
                    
                    if group_languages[0] == "ja-JP":
                        continue
                    
                    primary = group_languages[0]
                    alternatives = [lang for lang in group_languages[1:5] if lang != "ja-JP"][:4]
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
                error_details = "\n".join(recognition_errors[-3:]) if recognition_errors else "Unknown error"
                print(f"All speech recognition attempts failed (Japanese mode). Errors: {error_details}")
                send_message(
                    user_id,
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
                send_message(
                    user_id,
                    f"{user_identifier}:\nTranscribed: {transcribed_text}\n(Translation to Japanese failed)"
                )
                return
            
            # Send translated text
            try:
                reply_text = f"{user_identifier}:\n{translated_text}"
                send_message(user_id, reply_text)
                
                print(f"Voice translation completed (Japanese mode)")
                print(f"Original: {transcribed_text}")
                print(f"Translated: {translated_text}")
                
            except Exception as e:
                print(f"ERROR sending reply: {e}")
                print(traceback.format_exc())
            
            return
        
        # Handle pair mode (existing logic)
        # Determine source and target languages
        source_lang = settings.get("source_lang")
        target_lang = settings.get("target_lang")
        
        # Validate that languages are set
        if not source_lang or not target_lang:
            send_message(user_id, "Error: Language pair not properly configured.")
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
            send_message(
                user_id,
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
            
            send_message(
                user_id,
                f"Could not recognize speech. Please ensure:\n"
                f"- Audio is clear and not too quiet\n"
                f"- You're speaking in {source_name} or {target_name}\n"
                f"- Try speaking more slowly or clearly"
            )
            return
        
        if not transcribed_text or not transcribed_text.strip():
            send_message(user_id, "Could not transcribe audio. Please try again with clearer audio.")
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
            send_message(
                user_id,
                f"{user_identifier}:\nTranscribed: {transcribed_text}\n(Translation failed)"
            )
            return
        
        # Send translated text as text message (no audio generation)
        try:
            # Format the response with original and translated text
            reply_text = f"{user_identifier}:\n{translated_text}"
            send_message(user_id, reply_text)
            
            print(f"Voice translation completed: {detected_language} -> {translation_target}")
            print(f"Original: {transcribed_text}")
            print(f"Translated: {translated_text}")
            
        except Exception as e:
            print(f"ERROR sending reply: {e}")
            print(traceback.format_exc())
            
    except Exception as e:
        print(f"ERROR in handle_audio_message: {e}")
        print(traceback.format_exc())
        try:
            send_message(user_id, "An error occurred processing the audio message. Please try again.")
        except:
            pass  # If we can't send reply, just log the error


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
