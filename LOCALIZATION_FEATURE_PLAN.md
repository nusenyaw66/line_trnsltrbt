# Localization Feature Plan: Localized Slash Commands for line_transltrbt

## Overview
Implement support for detecting the user's preferred display language and rendering system "/" commands (help, status, error messages, etc.) in that language. Current scope ships **two non-English locales together**: `zh-TW` (Traditional Chinese) and `ja` (Japanese).

This enhances UX for non-English users in the bot's two largest non-English audiences (Taiwan/HK and Japan) in a single rollout.

## Goals
- Detect/store user's UI language preference (default: en).
- Localize all command responses and help text.
- Ship `zh-TW` **and** `ja` translations in the same release, with full key parity against `en`.
- Maintain backward compatibility; English remains default.
- Support easy addition of future languages (zh-CN, ko, etc.) with no schema changes.

## Architecture

### 1. Language Detection & Storage
- **Storage**: Extend existing user/group settings (Firestore or local JSON fallback in user_settings.json).
  - Add `ui_lang` field: ISO code, one of `"en"`, `"zh-TW"`, `"ja"` in current scope.
  - Default: `"en"`.
  - Per-user and per-group (group inherits or overrides).
- **Supported codes & normalization**: Accept case-insensitive input and normalize.
  - `en`, `english` → `en`
  - `zh-tw`, `zh_tw`, `zh-hant`, `tw`, `traditional`, `繁中` → `zh-TW`
  - `ja`, `jp`, `japanese`, `日本語` → `ja`
  - Anything else → reject with localized error listing supported codes.
- **Detection Sources** (priority order):
  1. Explicit user setting via new command: `/set lang <code>` or `/lang <code>` (e.g. `/lang ja`, `/lang zh-tw`).
  2. Infer from existing `target_lang` / `source_lang`:
     - `target` in {`zh-TW`, `zh-tw`, `zh-Hant`} → `zh-TW`
     - `target` in {`ja`, `jp`} → `ja`
  3. Future: LINE Profile API language extension or message language detection via Google Translate.
  4. Fallback: `"en"`.
- **Persistence**: Update `get_user_setting()`, `get_group_setting()`, `save_*_setting()` functions to handle `ui_lang`.
- **Detection Function**: `detect_ui_language(user_id, group_id=None, ui_lang=None) -> str` in `i18n.py` (already scaffolded; needs settings wiring).

### 2. Command Localization System
- **Centralized Strings**: `locales/` directory with one JSON per locale (all three shipped together):
  - `locales/en.json` (source of truth for keys)
  - `locales/zh-TW.json`
  - `locales/ja.json` *(new in this scope)*
- All three files MUST have identical key sets. A parity test enforces this (see Testing).
- Structure example:
  ```json
  {
    "help_title": "翻譯機器人說明",
    "commands": {
      "/help": "/help - この説明を表示"
    },
    "status_enabled": "有効: {status}"
  }
  ```
- **Loader**: `i18n.py` (already scaffolded) with:
  - `load_locale(lang: str) -> dict` — normalizes code, falls back to `en` on missing file.
  - `get_text(key: str, lang: str = "en", **kwargs) -> str` — needs `.format(**kwargs)` support added.
  - `get_localized_status_lines(...)` — extend the current `zh-TW`/`en` branch into a data-driven approach so adding `ja` does not add a new `if` arm (use locale strings + a yes/no value map keyed by `lang`).
- **Command Handlers Update**:
  - `handle_status_command()` (handles /help and /status): Use i18n.get_text() for all strings.
  - `handle_set_command()`, `handle_on_command()`, `handle_off_command()`: Localize confirmations and errors.
  - Similar updates in `telegram_translator_bot.py` and `messenger_translator_bot.py` for consistency (shared i18n).
- **parse_switch_command()**: Keep command parsing language-agnostic (English commands only for now; future: localized command aliases).

### 3. Integration Points
- Main entry: `line_translator_bot.py` (primary).
- Shared modules: Move i18n + settings helpers to common if possible (current duplication across bot files).
- Settings retrieval: Modify `get_user_setting` / `get_group_setting` to include `ui_lang`.
- Reply functions: `send_reply()` remains unchanged.

### 4. New Commands
- `/set lang <code>` or `/lang <code>`: Sets UI language. Accepted codes in current scope: `en`, `zh-tw`, `ja` (plus aliases above).
- `/status lang`: Shows current UI lang (localized name, e.g. `English` / `繁體中文` / `日本語`).
- Invalid code → localized error listing the three supported codes.
- Update help text in all three locales to document new command.

