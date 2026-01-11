from typing import Optional, Any
from google.cloud import speech_v1  # type: ignore
from google.cloud import texttospeech_v1  # type: ignore
import urllib.request
import urllib.error
import os
import json


# Speech-to-Text client (initialized lazily)
_speech_client: Optional[Any] = None

# Text-to-Speech client (initialized lazily)
_tts_client: Optional[Any] = None


def _get_speech_client() -> Any:
    """Get Speech-to-Text client, initializing if needed."""
    global _speech_client
    if _speech_client is None:
        try:
            _speech_client = speech_v1.SpeechClient()
        except Exception as e:
            print(f"ERROR: Failed to initialize Google Cloud Speech client: {e}")
            print("Make sure GOOGLE_APPLICATION_CREDENTIALS is set or running on GCP")
            raise
    return _speech_client


def _get_tts_client() -> Any:
    """Get Text-to-Speech client, initializing if needed."""
    global _tts_client
    if _tts_client is None:
        try:
            _tts_client = texttospeech_v1.TextToSpeechClient()
        except Exception as e:
            print(f"ERROR: Failed to initialize Google Cloud Text-to-Speech client: {e}")
            print("Make sure GOOGLE_APPLICATION_CREDENTIALS is set or running on GCP")
            raise
    return _tts_client


def speech_to_text(audio_content: bytes, language_code: str, alternative_language_codes: Optional[list[str]] = None) -> str:
    """
    Convert audio content to text using Google Cloud Speech-to-Text.
    
    Args:
        audio_content: Audio file content as bytes
        language_code: Language code (e.g., 'en-US', 'id-ID', 'zh-TW', 'es-ES', 'ja-JP', 'th-TH')
        alternative_language_codes: Optional list of alternative language codes to try for better recognition
    
    Returns:
        Transcribed text
    
    Raises:
        Exception: If speech recognition fails
    """
    try:
        client = _get_speech_client()
        
        # Use provided alternative languages, or default to empty list
        alternative_languages = alternative_language_codes or []
        
        # LINE sends audio in M4A format (AAC), but Google Cloud Speech supports various formats
        # We'll try multiple encodings and sample rates
        encodings_to_try = [
            speech_v1.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED,  # Auto-detect (try first)
            speech_v1.RecognitionConfig.AudioEncoding.MP3,
            speech_v1.RecognitionConfig.AudioEncoding.OGG_OPUS,
            speech_v1.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            speech_v1.RecognitionConfig.AudioEncoding.FLAC,
        ]
        
        # Common sample rates for LINE audio (LINE typically uses 16kHz or 48kHz)
        sample_rates_to_try = [0, 16000, 48000, 44100, 24000]  # 0 = auto-detect
        
        audio = speech_v1.RecognitionAudio(content=audio_content)
        
        # Try each combination of encoding and sample rate
        for encoding in encodings_to_try:
            for sample_rate in sample_rates_to_try:
                try:
                    # Configure recognition settings
                    # For ENCODING_UNSPECIFIED, sample_rate can be omitted or set to 0 for auto-detect
                    config_dict = {
                        "encoding": encoding,
                        "language_code": language_code,
                        "enable_automatic_punctuation": True,
                    }
                    
                    # Only set sample_rate if it's not 0 (0 means auto-detect)
                    if sample_rate > 0:
                        config_dict["sample_rate_hertz"] = sample_rate
                    
                    # Add alternative languages if available
                    if alternative_languages:
                        config_dict["alternative_language_codes"] = alternative_languages
                    
                    config = speech_v1.RecognitionConfig(**config_dict)
                    
                    response = client.recognize(config=config, audio=audio)
                    
                    if response.results:
                        # Get the first result (most confident)
                        result = response.results[0]
                        if result.alternatives:
                            transcript = result.alternatives[0].transcript.strip()
                            if transcript:  # Only return if we got actual text
                                print(f"Successfully recognized with encoding={encoding}, sample_rate={sample_rate}")
                                return transcript
                    
                    # If we get here, recognition returned no results
                    # Try next combination
                    continue
                except Exception as e:
                    # If this combination fails, try next one
                    # Only log if it's not a common "no results" error
                    if "no results" not in str(e).lower() and "empty" not in str(e).lower():
                        print(f"Warning: Speech recognition with encoding={encoding}, sample_rate={sample_rate} failed: {e}")
                    continue
        
        # If all combinations failed, raise an error with more details
        raise Exception(f"Speech recognition failed for {language_code} with all attempted encoding/sample_rate combinations")
        
    except Exception as e:
        print(f"ERROR in speech_to_text for {language_code}: {e}")
        print(f"Audio content size: {len(audio_content)} bytes")
        raise


