# Facebook Messenger Migration Plan

## Overview
Convert the LINE translator bot to Facebook Messenger while reusing as much existing code as possible.

## Architecture Changes

### 1. SDK Replacement
- **LINE SDK** → **Facebook Messenger API** (using `requests` library directly)
- LINE uses `line-bot-sdk` (v3)
- Facebook Messenger uses REST API (no official Python SDK, but we can use `requests`)

### 2. Webhook Changes
- **LINE**: Single POST endpoint `/webhook` with signature verification
- **Facebook**: 
  - GET `/webhook` for verification (with `hub.verify_token` and `hub.challenge`)
  - POST `/webhook` for events (with signature verification)

### 3. Message Handling
- **LINE**: Uses event handlers (`@handler.add(MessageEvent)`)
- **Facebook**: Parse JSON payload directly from POST request

### 4. User/Group Context
- **LINE**: Supports both user chats and group chats (`GroupSource`)
- **Facebook**: Supports user chats and group conversations (via `thread_id`)

### 5. Audio Messages
- **LINE**: M4A format, download via Content API
- **Facebook**: Audio attachments, download via Graph API

## Code Reuse Strategy

### Keep As-Is (100% reusable):
1. ✅ `gcs_translate.py` - Translation logic (no changes)
2. ✅ `gcs_audio.py` - Speech-to-text logic (minor changes for audio download)
3. ✅ Firestore settings management (`get_user_setting`, `update_user_setting`, etc.)
4. ✅ Command parsing (`parse_switch_command`)
5. ✅ Translation modes (pair, american, mandarin, japanese)
6. ✅ Emoji detection (`is_emoji_only`)

### Needs Modification:
1. 🔄 Main bot file - Replace LINE SDK with Facebook Messenger API calls
2. 🔄 Webhook handler - Add GET verification, update POST handler
3. 🔄 Message sending - Use Messenger Send API
4. 🔄 Audio download - Update for Messenger audio format
5. 🔄 User profile - Use Messenger Graph API

## Facebook Messenger API Details

### Authentication
- **Page Access Token**: Required for sending messages
- **App Secret**: Required for webhook signature verification
- **Verify Token**: Custom token for webhook verification

### Webhook Verification (GET)
```
GET /webhook?hub.mode=subscribe&hub.verify_token=YOUR_VERIFY_TOKEN&hub.challenge=CHALLENGE_STRING
Response: Return hub.challenge as plain text
```

### Webhook Events (POST)
- Content-Type: `application/json`
- Signature verification: `X-Hub-Signature-256` header (SHA256 HMAC)
- Event structure: `entry[].messaging[]` array

### Sending Messages
```
POST https://graph.facebook.com/v21.0/me/messages
Headers:
  - Content-Type: application/json
  - Authorization: Bearer PAGE_ACCESS_TOKEN
Body:
{
  "recipient": {"id": "USER_ID"},
  "message": {"text": "Hello"}
}
```

### Getting User Profile
```
GET https://graph.facebook.com/v21.0/{user-id}?fields=first_name,last_name&access_token=PAGE_ACCESS_TOKEN
```

### Downloading Audio
```
GET https://graph.facebook.com/v21.0/{attachment-id}?access_token=PAGE_ACCESS_TOKEN
```

## Environment Variables

Replace:
- `LINE_CHANNEL_ACCESS_TOKEN` → `FACEBOOK_PAGE_ACCESS_TOKEN`
- `LINE_CHANNEL_SECRET` → `FACEBOOK_APP_SECRET`
- Add: `FACEBOOK_VERIFY_TOKEN` (custom token for webhook verification)

Keep:
- `APP_VERSION`
- `GOOGLE_APPLICATION_CREDENTIALS`
- `FIRESTORE_DATABASE_ID`

## Facebook Settings Required

### 1. Facebook App Setup
1. Go to https://developers.facebook.com/
2. Create a new app or use existing
3. Add "Messenger" product
4. Get **App ID** and **App Secret**

### 2. Facebook Page
1. Create a Facebook Page (or use existing)
2. In Messenger settings, generate **Page Access Token**
3. Subscribe to webhook events:
   - `messages`
   - `messaging_postbacks`
   - `message_deliveries`
   - `message_reads`

### 3. Webhook Configuration
1. Set Webhook URL: `https://your-domain.com/webhook`
2. Set Verify Token: (custom token, e.g., "my_verify_token_123")
3. Subscribe to page events:
   - `messages`
   - `messaging_postbacks`

### 4. Permissions Required
- `pages_messaging` - Send/receive messages
- `pages_read_engagement` - Read page engagement
- `pages_show_list` - List pages

### 5. App Review (for Production)
- Submit app for review if going public
- For development, add test users in App Dashboard

## Implementation Steps

1. ✅ Create migration plan
2. ⏳ Update dependencies (remove line-bot-sdk, add requests if needed)
3. ⏳ Create new `messenger_bot.py` (or rename existing)
4. ⏳ Update webhook handler (GET + POST)
5. ⏳ Update message sending function
6. ⏳ Update message receiving/parsing
7. ⏳ Update audio message handling
8. ⏳ Update user profile retrieval
9. ⏳ Update audio download function
10. ⏳ Test with Facebook Messenger
11. ⏳ Update documentation

## Testing Checklist

- [ ] Webhook verification (GET request)
- [ ] Webhook signature verification (POST request)
- [ ] Text message receiving
- [ ] Text message sending
- [ ] Command parsing (`/set`, `/status`)
- [ ] Translation (pair mode)
- [ ] Translation (american mode)
- [ ] Translation (mandarin mode)
- [ ] Translation (japanese mode)
- [ ] Audio message receiving
- [ ] Audio transcription
- [ ] User profile retrieval
- [ ] Group conversation support
- [ ] Emoji-only message filtering

## Notes

- Facebook Messenger doesn't have a direct "group" concept like LINE
- Use `thread_id` to identify conversations (can be 1-on-1 or group)
- Facebook audio format: typically MP3 or OGG
- Rate limits: 250 messages per user per day (standard), 1000+ with approval