## File Changes

### New Files
- `locales/en.json` - English strings (extract from current code). *(scaffolded)*
- `locales/zh-TW.json` - Traditional Chinese translations for all help/status/command texts. *(scaffolded)*
- `locales/ja.json` - **Japanese translations for all help/status/command texts.** *(new in this scope)*
- `i18n.py` - Localization loader and helper functions. *(scaffolded; needs `.format()` + settings wiring)*
- `tests/test_i18n.py` - Unit tests including a key-parity test across `en` / `zh-TW` / `ja`. *(extend existing)*
- Update `LOCALIZATION_FEATURE_PLAN.md` (this file) post-implementation.

### Modified Files
1. **line_translator_bot.py**
   - Import i18n.
   - Update `get_user_setting()`, `save_user_setting()`, equivalents for groups.
   - Refactor `handle_status_command()` to use localized strings based on `detect_ui_language()`.
   - Update `handle_set_command()` and other handlers for localized responses.
   - Add handling for `/set lang` and `/lang`.
   - Modify `parse_switch_command()` to recognize new lang commands.
   - Update version info / copyright strings if needed.

2. **telegram_translator_bot.py** & **messenger_translator_bot.py**
   - Adopt same i18n module for cross-platform consistency.
   - Update their command handlers similarly (they have duplicate command parsing logic).

3. **cache_manager.py** or settings-related
   - Ensure `ui_lang` is cached properly.

4. **README.md**
   - Document new `/set lang` command and supported languages.
   - Add localization section.

5. **pyproject.toml** / dependencies
   - No new deps needed (pure Python + existing json).

6. **user_settings.json** (example data)
   - Add sample `ui_lang` entries.

## Language Detection Logic (Pseudocode)
```python
SUPPORTED_UI_LANGS = {"en", "zh-TW", "ja"}

TARGET_LANG_TO_UI = {
    "zh-TW": "zh-TW", "zh-tw": "zh-TW", "zh-Hant": "zh-TW",
    "ja": "ja", "jp": "ja",
}

def detect_ui_language(user_id: str, group_id: Optional[str] = None) -> str:
    settings = get_group_setting(group_id) if group_id else get_user_setting(user_id)

    explicit = settings.get("ui_lang")
    if explicit in SUPPORTED_UI_LANGS:
        return explicit

    inferred = TARGET_LANG_TO_UI.get(settings.get("target_lang"))
    if inferred:
        return inferred

    # Future: LINE profile lang, auto-detect from recent messages
    return "en"
```

## Implementation Steps
1. Extract all hardcoded English strings from command handlers into `en.json` (finish the set already scaffolded).
2. Create `zh-TW.json` translations (Traditional Chinese — finish the set already scaffolded).
3. Create `ja.json` translations (natural-sounding business Japanese; keigo for system messages).
4. Add a parity test asserting `keys(en) == keys(zh-TW) == keys(ja)`.
5. Finish `i18n.py`: `.format(**kwargs)` support in `get_text`, refactor `get_localized_status_lines` to be locale-data-driven (no per-language `if` arms), and wire `detect_ui_language` to real settings.
6. Extend settings schema + CRUD functions to read/write `ui_lang`.
7. Refactor handlers (`handle_status_command`, `handle_set_command`, `handle_on/off_command`) to use `i18n.get_text` + detection.
8. Add `/set lang` and `/lang` commands; update `parse_switch_command()`.
9. Test with `zh-TW` and `ja` users (mock settings) — explicit, inferred-from-target, and fallback paths.
10. Update docs and other bots (`telegram_translator_bot.py`, `messenger_translator_bot.py`).
11. Deploy in one release (both new locales together, behind no flag — English remains default).

## Considerations & Risks
- **Command Parsing**: Keep commands in English to avoid complexity; localize only *output*.
- **Performance**: JSON load cached in memory (`@lru_cache` already in place).
- **Maintenance**: `en.json` is the source of truth for keys; CI parity test prevents drift between `en` / `zh-TW` / `ja`.
- **Group vs User**: Groups use group `ui_lang`; individuals use personal `ui_lang`.
- **Yes/No & enum values**: Hard-coded `"Yes"/"No"`, mode names, etc. must come from the locale (e.g. `zh-TW`: 是/否, `ja`: はい/いいえ) — don't branch by language in code.
- **Japanese specifics**:
  - Use polite form (です/ます) and light keigo for system messages; avoid casual endings.
  - Punctuation: full-width `：` `、` `。` where natural; keep ASCII for code/command tokens.
  - No spaces between Japanese tokens; keep spaces around Latin/numeric runs.
