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
    GroupSource
)
from dotenv import load_dotenv
import os
import traceback
import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, cast
from google.cloud.firestore_v1 import Client
from google.cloud.firestore_v1.base_document import DocumentSnapshot

from gcs_translate import detect_and_translate
from gcs_audio import speech_to_text, download_line_audio

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


def get_user_display_name(user_id: str) -> Optional[str]:
    """
    Get user's display name from LINE API.
    
    Returns None if profile cannot be retrieved (user not added as friend,
    user blocked the bot, or API error).
    """
    if not CHANNEL_ACCESS_TOKEN:
        return None
    
    try:
        url = f"https://api.line.me/v2/bot/profile/{user_id}"
        headers = {
            "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"
        }
        
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                profile_data = json.loads(response.read().decode())
                return profile_data.get("displayName")
    except urllib.error.HTTPError as e:
        # User might not have added bot as friend, or blocked the bot
        print(f"Could not retrieve profile for user {user_id}: {e.code} {e.reason}")
    except Exception as e:
        print(f"ERROR retrieving user profile: {e}")
    
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
    - Mode is "pair"
    - Language pair is "en" and "id" (in either direction)
    
    Args:
        settings: User or group settings dictionary
    
    Returns:
        True if voice translation should be enabled
    """
    if not settings.get("enabled", False):
        return False
    
    if settings.get("mode") != "pair":
        return False
    
    source_lang = settings.get("source_lang")
    target_lang = settings.get("target_lang")
    
    # Check if language pair is en-id or id-en
    if source_lang == "en" and target_lang == "id":
        return True
    if source_lang == "id" and target_lang == "en":
        return True
    
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
            # Try to get user's display name, fallback to user ID if unavailable
            display_name = get_user_display_name(user_id)
            user_identifier = display_name if display_name else f"User ID: {user_id}"
            reply_text = f"{user_identifier}\nTranslated: {translated}"
            send_reply(event.reply_token, reply_text)
    except Exception as e:
        print(f"ERROR in handle_message: {e}")
        print(traceback.format_exc())


@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio_message(event):
    """
    Handle audio/voice messages for voice translation.
    Only processes when:
    - Translation is enabled
    - Mode is "pair"
    - Language pair is "en id" or "id en"
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
        
        # Get user/group settings
        if group_id:
            settings = get_group_setting(group_id)
        else:
            settings = get_user_setting(user_id)
        
        # Check if voice translation is enabled
        if not is_voice_translation_enabled(settings):
            # Voice translation not enabled, send informative message
            send_reply(
                event.reply_token,
                "Voice translation is only available for English-Indonesian language pairs.\n"
                "Please set language pair to 'en id' or 'id en' using:\n"
                "/set language pair en id"
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
        
        # Determine source and target languages
        source_lang = settings.get("source_lang")
        target_lang = settings.get("target_lang")
        
        # Validate that languages are set
        if not source_lang or not target_lang:
            send_reply(event.reply_token, "Error: Language pair not properly configured.")
            return
        
        # Map to Speech-to-Text language codes
        stt_language_map = {
            "en": "en-US",
            "id": "id-ID"
        }
        
        # Try both languages for speech recognition (since we don't know which one was spoken)
        # First try source language, then target language
        source_stt_code = stt_language_map.get(source_lang, "en-US")
        target_stt_code = stt_language_map.get(target_lang, "id-ID")
        
        transcribed_text = None
        detected_language = None
        recognition_errors = []
        
        # Try source language first
        try:
            print(f"Attempting speech recognition with {source_lang} ({source_stt_code})...")
            transcribed_text = speech_to_text(audio_content, source_stt_code)
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
        
        # If source language failed, try target language
        if not transcribed_text:
            try:
                print(f"Attempting speech recognition with {target_lang} ({target_stt_code})...")
                transcribed_text = speech_to_text(audio_content, target_stt_code)
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
            send_reply(
                event.reply_token,
                "Could not recognize speech. Please ensure:\n"
                "- Audio is clear and not too quiet\n"
                "- You're speaking in English or Indonesian\n"
                "- Try speaking more slowly or clearly"
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
                f"Transcribed: {transcribed_text}\n(Translation failed)"
            )
            return
        
        # Send translated text as text message (no audio generation)
        try:
            # Format the response with original and translated text
            reply_text = f"Translated: {translated_text}"
            send_reply(event.reply_token, reply_text)
            
            print(f"Voice translation completed: {detected_language} -> {translation_target}")
            print(f"Original: {transcribed_text}")
            print(f"Translated: {translated_text}")
            
        except Exception as e:
            print(f"ERROR sending reply: {e}")
            print(traceback.format_exc())
            # Try to send a simpler message
            try:
                send_reply(event.reply_token, translated_text)
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