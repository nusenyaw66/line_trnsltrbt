TranslatorBot for Line

v0.0.1
Command Parsing:
Commands start with /
/on translate - enables translation for user
/off translate - disables translation for user
/set language pair   - sets specific language pair (e.g., /set language pair tc eng)
/set american - sets mode to translate all languages to American English
/status - returns current user settings
/status version
/status help

Langage options for /set language pair  
"en": "en",
"zh-tw": "zh-TW",
"zh-cn": "zh-CN",
"tw": "zh-TW",  # Traditional Chinese (Taiwan)
"cn": "zh-CN",  # Simplified Chinese
"es": "es",
"ja": "ja",
"jpn": "ja",  # Also accept jpn
"th": "th",
"id": "id",
"ind": "id"  # Also accept ind

Voice to text only available for paid customers!

v0.0.2
in /set language pair mode, added translation from soruce to target and vice versa.  Also Line user name (when available) will be displayed with Original message

v0.0.3
added voice-to-text and text-to-voice for language pair en and id

v0.0.4
changed only voice-to-text. I.e., souce voice will only be translated to text instead of voice.

v0.0.5
ignore icon or Emoji only messages

v0.0.8
fixed Line displayName errors in line_translator_bot.py

v0.2
enabled voice-to-text for paired language mode 

v0.4
enabled voice-to-text for /set american mode
refer to enable_voice_american_mode.plan.md

v0.6 added /set maindrain mode

v0.7 added /set japanese mode

v0.8 added FB Messenger branch

v0.9 Added Filipino (Tagalog) support to the translation bot.

v0.22 added French, Italian, Germany and pre-production update.

v0.39 added Vietnamese

v0.46 added Simpfied Chinese - zh-CN

v0.50 added v2v AI translation. 0 Star druing beta

v0.54 spoken replies use Grok TTS (eve/rex) instead of Gemini TTS; Gemini still understands the voice note

v0.55 spoken replies are Google STT + Google Translate + Grok TTS (no Gemini audio-in)