- **Traditional Chinese specifics**:
  - Use Taiwan vocabulary (e.g. 設定 not 设置; 啟用 not 启用); full-width punctuation `：` `，` `。`.
- **Future Extensibility**: Support pluralization, RTL if needed (not for zh-TW or ja).
- **Testing**: Unit tests for `i18n`; key-parity test; integration with Firestore settings; snapshot tests for `/help` and `/status` in all three locales.

## Sample Translations

### zh-TW (Traditional Chinese)
- "/help - returns this help message" → "/help - 返回此說明訊息"
- "Current Translation Settings:" → "目前翻譯設定："
- "Enabled: Yes" → "已啟用：是"
- "Unknown language code." → "未知的語言代碼。"

### ja (Japanese)
- "/help - returns this help message" → "/help - このヘルプを表示します"
- "Current Translation Settings:" → "現在の翻訳設定："
- "Enabled: Yes" → "有効：はい"
- "Unknown language code." → "不明な言語コードです。"

This plan provides a clean, scalable foundation for multilingual command UX, shipping `zh-TW` and `ja` together in the current scope.

---

# Phase 2: Telegram Bot Rollout

## Status
LINE bot localization shipped (`zh-TW` + `ja`, 57 tests passing). The reusable
runtime lives in `i18n.py` and is platform-agnostic — Telegram just needs to be
wired up to it the same way LINE is, plus a small set of Telegram-specific
locale keys.

## Goals
- Bring `telegram_translator_bot.py` to feature parity with the LINE bot for
  localization: `en` / `zh-TW` / `ja`, with the same `/lang` and `/set lang`
  UX.
- Persist `ui_lang` on per-user **and** per-thread (conversation/forum)
  settings.
- Localize **every** user-facing string the Telegram bot sends — including the
  voice-translation status and error messages, which the LINE bot does not have
  in the same form.
- Add `{platform}` parameterization to `help_version` so the same key serves
  both bots without forking.
- Keep `i18n.py` unchanged in behavior; only data (locale JSON) and a few
  helper signatures grow.

## Scope (current cycle)
In scope:
1. Telegram parser supports `/lang <code>` and `/set lang <code>`.
2. All `handle_*` functions (`set`, `status`, text rate-limit, voice path) use
   `get_text` / `get_localized_*_lines`.
3. Per-thread `ui_lang` field added to default settings.
4. New `_thread` variants of confirmation strings (mirrors `_group` variants).
5. New voice/transcription locale keys (shared with future LINE backfill).
6. `help_version` becomes `"Translator Bot for {platform}. Version: {version}"`;
   LINE caller updated to pass `platform="LINE"`, Telegram passes
   `platform="Telegram"`.
7. Parity test extended to assert all three locales still have identical keys
   after additions.
8. Parser tests for Telegram added (skip-on-missing-deps pattern like LINE).

Out of scope (defer):
- Messenger bot (Phase 3).
- Backfilling LINE's voice-error messages with the new shared keys — LINE's
  voice path was not refactored in Phase 1; do that as a small follow-up after
  Phase 2 lands.
- Auto-detecting Telegram's `language_code` field from the user's profile
  (Telegram exposes this in `from.language_code`). Worth a future iteration:
  use it as a **third** detection source (after explicit, before inference).

## Architecture

### Reuse, don't duplicate
- `i18n.py` stays the source of truth. No code changes there other than the one
  small signature update for `help_version`'s platform kwarg (already supported
  by `**kwargs` plumbing; only the locale strings change).
- Detection logic (`detect_ui_language`) is identical — Telegram passes
  `target_lang` from settings, same as LINE.

### Storage shape
- `get_user_setting()` / `get_thread_setting()` default dicts gain
  `"ui_lang": None` (six call sites; same pattern as LINE).
- Existing Firestore documents without `ui_lang` continue to work (resolves to
  `en` via fallback).

### Naming convention for new locale keys
- Use suffix `_thread` for Telegram-conversation/forum-thread variants
  (mirrors `_group` on LINE):
  - `current_thread_settings`
  - `translation_enabled_thread` / `translation_disabled_thread`
  - `pair_set_thread`
  - `american_enabled_thread` / `mandarin_enabled_thread` / `japanese_enabled_thread`
  - `lang_set_thread`
