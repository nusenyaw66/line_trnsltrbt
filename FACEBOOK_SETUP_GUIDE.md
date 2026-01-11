# Facebook Messenger Bot Setup Guide

This guide walks you through setting up the Facebook Messenger translator bot.

## Prerequisites

1. A Facebook account
2. A Facebook Page (create one at https://www.facebook.com/pages/create)
3. Access to https://developers.facebook.com/

## Step 1: Create a Facebook App

1. Go to https://developers.facebook.com/
2. Click **"My Apps"** → **"Create App"**
3. Select **"Business"** as the app type
4. Fill in:
   - **App Name**: e.g., "Translator Bot"
   - **App Contact Email**: Your email
   - **Business Account**: (optional, can skip)
5. Click **"Create App"**

## Step 2: Add Messenger Product

1. In your app dashboard, find **"Add Product"** or go to **"Products"** in the left sidebar
2. Find **"Messenger"** and click **"Set Up"**
3. You'll be taken to the Messenger settings page

**Note**: After adding Messenger, you can access it via:
- **"Products"** → **"Messenger"** → **"Settings"**
- Or **"Use case"** → **"Customize"** → **"Messenger API Settings"**

## Step 3: Create a Facebook Page (if you don't have one)

1. Go to https://www.facebook.com/pages/create
2. Choose **"Business or Brand"**
3. Fill in your page name and category
4. Click **"Create Page"**

## Step 4: Generate Page Access Token

**Navigation**: Go to **"Use case"** → **"Customize"** → **"Messenger API Settings"** → **"2. Generate access token"** section

Alternatively: **"Products"** → **"Messenger"** → **"Settings"** → **"Access Tokens"**

1. In the Messenger API Settings page, go to the **"2. Generate access token"** section
2. Select your Facebook Page from the dropdown
3. Click **"Generate Token"**
4. **Copy and save this token** - this is your `FACEBOOK_PAGE_ACCESS_TOKEN`
5. You may need to grant permissions - click **"Continue"** if prompted

**Note**: This is the same section where you'll subscribe your page to webhooks in Step 6.3. After generating the token, proceed to Step 6.3 in the same section to subscribe your page.

## Step 5: Get App Secret

1. In your app dashboard, go to **"Settings"** → **"Basic"**
2. Find **"App Secret"** and click **"Show"**
3. Enter your Facebook password if prompted
4. **Copy and save this secret** - this is your `FACEBOOK_APP_SECRET`

## Step 6: Set Up Webhook

**Navigation**: Go to **"Use case"** → **"Customize"** → **"Messenger API Settings"** (or **"Products"** → **"Messenger"** → **"Settings"**)

In the Messenger API Settings page, you'll see numbered sections:
- **1. Configure Webhooks** (Steps 6.1 and 6.2)
- **2. Generate access token** (Step 6.3)

### 6.1 Configure Webhook URL

**Location**: **"Messenger API Settings"** → **"1. Configure Webhooks"**

1. In the **"1. Configure Webhooks"** section, click **"Add Callback URL"** or **"Edit"** if one exists
2. Enter your webhook URL: `https://your-domain.com/webhook`
   - For local testing, use ngrok: `https://your-ngrok-url.ngrok.io/webhook`
3. Enter a **Verify Token** (any string you choose, e.g., `my_verify_token_123`)
   - **Save this token** - this is your `FACEBOOK_VERIFY_TOKEN`
4. Click **"Verify and Save"**
   - Facebook will send a GET request to your webhook URL to verify it
   - Your server must respond with the verify token

### 6.2 Subscribe to Events

**Location**: **"Messenger API Settings"** → **"1. Configure Webhooks"** (same section as 6.1)

1. After webhook is verified, in the same **"1. Configure Webhooks"** section, click **"Manage"** or **"Edit"** next to your webhook
2. In **"Subscription Fields"** (or **"Webhook Fields"**), subscribe to:
   - ✅ `messages` - Required for receiving messages
   - ✅ `messaging_postbacks` - For handling button clicks/postbacks
   - ✅ `message_deliveries` (optional) - For delivery receipts
   - ✅ `message_reads` (optional) - For read receipts
3. Click **"Save"**

### 6.3 Subscribe Your Page to Webhook

**Location**: **"Messenger API Settings"** → **"2. Generate access token"** section

1. Go to the **"2. Generate access token"** section in Messenger API Settings
2. Look for **"Page Subscriptions"** or **"Subscribed Pages"** in this section
3. If your page is not listed, look for:
   - **"Subscribe to Pages"** button
   - **"Add Page"** button
   - Or your page may appear with a **"Subscribe"** toggle/button next to it
4. Click **"Subscribe"** next to your page (or toggle it ON)
5. Ensure these events are enabled for your page:
   - ✅ `messages` - Required for receiving messages
   - ✅ `messaging_postbacks` - For button clicks
6. The subscription should save automatically, or click **"Save"** if prompted

**Note**: The "Page Subscriptions" is in the **"2. Generate access token"** section, which is separate from the webhook configuration (Step 6.1 and 6.2 are in section "1. Configure Webhooks").

## Step 7: Configure Environment Variables

Create or update your `.env` file with:

```env
# Facebook Messenger Credentials
FACEBOOK_PAGE_ACCESS_TOKEN=your_page_access_token_here
FACEBOOK_APP_SECRET=your_app_secret_here
FACEBOOK_VERIFY_TOKEN=my_verify_token_123

# Optional (keep existing values)
APP_VERSION=0.1
GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service-account-key.json
FIRESTORE_DATABASE_ID=messenger-trnsltrbt-db
```

## Step 8: Test Webhook Verification

1. Start your bot server:
   ```bash
   poetry run python messenger_translator_bot.py
   ```

2. For local testing, use ngrok:
   ```bash
   ngrok http 8080
   ```

3. Update your webhook URL in Facebook with the ngrok URL

4. Facebook will send a GET request to verify your webhook. Your server should respond with the challenge token.

## Step 9: Test the Bot

1. Go to your Facebook Page
2. Click **"Message"** button
3. Send a test message to your page
4. The bot should respond (if translation is enabled)

### Test Commands

Try these commands:
- `/status` - Check current settings
- `/set on` - Enable translation
- `/set language pair en zh-tw` - Set language pair
- `/set american` - Enable American mode
- `/status help` - Show help

## Step 10: App Review (For Production)

If you want to make your bot available to the public:

1. Go to **"App Review"** → **"Permissions and Features"**
2. Request these permissions:
   - `pages_messaging` - Required for sending/receiving messages
   - `pages_read_engagement` - Optional, for analytics
3. Fill out the required information
4. Submit for review

**Note**: For development/testing, you can add test users in **"Roles"** → **"Test Users"** without going through review.

## Troubleshooting

### Webhook Verification Fails

- Check that `FACEBOOK_VERIFY_TOKEN` in your `.env` matches the token you entered in Facebook
- Ensure your server is running and accessible
- Check server logs for errors

### Messages Not Received

- Verify webhook is subscribed to `messages` event
- Check that your page is subscribed to the webhook
- Verify `FACEBOOK_PAGE_ACCESS_TOKEN` is correct
- Check server logs for errors

### Signature Verification Fails

- Ensure `FACEBOOK_APP_SECRET` is correct
- Check that the webhook signature header is being read correctly
- Verify your server is receiving the raw request body (not parsed JSON)

### Audio Messages Not Working

- Verify audio attachments are being received
- Check that `download_messenger_audio` function has access to `PAGE_ACCESS_TOKEN`
- Ensure Google Cloud Speech-to-Text API is enabled and configured

## Security Notes

1. **Never commit** your `.env` file to version control
2. Keep your `APP_SECRET` and `PAGE_ACCESS_TOKEN` secure
3. Use environment variables or secret management in production
4. Regularly rotate access tokens

## Rate Limits

Facebook Messenger has rate limits:
- **Standard**: 250 messages per user per day
- **With approval**: Can request higher limits (1000+ messages/day)

## Additional Resources

- [Facebook Messenger Platform Documentation](https://developers.facebook.com/docs/messenger-platform)
- [Webhook Reference](https://developers.facebook.com/docs/graph-api/webhooks)
- [Send API Reference](https://developers.facebook.com/docs/messenger-platform/send-messages)
