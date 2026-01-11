# Project Structure & Service Account Plan

## Overview

This document addresses:
1. **Project Structure**: Should you create a new project/repo for Facebook Messenger bot?
2. **Service Account Sharing**: Can both bots use the same Google Cloud service account?

## Recommendation: Monorepo Approach (Current Structure)

### ✅ Keep Both Bots in Same Repository

**Current Structure** (Recommended):
```
line_trnsltrbt/
├── line_translator_bot.py      # LINE bot
├── messenger_translator_bot.py # Facebook Messenger bot
├── gcs_translate.py            # Shared translation logic
├── gcs_audio.py                # Shared audio processing
├── pyproject.toml              # Shared dependencies
├── Dockerfile                  # Can be shared or separate
├── cloudbuild.yaml             # LINE-specific (create messenger version)
├── deploy_gcs.sh               # LINE-specific (create messenger version)
└── ...
```

**Why This Works:**
- ✅ **Maximum code reuse** - Both bots share 90%+ of code
- ✅ **Easier maintenance** - Update translation logic once, both bots benefit
- ✅ **Single dependency management** - One `pyproject.toml` for both
- ✅ **Unified versioning** - Same version number for both bots
- ✅ **Simpler development** - Test both bots locally with same environment
- ✅ **Shared utilities** - `gcs_translate.py`, `gcs_audio.py` used by both

### Alternative: Separate Repositories

**If you choose separate repos:**
```
line-translator-bot/
├── line_translator_bot.py
├── gcs_translate.py
├── gcs_audio.py
└── ...

messenger-translator-bot/
├── messenger_translator_bot.py
├── gcs_translate.py  # Duplicated
├── gcs_audio.py      # Duplicated
└── ...
```

**Drawbacks:**
- ❌ Code duplication (translation/audio logic in both repos)
- ❌ Maintenance overhead (fix bugs in two places)
- ❌ Version drift (bots may have different features)
- ❌ More complex CI/CD setup

**When Separate Repos Make Sense:**
- Different teams maintaining each bot
- Different release cycles
- Different deployment targets
- Need completely isolated deployments

## Service Account Sharing: ✅ YES

### You CAN Share the Same Service Account

**Answer: YES, absolutely!** Both bots can use the same Google Cloud service account.

### Why It Works

1. **Same Permissions Needed**: Both bots require identical permissions:
   - Translation API (`roles/cloudtranslate.user`)
   - Speech-to-Text API (`roles/speech.client`)
   - Text-to-Speech API (`roles/cloudtts.user`)
   - Firestore access
   - Secret Manager access (for different secrets)

2. **Service Accounts Are Credentials**: A service account is just a set of credentials with permissions. Multiple services can use the same account.

3. **Common Pattern**: This is a standard practice in Google Cloud - one service account per application type, shared across related services.

### Current Setup

**Existing Service Account:**
- **Email**: `user-704@line-trnsltrbt.iam.gserviceaccount.com`
- **Project**: `line-trnsltrbt`

### Recommended Approach

#### Option 1: Share Existing Service Account (Simplest) ✅

**Use the same service account for both bots:**

```bash
# LINE Bot
gcloud run deploy line-translator-bot \
  --service-account=user-704@line-trnsltrbt.iam.gserviceaccount.com

# Facebook Messenger Bot
gcloud run deploy messenger-translator-bot \
  --service-account=user-704@line-trnsltrbt.iam.gserviceaccount.com
```

**Pros:**
- ✅ No additional setup needed
- ✅ Same permissions for both bots
- ✅ Simpler IAM management
- ✅ Lower cost (one service account)