- Voice/transcription keys (platform-neutral, will also be used by future LINE
  voice refactor):
  - `voice_translation_not_enabled_american`
  - `voice_translation_not_enabled_mandarin`
  - `voice_translation_not_enabled_japanese`
  - `voice_translation_requires_pair`
  - `voice_pair_unsupported` (with `{source}` / `{target}` placeholders)
  - `voice_could_not_get_file`
  - `voice_could_not_download`
  - `voice_could_not_recognize`
  - `voice_could_not_recognize_pair`
  - `voice_could_not_transcribe`
  - `voice_translation_failed_prefix` (used as a line in a multi-line reply, e.g. "(Translation failed)")
  - `voice_pair_misconfigured`
  - `voice_unsupported_languages` (with `{supported}`)
  - `voice_processing_error`
- Help text:
  - `help_version` becomes `"Translator Bot for {platform}. Version: {version}"`
    in all three locales.

### Parser changes (`parse_switch_command` in Telegram)
Same diff as LINE:
```python
elif parts[1] == 'lang' and len(parts) >= 3:
    return {"type": "set_lang", "code": parts[2]}
...
if command == '/lang' and len(parts) >= 2:
    return {"type": "set_lang", "code": parts[1]}
```
Dispatcher: add `"set_lang"` to the type list in `handle_text_message`.

### New Telegram-side helpers
- `_resolve_ui_lang(user_id, thread_id) -> str` — mirrors LINE's helper,
  reads settings + calls `detect_ui_language`.
- `handle_set_lang_command(code, chat_id, user_id, thread_id) -> None` —
  validates via `normalize_lang`, persists `ui_lang` on user or thread,
  replies in the **newly selected** language.

### Refactor surface (telegram_translator_bot.py)
- 6 default-settings dicts → add `"ui_lang": None` (same replace-all pattern).
- `handle_set_command` → `get_text` for every confirmation/error.
- `handle_status_command` → `get_localized_help_lines` and
  `get_localized_status_lines` with `is_group=bool(thread_id)`.
  - Note: `get_localized_status_lines` currently keys the group-title swap on
    `is_group`. For Telegram threads we want the same visual semantics, so we
    pass `is_group=bool(thread_id)` and either (a) reuse `current_group_settings`
    or (b) add a tiny `is_thread` parameter that picks `current_thread_settings`
    when true. **Decision: extend the helper** with an optional
    `is_thread: bool = False` flag — keeps semantics explicit and lets the
    title differ ("Group" vs "Conversation") in each locale. Backward
    compatible.
- Text rate-limit message → `err_rate_limit_text`.
- Voice rate-limit message → `err_rate_limit_voice`.
- Voice path: roughly 15 string replacements across the four mode branches in
  `handle_voice_message` (american / mandarin / japanese / pair) plus the
  shared error tails.

### Detection priority on Telegram (future-proof)
Document, don't implement yet:
```
1. settings.ui_lang (explicit /lang or /set lang)
2. settings.target_lang (inferred — ja / zh-TW / etc.)
3. Telegram update.message.from.language_code  ← Phase 2.5
4. en
```
For Phase 2 we ship steps 1, 2, 4 (same as LINE). Step 3 is a one-line plumb
once we want it.

## File Changes

### Modified
1. **`telegram_translator_bot.py`** — analogous to LINE: imports, defaults,
   parser, dispatcher, all five `handle_*` functions, voice path.
2. **`locales/en.json`** — add ~18 new keys (thread variants + voice + the
   `help_version` platform refactor).
3. **`locales/zh-TW.json`** — translate same new keys.
4. **`locales/ja.json`** — translate same new keys.
5. **`line_translator_bot.py`** — one tiny edit: pass `platform="LINE"` to
   `get_localized_help_lines` (or to `get_text("help_version", ...)`) since the
   key is now parameterized.
6. **`i18n.py`** — single small change: `get_localized_help_lines` accepts
   `platform: str = "LINE"` and threads it into the `help_version` format kwargs.
   Optionally: `get_localized_status_lines` gains `is_thread: bool = False`.

### New
- `tests/test_parse_switch_command_telegram.py` — mirrors the LINE parser
  test; `pytest.importorskip("flask")` for graceful skip.
- (No new locale files.)

### Unchanged
- `i18n.py` core algorithms (normalization, detection, format kwargs, parity).
- `messenger_translator_bot.py` (Phase 3).

## Implementation Steps
1. Add Telegram-specific + voice-path + platform-aware locale keys to
   `en.json`. Keep `help_version` value updated to use `{platform}`.
2. Mirror new keys in `zh-TW.json` and `ja.json` with natural translations.
3. Update `get_localized_help_lines(platform=…)` and (optionally)
   `get_localized_status_lines(is_thread=…)` in `i18n.py`.
