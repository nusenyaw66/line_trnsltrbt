# Enable Voice-to-Text for American Mode

## Overview

Currently, voice-to-text only works in "pair" mode where both source and target languages are known. This plan enables voice-to-text for "american" mode, which translates ANY detected language to English.

## Research Findings

### Google Cloud Speech-to-Text Language Support

**Key Facts:**

- Google Cloud Speech-to-Text supports **100+ languages**, but **NOT all languages globally**
- The API supports automatic language detection through `alternative_language_codes` parameter
- You can specify up to 4 alternative languages in addition to the primary language code
- For unknown source languages, we can use a list of common languages as alternatives

**Commonly Supported Languages (examples):**

- English (en-US, en-GB, en-AU, etc.)
- Chinese (zh-CN, zh-TW)
- Spanish (es-ES, es-MX, es-AR, etc.)
- Japanese (ja-JP)
- Korean (ko-KR)
- French (fr-FR, fr-CA)
- German (de-DE)
- Italian (it-IT)
- Portuguese (pt-BR, pt-PT)
- Russian (ru-RU)
- Arabic (ar-XA)
- Hindi (hi-IN)
- Thai (th-TH)
- Indonesian (id-ID)
- Vietnamese (vi-VN)
- And many more...

## Implementation Plan

### 1. Update `is_voice_translation_enabled()` Function

**Current behavior:** Only allows "pair" mode**New behavior:** Allow both "pair" and "american" modes

```python
def is_voice_translation_enabled(settings: Dict[str, Any]) -> bool:
    if not settings.get("enabled", False):
        return False
    
    mode = settings.get("mode")
    
    # Pair mode: requires both source and target languages
    if mode == "pair":
        source_lang = settings.get("source_lang")
        target_lang = settings.get("target_lang")
        supported_languages = ["en", "zh-TW", "es", "ja", "th", "id"]
        if source_lang and target_lang:
            if source_lang in supported_languages and target_lang in supported_languages:
                return True
    
    # American mode: translate any language to English
    elif mode == "american":
        return True  # American mode supports all languages that Speech-to-Text can recognize
    
    return False
```



### 2. Create Language Mapping for American Mode

Create a comprehensive list of common languages for speech recognition in american mode:

```python
# Common languages for american mode (prioritized list)
AMERICAN_MODE_LANGUAGES = [
    "en-US",      # English (most common)
    "zh-CN",      # Chinese (Simplified)
    "zh-TW",      # Chinese (Traditional)
    "es-ES",      # Spanish (Spain)
    "es-MX",      # Spanish (Mexico)
    "ja-JP",      # Japanese
    "ko-KR",      # Korean
    "fr-FR",      # French
    "de-DE",      # German
    "it-IT",      # Italian
    "pt-BR",      # Portuguese (Brazil)
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
    # Add more as needed
]
```

**Note:** Google Cloud Speech-to-Text `alternative_language_codes` supports up to 4 alternatives. We can:

- Option A: Use the first language as primary and next 4 as alternatives
- Option B: Try languages sequentially (more reliable but slower)
- Option C: Use a smart approach - try most common languages first, then expand

### 3. Update `handle_audio_message()` Function

**For American Mode:**

1. Use a list of common languages (or all supported languages)
2. Try speech recognition with multiple language alternatives
3. If successful, translate transcribed text to English using existing `detect_and_translate()` function
4. Handle cases where language is not recognized

**Implementation Strategy:**

```python
if settings.get("mode") == "american":
    # American mode: try multiple languages
    # Use first language as primary, next 4 as alternatives (API limit)
    primary_lang = AMERICAN_MODE_LANGUAGES[0]
    alternative_langs = AMERICAN_MODE_LANGUAGES[1:5]  # Max 4 alternatives
    
    try:
        transcribed_text = speech_to_text(
            audio_content, 
            primary_lang, 
            alternative_language_codes=alternative_langs
        )
    except:
        # If first attempt fails, try other language groups
        # Could iterate through language groups or try sequentially
        pass
    
    # Translate to English
    translated_text = detect_and_translate(
        transcribed_text,
        enabled=True,
        mode="american"
    )
```



### 4. Handle Edge Cases

- **Language not recognized:** Provide helpful error message
- **Empty transcription:** Handle gracefully
- **Translation fails:** Fall back to transcribed text only
- **Performance:** Consider caching or optimizing language detection

### 5. Update Error Messages

Update error messages to mention american mode support:

```python
"Voice translation is available in:\n"
"- Pair mode: /set language pair <source> <target>\n"
"- American mode: /set american (translates any language to English)"
```



## Limitations

1. **Not all languages supported:** Google Cloud Speech-to-Text doesn't support every language globally
2. **Performance:** Trying multiple languages may be slower than pair mode
3. **Accuracy:** Auto-detection may be less accurate than specifying exact language pair
4. **API limits:** `alternative_language_codes` limited to 4 alternatives per request

## Testing Plan

1. Test with common languages (English, Spanish, Chinese, Japanese)
2. Test with less common languages
3. Test error handling for unsupported languages
4. Test performance with multiple language attempts
5. Verify translation to English works correctly

## Files to Modify

1. `line_translator_bot.py`

- Update `is_voice_translation_enabled()`
- Update `handle_audio_message()` to handle american mode
- Add language list for american mode

2. `gcs_audio.py` (if needed)

- May need to enhance `speech_to_text()` for better multi-language support

## Success Criteria

- ✅ Voice messages work in american mode