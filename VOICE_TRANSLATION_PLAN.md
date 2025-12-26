# Voice Translation Feature Plan

## Overview
Add voice translation capability to the LINE translator bot. When users are in "/set language pair..." mode with language pair "en id" (English-Indonesian), enable voice input that is converted to text, translated, and returned as a text message (no audio output).

## Current System Analysis

### Existing Features
- ✅ Text message translation via Google Cloud Translate API
- ✅ Language pair mode with bidirectional translation (source ↔ target)
- ✅ User/group settings stored in Firestore
- ✅ Command-based configuration (`/set language pair en id`)

### Current Architecture
- **Framework**: Flask + LINE Bot SDK v3
- **Translation**: Google Cloud Translate API v2
- **Storage**: Google Cloud Firestore
- **Message Types**: Text messages only

## Feature Requirements

### Functional Requirements
1. **Voice Input Support**
   - Detect and handle audio/voice messages from LINE
   - Support for language pair: English (en) ↔ Indonesian (id)
   - Only activate when language pair is set to "en id" or "id en"

2. **Speech-to-Text (STT)**
   - Convert received audio to text
   - Detect source language (en or id)
   - Handle audio format from LINE (typically M4A/AMR)

3. **Translation**
   - Use existing `detect_and_translate` function
   - Translate from detected language to target language
   - Maintain bidirectional translation logic

4. **Text Response**
   - Send translated text as a text message (not audio)
   - Simple and efficient - no audio generation needed

5. **Settings Integration**
   - Only enable when:
     - Translation is enabled (`enabled: true`)
     - Mode is "pair"
     - Language pair is "en id" or "id en"
   - Store voice translation preference in user settings (optional)

### Technical Requirements

#### Google Cloud Services
1. **Speech-to-Text API**
   - Convert audio to text
   - Language codes: `en-US`, `id-ID`
   - Support for M4A, AMR, and other LINE audio formats

2. **Text-to-Speech API** (NOT USED - Removed from implementation)
   - ~~Convert text to audio~~ - No longer needed
   - ~~Language codes: `en-US`, `id-ID`~~ - Removed
   - ~~Voice selection for natural-sounding output~~ - Removed
   - ~~Output format: M4A or MP3 (LINE compatible)~~ - Removed

#### LINE Bot SDK
1. **Audio Message Handling**
   - Handle `AudioMessageContent` webhook events
   - Download audio content from LINE
   - Upload audio content back to LINE

2. **Message Types**
   - Receive: Audio messages (voice input)
   - Send: Text messages (translated text)

## Implementation Plan

### Phase 1: Dependencies & Setup

#### 1.1 Update Dependencies (`pyproject.toml`)
```toml
google-cloud-speech = "^2.21.0"  # Speech-to-Text
google-cloud-texttospeech = "^2.16.0"  # Text-to-Speech
```

#### 1.2 Environment Variables
- No new environment variables needed (uses existing Google Cloud credentials)

### Phase 2: Audio Processing Module

#### 2.1 Create `gcs_audio.py`
**Functions:**
- `speech_to_text(audio_content: bytes, language_code: str) -> str`
  - Convert audio bytes to text
  - Support en-US and id-ID
  - Handle audio format conversion if needed

- `text_to_speech(text: str, language_code: str) -> bytes`
  - Convert text to audio bytes
  - Select appropriate voice (e.g., en-US: en-US-Wavenet-D, id-ID: id-ID-Wavenet-A)
  - Return audio in LINE-compatible format (M4A/MP3)

- `download_line_audio(message_id: str, access_token: str) -> bytes`
  - Download audio content from LINE API
  - Handle LINE's audio content API

### Phase 3: LINE Bot Integration

#### 3.1 Update `line_translator_bot.py`

**New Imports:**
```python
from linebot.v3.webhooks import AudioMessageContent
from linebot.v3.messaging import AudioMessage
from google.cloud import speech_v1, texttospeech_v1
```

**New Handler:**
```python
@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio_message(event):
    """
    Handle audio/voice messages for voice translation.
    Only processes when:
    - Translation is enabled
    - Mode is "pair"
    - Language pair is "en id" or "id en"
    """
    # 1. Get user/group settings
    # 2. Check if voice translation is enabled (en id pair)
    # 3. Download audio from LINE
    # 4. Convert speech to text
    # 5. Translate text
    # 6. Send translated text as text message
```

**Settings Check:**
- Verify `enabled == True`
- Verify `mode == "pair"`
- Verify language pair is `("en", "id")` or `("id", "en")`

### Phase 4: Audio Format Handling

#### 4.1 Audio Format Conversion
- LINE sends audio in M4A/AMR format
- Google Cloud Speech-to-Text supports various formats
- May need conversion library (e.g., `pydub`, `ffmpeg-python`)

#### 4.2 Audio Quality
- Ensure audio quality is sufficient for accurate transcription
- Handle different audio sample rates and bitrates

### Phase 5: Error Handling & Edge Cases

#### 5.1 Error Scenarios
- Audio download fails
- Speech-to-Text fails (unclear audio, unsupported format)
- Translation fails

#### 5.2 Fallback Behavior
- If STT fails: Send text message "Could not process audio. Please try again."
- If translation fails: Send original transcribed text
- Always send text message (no audio generation needed)

### Phase 6: Testing