4. Update LINE bot to pass `platform="LINE"` to `get_localized_help_lines`.
5. Add `"ui_lang": None` to all six default-settings dicts in the Telegram bot
   (same replace-all pattern used for LINE).
6. Extend Telegram `parse_switch_command` to recognize `/lang` and
   `/set lang`.
7. Add `_resolve_ui_lang` and `handle_set_lang_command` helpers in Telegram bot.
8. Refactor `handle_set_command`, `handle_status_command`, and the voice path
   of `handle_voice_message` to use `get_text` / `get_localized_*_lines`.
9. Extend dispatcher in `handle_text_message` to route `set_lang`.
10. Run full test suite. Existing parity test will fail until all three
    locales have the new keys — fix any drift.
11. Add Telegram parser test (`pytest.importorskip` gated).
12. Smoke-import the Telegram bot end-to-end and render a few `/help` and
    `/status` outputs in each language.

## Risks & Considerations
- **Voice path verbosity**: Telegram's voice path has many short user-facing
  strings. Translating them is mechanical, but it's where translation drift
  is most likely. The parity test catches missing keys; review the
  translations once for tone consistency before merging.
- **Telegram chat_id vs user_id**: For private chats Telegram's `chat_id`
  equals the user id; for group chats they differ and we already use
  `thread_id` (forum threads) plus `chat_id` (the group's id). `ui_lang`
  storage should follow the **same key the bot uses for the settings doc** —
  per-user for DMs, per-thread for forum/group threads. No new storage shape.
- **`help_version` key change**: Backward-incompatible at the string level (it
  now has `{platform}`). All in-tree callers will be updated in the same PR;
  no external consumers.
- **Forum threads vs plain groups**: Telegram supports both; threads have a
  `message_thread_id`. The existing code treats threads as the localization
  unit when present. We keep that semantics; group chats *without* threads
  fall through to user settings (existing behavior — unchanged).
- **No new dependencies**.
- **Atomic rollout**: One PR that bumps all three locales and Telegram code
  together, so the parity test never goes red on `main`.

## Sample Telegram-Side Translations

### `current_thread_settings`
- en: `Current Conversation Translation Settings:`
- zh-TW: `目前對話翻譯設定：`
- ja: `現在の会話の翻訳設定：`

### `translation_enabled_thread`
- en: `Translation enabled for this conversation ✓`
- zh-TW: `已為此對話啟用翻譯 ✓`
- ja: `この会話の翻訳を有効にしました ✓`

### `voice_could_not_recognize`
- en: `Could not recognize speech. Please ensure audio is clear and try again.`
- zh-TW: `無法辨識語音。請確認音訊清晰後再試一次。`
- ja: `音声を認識できませんでした。音声がはっきりしているか確認のうえ再度お試しください。`

### `voice_pair_unsupported` (with placeholders)
- en: `Voice translation not enabled or pair ({source} → {target}) not supported.`
- zh-TW: `語音翻譯未啟用，或語言對 ({source} → {target}) 不支援。`
- ja: `音声翻訳が無効、または言語ペア ({source} → {target}) は未対応です。`

### `help_version` (now platform-aware)
- en: `Translator Bot for {platform}. Version: {version}`
- zh-TW: `{platform} 翻譯機器人。版本：{version}`
- ja: `{platform} 翻訳ボット。バージョン：{version}`

## Test Plan
- All existing 57 tests still pass (parity, format kwargs, status/help in three
  langs).
- Parity test continues to pass after adding ~18 new keys × 3 locales.
- New `tests/test_parse_switch_command_telegram.py`:
  - `/lang ja`, `/lang zh-tw`, `/lang en` parsed → `set_lang`.
  - `/set lang …` parsed → `set_lang`.
  - `/lang` without arg → `None`.
  - Regression: existing `/help`, `/status`, `/set on/off/pair/...` still parse.
- Smoke script (not committed): render `/help` and `/status` in `en` /
  `zh-TW` / `ja` for both user and thread contexts on the Telegram bot.
- Manual smoke (deferred to deploy time): `/lang ja` in a real Telegram chat
  followed by `/status` to confirm the reply is in Japanese.

## Estimated Surface
- ~150 lines changed in `telegram_translator_bot.py`.
- ~20 new keys × 3 locale files = ~60 JSON line additions.
- ~1 line change in `i18n.py` signature + tiny adjustment in
  `get_localized_help_lines`.
- 1 line change in `line_translator_bot.py` to pass `platform="LINE"`.
- ~30 lines of new tests.

Net: one cohesive PR, parity test prevents merge of partial locale data.
