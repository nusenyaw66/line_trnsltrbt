TranslatorBot for Line

v0.0.1
Command Parsing:
Commands start with /
/on translate - enables translation for user
/off translate - disables translation for user
/set language pair <source> <target> - sets specific language pair (e.g., /set language pair tc eng)
/set american - sets mode to translate all languages to American English
/status - returns current user settings

Langage options for /set language pair <source> <target>
"en": "en",
"zh-tw": "zh-TW",
"zh-cn": "zh-TW",  # Map zh-cn to zh-TW (we only support Traditional Chinese)
"es": "es",
"ja": "ja",
"jpn": "ja",  # Also accept jpn
"th": "th",
"id": "id",
"ind": "id"  # Also accept ind

v0.0.2
in /set language pair mode, added translation from soruce to target and vice versa.  Also Line user name (when available) will be displayed with Original message

v0.0.3
added voice-to-text and text-to-voice for language pair en and id

v0.0.4
changed only voice-to-text. I.e., souce voice will only be translated to text instead of voice.

v0.0.5
ignore icon or Emoji only messages