#### 6.1 Unit Tests
- Test `speech_to_text` with sample audio
- Test `text_to_speech` with sample text
- Test language detection and translation flow

#### 6.2 Integration Tests
- Test full flow: audio → text → translation → text message
- Test with both en→id and id→en directions
- Test error handling

#### 6.3 User Testing
- Test with real LINE audio messages
- Verify audio quality and accuracy
- Test in group chats vs. direct messages

## File Structure Changes

```
line_trnsltrbt/
├── line_translator_bot.py      # Add audio message handler
├── gcs_translate.py            # No changes (reuse existing)
├── gcs_audio.py                # NEW: Audio processing functions
├── pyproject.toml              # Add new dependencies
└── VOICE_TRANSLATION_PLAN.md   # This file
```

## API Usage Considerations

### Google Cloud Speech-to-Text
- **Pricing**: Pay per 15-second increment
- **Quotas**: Check default quotas
- **Languages**: en-US, id-ID supported

### Google Cloud Text-to-Speech
- **Status**: NOT USED - Removed from implementation
- ~~**Pricing**: Pay per character~~ - No cost (not used)
- ~~**Quotas**: Check default quotas~~ - Not needed
- ~~**Voices**: Select natural-sounding voices for en-US and id-ID~~ - Not needed

### LINE Bot API
- **Audio Message Limits**: Only for receiving audio (downloading)
- **Content API**: Use LINE Content API to download audio (no upload needed)

## Configuration Options (Future Enhancements)

### Optional Settings to Add
1. **Voice Translation Toggle**
   - Add `voice_enabled: bool` to user settings
   - Allow users to enable/disable voice translation separately

2. **Voice Selection**
   - Allow users to choose TTS voice (male/female, different accents)

3. **Audio Quality Settings**
   - Adjust audio quality vs. file size tradeoff

## Implementation Priority

### MVP (Minimum Viable Product)
1. ✅ Basic audio message handling
2. ✅ Speech-to-Text for en-US and id-ID
3. ✅ Translation using existing logic
4. ✅ Text message reply (translated text)

### Future Enhancements
- Support for other language pairs
- Voice cloning/personalization
- Real-time streaming (if LINE supports)
- Audio quality optimization
- Caching for repeated phrases

## Security & Privacy

### Data Handling
- Audio files are temporary (process and discard)
- No storage of user audio content
- Comply with LINE's data usage policies
- Comply with Google Cloud data processing terms

### Error Logging
- Log errors without storing audio content
- Avoid logging sensitive user audio data

## Deployment Considerations

### Cloud Run
- **Recommended Settings for Voice Translation:**
  - **Memory: 1Gi** (upgraded from 512Mi, reduced from 2Gi)
    - Audio file buffering requires some memory
    - Google Cloud Speech-to-Text client needs memory for API calls
    - No audio output generation needed (simpler)
  - **CPU: 1-2** (1 CPU sufficient, 2 for better concurrency)
    - Audio processing (downloading, STT) is the main workload
    - No TTS processing needed (simpler)
    - 2 CPU recommended for better concurrent request handling
  
- **Current vs Recommended:**
  - Previous: 512Mi memory, 1 CPU (sufficient for text-only translation)
  - Recommended: 1Gi memory, 2 CPU (optimal for voice-to-text translation)
  - Minimum: 512Mi memory, 1 CPU (may work but 1Gi recommended for audio buffering)

- **Cost Considerations:**
  - 1Gi + 2 CPU: ~1.5x cost of 512Mi + 1 CPU (lower than original 2Gi plan)
  - No Text-to-Speech API costs (significant savings)
  - Only Speech-to-Text API costs (per 15-second increment)
  - Monitor Cloud Run metrics (memory usage, CPU utilization, request latency)

- **Scaling:**
  - Keep `--min-instances: 0` for cost efficiency (cold starts acceptable)
  - `--max-instances: 10` is reasonable for moderate traffic
  - Consider increasing max-instances if you expect high concurrent audio requests

- Monitor API usage and costs (Speech-to-Text API only - no TTS costs)

### Local Development
- Test with LINE webhook simulator
- Mock Google Cloud APIs for development
- Use sample audio files for testing

## Success Metrics

1. **Accuracy**: Speech-to-Text accuracy > 90% for clear audio
2. **Latency**: End-to-end processing < 3 seconds (faster without TTS)
3. **Reliability**: Success rate > 95%
4. **User Satisfaction**: Accurate transcription and translation

## Next Steps

1. Review and approve this plan
2. Set up Google Cloud Speech-to-Text API (Text-to-Speech not needed)
3. Implement Phase 1 (dependencies - Speech-to-Text only)
4. Implement Phase 2 (audio processing module - STT only)
5. Implement Phase 3 (LINE bot integration - text response)
6. Test and iterate
7. Deploy to production

## Implementation Changes (Simplified)

### Removed Components
- ❌ Text-to-Speech API integration
- ❌ Audio message generation
- ❌ Google Cloud Storage upload for audio
- ❌ Audio reply functionality

### Simplified Flow
1. Receive audio message from LINE
2. Download audio content
3. Convert speech to text (Speech-to-Text)
4. Translate text
5. Send translated text as text message

### Benefits
- ✅ Simpler implementation
- ✅ Lower costs (no TTS API usage)
- ✅ Faster response time (no audio generation)
- ✅ Less memory/CPU needed
- ✅ Easier to debug and maintain