def text_to_speech(text: str, language_code: str) -> bytes:
    """
    Convert text to speech using Google Cloud Text-to-Speech.
    
    Args:
        text: Text to convert to speech
        language_code: Language code (e.g., 'en-US', 'id-ID')
    
    Returns:
        Audio content as bytes (MP3 format)
    
    Raises:
        Exception: If TTS synthesis fails
    """
    # Select appropriate voice based on language
    # Using WaveNet voices for better quality
    voice_map = {
        'en-US': 'en-US-Wavenet-D',  # Male voice
        'id-ID': 'id-ID-Wavenet-A',   # Female voice
    }
    
    # Fallback to standard voices if WaveNet not available
    fallback_voice_map = {
        'en-US': 'en-US-Standard-D',
        'id-ID': 'id-ID-Standard-A',
    }
    
    voice_name = voice_map.get(language_code)
    if not voice_name:
        # Try to extract base language code
        base_lang = language_code.split('-')[0]
        if base_lang == 'en':
            voice_name = 'en-US-Wavenet-D'
        elif base_lang == 'id':
            voice_name = 'id-ID-Wavenet-A'
        else:
            raise ValueError(f"Unsupported language code for TTS: {language_code}")
    
    # Configure synthesis input
    synthesis_input = texttospeech_v1.SynthesisInput(text=text)
    
    # Configure audio output
    audio_config = texttospeech_v1.AudioConfig(
        audio_encoding=texttospeech_v1.AudioEncoding.MP3,
        speaking_rate=1.0,  # Normal speed
        pitch=0.0,  # Normal pitch
    )
    
    try:
        client = _get_tts_client()
        
        # Configure voice
        voice = texttospeech_v1.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
            ssml_gender=texttospeech_v1.SsmlVoiceGender.NEUTRAL,
        )
        
        # Perform synthesis
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        return response.audio_content
        
    except Exception as e:
        print(f"ERROR in text_to_speech: {e}")
        # Try with fallback voice if WaveNet fails
        if 'Wavenet' in str(e) or 'not found' in str(e).lower():
            try:
                client = _get_tts_client()
                fallback_voice = fallback_voice_map.get(language_code)
                if fallback_voice:
                    voice = texttospeech_v1.VoiceSelectionParams(
                        language_code=language_code,
                        name=fallback_voice,
                        ssml_gender=texttospeech_v1.SsmlVoiceGender.NEUTRAL,
                    )
                    response = client.synthesize_speech(
                        input=synthesis_input,
                        voice=voice,
                        audio_config=audio_config
                    )
                    return response.audio_content
            except Exception as fallback_error:
                print(f"ERROR in text_to_speech fallback: {fallback_error}")
        
        raise


def download_line_audio(message_id: str, access_token: str) -> bytes:
    """
    Download audio content from LINE Content API.
    
    Args:
        message_id: LINE message ID
        access_token: LINE channel access token
    
    Returns:
        Audio content as bytes
    
    Raises:
        Exception: If download fails
    """
    try:
        # LINE Content API endpoint
        url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                return response.read()
            else:
                raise Exception(f"Failed to download audio: HTTP {response.status}")
                
    except urllib.error.HTTPError as e:
        print(f"HTTP Error downloading LINE audio: {e.code} {e.reason}")
        raise Exception(f"Failed to download audio from LINE: {e.code} {e.reason}")
    except Exception as e:
        print(f"ERROR downloading LINE audio: {e}")
        raise


def download_messenger_audio_from_url(audio_url: str, access_token: str) -> bytes:
    """
    Download audio content directly from a URL (for Messenger attachments with direct URLs).
    
    Args:
        audio_url: Direct URL to the audio file
        access_token: Facebook page access token
    
    Returns:
        Audio content as bytes
    
    Raises:
        Exception: If download fails
    """
    try:
        req = urllib.request.Request(audio_url)
        req.add_header("Authorization", f"Bearer {access_token}")
        
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                return response.read()
            else:
                raise Exception(f"Failed to download audio from URL: HTTP {response.status}")
                
    except urllib.error.HTTPError as e:
        error_body = None
        try:
            error_body = e.read().decode()
        except:
            pass
        print(f"HTTP Error downloading Messenger audio from URL: {e.code} {e.reason}")
        if error_body:
            print(f"  Error details: {error_body}")
        raise Exception(f"Failed to download audio from URL: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        print(f"URL Error downloading Messenger audio: {e.reason}")
        raise Exception(f"Failed to download audio from URL: {e.reason}")
    except Exception as e:
        print(f"ERROR downloading Messenger audio from URL: {e}")
        raise


def download_messenger_audio(attachment_id: str, access_token: str) -> bytes:
    """
    Download audio content from Facebook Messenger Graph API using attachment ID.
    
    First fetches the attachment metadata to get the URL, then downloads the audio file.
    
    Args:
        attachment_id: Facebook attachment ID
        access_token: Facebook page access token
    
    Returns:
        Audio content as bytes
    
    Raises:
        Exception: If download fails
    """
    try:
        # First, get the attachment URL from the Graph API
        url = f"https://graph.facebook.com/v21.0/{attachment_id}?access_token={access_token}"
        
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                attachment_data = json.loads(response.read().decode())
                audio_url = attachment_data.get('url')
                
                if not audio_url:
                    raise Exception(f"No URL in attachment data. Response: {json.dumps(attachment_data)}")
                
                # Download the actual audio file using the URL
                return download_messenger_audio_from_url(audio_url, access_token)
            else:
                error_body = response.read().decode()
                raise Exception(f"Failed to get attachment info: HTTP {response.status} - {error_body}")
                
    except urllib.error.HTTPError as e:
        error_body = None
        try:
            error_body = e.read().decode()
        except:
            pass
        print(f"HTTP Error downloading Messenger audio: {e.code} {e.reason}")
        if error_body:
            print(f"  Error details: {error_body}")
        raise Exception(f"Failed to download audio from Messenger: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        print(f"URL Error downloading Messenger audio: {e.reason}")
        raise Exception(f"Failed to download audio from Messenger: {e.reason}")
    except Exception as e:
        print(f"ERROR downloading Messenger audio: {e}")
        raise

