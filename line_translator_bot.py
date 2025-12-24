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
    GroupSource
)
from dotenv import load_dotenv
import os
import traceback
import json
from typing import Dict, Any, Optional, cast
from google.cloud.firestore_v1 import Client
from google.cloud.firestore_v1.base_document import DocumentSnapshot

from gcs_translate import detect_and_translate

load_dotenv()
CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')

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
    
    # /on translate
    if command == '/on' and len(parts) >= 2 and parts[1] == 'translate':
        return {"type": "on"}
    
    # /off translate
    if command == '/off' and len(parts) >= 2 and parts[1] == 'translate':
        return {"type": "off"}
    
    # /set language pair <source> <target>
    if command == '/set' and len(parts) >= 5 and parts[1] == 'language' and parts[2] == 'pair':
        source = parts[3]
        target = parts[4]
        return {"type": "set_pair", "source": source, "target": target}
    
    # /set american
    if command == '/set' and len(parts) >= 2 and parts[1] == 'american':
        return {"type": "set_american"}
    
    # /status
    if command == '/status':
        return {"type": "status"}
    
    return None


def send_reply(reply_token: str, text: str) -> None:
    """Send reply message to user."""
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            # LINE Bot SDK v3 uses replyToken (camelCase) in the API
            request = ReplyMessageRequest(
                replyToken=reply_token,  # type: ignore
                messages=[TextMessage(text=text)],
                quickReply=None,  # type: ignore
                quoteToken=None  # type: ignore
            )
            line_bot_api.reply_message(request)
    except Exception as e:
        print(f"ERROR sending reply: {e}")
        print(traceback.format_exc())


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
    if cmd_info["type"] == "set_pair":
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


def handle_status_command(user_id: str, reply_token: str, group_id: Optional[str] = None) -> None:
    """Handle /status command."""
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
    
    send_reply(reply_token, "\n".join(status_lines))

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
            if cmd_info["type"] == "on":
                handle_on_command(user_id, event.reply_token, group_id)
            elif cmd_info["type"] == "off":
                handle_off_command(user_id, event.reply_token, group_id)
            elif cmd_info["type"] in ["set_pair", "set_american"]:
                handle_set_command(cmd_info, user_id, event.reply_token, group_id)
            elif cmd_info["type"] == "status":
                handle_status_command(user_id, event.reply_token, group_id)
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
            reply_text = f"Original: {user_message}\nTranslated: {translated}"
            send_reply(event.reply_token, reply_text)
    except Exception as e:
        print(f"ERROR in handle_message: {e}")
        print(traceback.format_exc())

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)