**Cons:**
- ⚠️ Both bots share same audit trail (can't distinguish which bot made API calls)
- ⚠️ If one bot is compromised, both are affected (but same risk level)

#### Option 2: Separate Service Accounts (More Secure)

**Create dedicated service accounts for each bot:**

```bash
# Create service account for Messenger bot
gcloud iam service-accounts create messenger-bot-sa \
  --display-name="Messenger Translator Bot Service Account" \
  --project=line-trnsltrbt

# Grant same permissions
gcloud projects add-iam-policy-binding line-trnsltrbt \
  --member="serviceAccount:messenger-bot-sa@line-trnsltrbt.iam.gserviceaccount.com" \
  --role="roles/cloudtranslate.user"

# ... (grant other roles)
```

**Pros:**
- ✅ Better audit trail (can see which bot made which calls)
- ✅ Principle of least privilege (can customize permissions per bot)
- ✅ Isolation (compromise of one doesn't affect the other)

**Cons:**
- ❌ More setup and maintenance
- ❌ More IAM policies to manage
- ❌ Slightly higher cost (minimal)

### Recommendation: Option 1 (Share Service Account)

**For your use case, sharing the service account is recommended because:**
1. Both bots have identical permission requirements
2. Simpler to manage
3. Lower operational overhead
4. Both bots are part of the same application (translator bot)

## Google Cloud Project Structure

### Option 1: Same GCP Project (Recommended) ✅

**Keep both bots in the same Google Cloud project:**

```
Project: line-trnsltrbt
├── Cloud Run Services:
│   ├── line-translator-bot
│   └── messenger-translator-bot
├── Service Account:
│   └── user-704@line-trnsltrbt.iam.gserviceaccount.com (shared)
├── Firestore:
│   └── user_settings collection (shared or separate databases)
├── Secret Manager:
│   ├── line-channel-access-token
│   ├── line-channel-secret
│   ├── facebook-page-access-token
│   └── facebook-app-secret
└── Artifact Registry:
    └── line-trnsltrbt (shared repository)
```

**Pros:**
- ✅ Unified billing and quotas
- ✅ Shared resources (Firestore, APIs)
- ✅ Easier cross-service communication
- ✅ Single project to manage

**Cons:**
- ⚠️ Resource limits shared (but unlikely to be an issue)

### Option 2: Separate GCP Projects

**Create separate projects for each bot:**

```
Project: line-trnsltrbt
└── line-translator-bot

Project: messenger-trnsltrbt
└── messenger-translator-bot
```

**When This Makes Sense:**
- Different billing accounts
- Different teams/organizations
- Need complete isolation
- Compliance/regulatory requirements

**For your use case: Same project is recommended.**

## Firestore Database Strategy

### Option 1: Shared Database (Recommended) ✅

**Use the same Firestore database, different document prefixes:**

```
Collection: user_settings
├── line:{user_id}          # LINE user settings
├── messenger:{user_id}     # Messenger user settings
├── line:group:{group_id}    # LINE group settings
└── messenger:thread:{thread_id}  # Messenger thread settings
```

**Or use separate collections:**

```
Collection: line_user_settings
Collection: messenger_user_settings
```

**Pros:**
- ✅ Single database to manage
- ✅ Unified backup/restore
- ✅ Lower cost (one database)

### Option 2: Separate Databases

**Use different Firestore databases:**

```python
# LINE bot
FIRESTORE_DATABASE_ID = "line-trnsltrbt-db"

# Messenger bot
FIRESTORE_DATABASE_ID = "messenger-trnsltrbt-db"
```

**Pros:**
- ✅ Complete data isolation
- ✅ Independent scaling

**Cons:**
- ❌ More databases to manage
- ❌ Higher cost (minimal)

**Recommendation: Shared database with different document IDs/collections.**

## Deployment Strategy

### Recommended: Separate Cloud Run Services

**Deploy each bot as a separate Cloud Run service:**

```bash
# LINE Bot
gcloud run deploy line-translator-bot \
  --image=asia-east1-docker.pkg.dev/line-trnsltrbt/line-trnsltrbt/line-translator-bot:latest \
  --service-account=user-704@line-trnsltrbt.iam.gserviceaccount.com \
  --set-secrets=LINE_CHANNEL_ACCESS_TOKEN=line-channel-access-token:latest,LINE_CHANNEL_SECRET=line-channel-secret:latest

# Messenger Bot
gcloud run deploy messenger-translator-bot \
  --image=asia-east1-docker.pkg.dev/line-trnsltrbt/line-trnsltrbt/messenger-translator-bot:latest \
  --service-account=user-704@line-trnsltrbt.iam.gserviceaccount.com \
  --set-secrets=FACEBOOK_PAGE_ACCESS_TOKEN=facebook-page-access-token:latest,FACEBOOK_APP_SECRET=facebook-app-secret:latest
```

**Benefits:**
- ✅ Independent scaling
- ✅ Independent deployments
- ✅ Independent monitoring
- ✅ Can update one without affecting the other

## Implementation Plan

### Step 1: Keep Current Repository Structure ✅
- No changes needed - current monorepo structure is perfect

### Step 2: Share Service Account ✅
- Use existing `user-704@line-trnsltrbt.iam.gserviceaccount.com` for both bots
- No additional IAM setup needed (already has required permissions)

### Step 3: Create Messenger Deployment Files
- Create `cloudbuild-messenger.yaml` for Messenger bot
- Create `deploy-messenger.sh` script (or extend existing)
- Update `Dockerfile` if needed (or create separate one)

### Step 4: Configure Secrets
- Add Facebook secrets to Secret Manager:
  ```bash
  echo -n 'your_token' | gcloud secrets create facebook-page-access-token --data-file=-
  echo -n 'your_secret' | gcloud secrets create facebook-app-secret --data-file=-
  ```

### Step 5: Deploy Both Services
- Deploy LINE bot (existing)
- Deploy Messenger bot (new)

## Summary

### ✅ Recommended Structure

1. **Repository**: Monorepo (keep both bots together)
2. **GCP Project**: Same project (`line-trnsltrbt`)
3. **Service Account**: Shared (`user-704@line-trnsltrbt.iam.gserviceaccount.com`)
4. **Cloud Run**: Separate services (`line-translator-bot` and `messenger-translator-bot`)
5. **Firestore**: Shared database, separate document IDs/collections
6. **Secrets**: Separate secrets in Secret Manager

### Benefits

- ✅ Maximum code reuse
- ✅ Simple maintenance
- ✅ Unified billing
- ✅ Shared infrastructure
- ✅ Independent deployments
- ✅ No additional service account setup needed
