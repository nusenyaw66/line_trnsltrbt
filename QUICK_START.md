# Quick Start: Project Structure & Service Account

## TL;DR - Recommendations

### ✅ Project Structure: **Monorepo** (Keep Both Bots Together)
- Keep `line_translator_bot.py` and `messenger_translator_bot.py` in the same repository
- Both bots share `gcs_translate.py` and `gcs_audio.py`
- Single `pyproject.toml` for dependencies

### ✅ Service Account: **Share the Same One**
- Use existing: `user-704@line-trnsltrbt.iam.gserviceaccount.com`
- Both bots need identical permissions (Translation, Speech-to-Text, Firestore)
- No additional setup needed!

### ✅ GCP Project: **Same Project**
- Keep both bots in `line-trnsltrbt` project
- Deploy as separate Cloud Run services:
  - `line-translator-bot`
  - `messenger-translator-bot`

## Deployment Commands

### Deploy LINE Bot (Existing)
```bash
./deploy_gcs.sh
```

### Deploy Messenger Bot (New)
```bash
./deploy-messenger.sh
```

### Set Up Facebook Secrets (One-time)
```bash
# Update .env file with Facebook credentials
# Then run:
secret_update=true ./deploy-messenger.sh
```

## File Structure

```
line_trnsltrbt/
├── line_translator_bot.py          # LINE bot
├── messenger_translator_bot.py    # Messenger bot
├── gcs_translate.py               # Shared translation
├── gcs_audio.py                   # Shared audio processing
├── Dockerfile                      # LINE bot Dockerfile
├── Dockerfile.messenger           # Messenger bot Dockerfile
├── cloudbuild.yaml                # LINE build config
├── cloudbuild-messenger.yaml      # Messenger build config
├── deploy_gcs.sh                  # LINE deployment script
├── deploy-messenger.sh            # Messenger deployment script
└── pyproject.toml                 # Shared dependencies
```

## Service Account Details

**Email**: `user-704@line-trnsltrbt.iam.gserviceaccount.com`

**Already Has Required Permissions**:
- ✅ Translation API (`roles/cloudtranslate.user`)
- ✅ Speech-to-Text API (`roles/speech.client`)
- ✅ Text-to-Speech API (`roles/cloudtts.user`)
- ✅ Firestore access
- ✅ Secret Manager access

**No additional setup needed!** Just use the same service account for both Cloud Run services.

## Why This Works

1. **Same Permissions**: Both bots need identical Google Cloud API permissions
2. **Service Accounts Are Credentials**: Multiple services can use the same account
3. **Common Practice**: Standard pattern in GCP - one service account per application type
4. **Simpler Management**: One account to manage instead of two

## Next Steps

1. ✅ Keep current repository structure (no changes needed)
2. ✅ Use existing service account for both bots
3. ✅ Set up Facebook secrets in Secret Manager
4. ✅ Deploy Messenger bot using `deploy-messenger.sh`

See `PROJECT_STRUCTURE_PLAN.md` for detailed explanation.
