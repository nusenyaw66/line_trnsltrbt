# Deployment Structure: Two Services, Two Images

## Overview

Yes, you will have **2 Cloud Run services** and **2 Docker images**, each deployed independently.

## Architecture Diagram

```
Google Cloud Project: line-trnsltrbt
│
├── Artifact Registry Repository: line-trnsltrbt
│   ├── Image 1: line-translator-bot:latest
│   │   └── Built from: Dockerfile
│   │   └── Contains: line_translator_bot.py + shared code
│   │
│   └── Image 2: messenger-translator-bot:latest
│       └── Built from: Dockerfile.messenger
│       └── Contains: messenger_translator_bot.py + shared code
│
├── Cloud Run Services
│   ├── Service 1: line-translator-bot
│   │   ├── Image: line-translator-bot:latest
│   │   ├── URL: https://line-translator-bot-xxx.run.app
│   │   ├── Secrets: LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET
│   │   └── Service Account: user-704@line-trnsltrbt.iam.gserviceaccount.com
│   │
│   └── Service 2: messenger-translator-bot
│       ├── Image: messenger-translator-bot:latest
│       ├── URL: https://messenger-translator-bot-xxx.run.app
│       ├── Secrets: FACEBOOK_PAGE_ACCESS_TOKEN, FACEBOOK_APP_SECRET, FACEBOOK_VERIFY_TOKEN
│       └── Service Account: user-704@line-trnsltrbt.iam.gserviceaccount.com (SHARED)
│
└── Shared Resources
    ├── Service Account: user-704@line-trnsltrbt.iam.gserviceaccount.com
    ├── Firestore Database: (shared, different document IDs)
    └── Secret Manager: (separate secrets for each bot)
```

## Deployment Flow

### 1. Deploy LINE Bot (`./deploy_gcs.sh`)

```bash
./deploy_gcs.sh
```

**What it does:**
1. Builds Docker image using `Dockerfile`
2. Tags image as: `asia-east1-docker.pkg.dev/line-trnsltrbt/line-trnsltrbt/line-translator-bot:latest`
3. Pushes to Artifact Registry
4. Deploys Cloud Run service: `line-translator-bot`
5. Configures secrets: `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET`

**Result:**
- ✅ 1 Docker image in Artifact Registry
- ✅ 1 Cloud Run service running

### 2. Deploy Messenger Bot (`./deploy-messenger.sh`)

```bash
./deploy-messenger.sh
```

**What it does:**
1. Builds Docker image using `Dockerfile.messenger`
2. Tags image as: `asia-east1-docker.pkg.dev/line-trnsltrbt/line-trnsltrbt/messenger-translator-bot:latest`
3. Pushes to Artifact Registry
4. Deploys Cloud Run service: `messenger-translator-bot`
5. Configures secrets: `FACEBOOK_PAGE_ACCESS_TOKEN`, `FACEBOOK_APP_SECRET`, `FACEBOOK_VERIFY_TOKEN`

**Result:**
- ✅ 1 Docker image in Artifact Registry (separate from LINE bot)
- ✅ 1 Cloud Run service running (separate from LINE bot)

## Image Details

### Image 1: `line-translator-bot`
- **Dockerfile**: `Dockerfile` (default)
- **Entry Point**: `gunicorn -b 0.0.0.0:8080 line_translator_bot:app`
- **Contains**:
  - `line_translator_bot.py` (LINE bot code)
  - `gcs_translate.py` (shared)
  - `gcs_audio.py` (shared)
  - All dependencies from `pyproject.toml`

### Image 2: `messenger-translator-bot`
- **Dockerfile**: `Dockerfile.messenger`
- **Entry Point**: `gunicorn -b 0.0.0.0:8080 messenger_translator_bot:app`
- **Contains**:
  - `messenger_translator_bot.py` (Messenger bot code)
  - `gcs_translate.py` (shared)
  - `gcs_audio.py` (shared)
  - All dependencies from `pyproject.toml`

## Key Points

### ✅ Independent Deployments
- Each bot deploys independently
- Update one without affecting the other
- Different URLs for webhooks

### ✅ Shared Code in Each Image
- Both images contain the same shared code (`gcs_translate.py`, `gcs_audio.py`)
- Code is duplicated in each image (normal Docker practice)
- Updates to shared code require rebuilding both images

### ✅ Same Artifact Registry
- Both images stored in: `asia-east1-docker.pkg.dev/line-trnsltrbt/line-trnsltrbt/`
- Different image names prevent conflicts
- Can view both in same repository

### ✅ Same Service Account
- Both services use: `user-704@line-trnsltrbt.iam.gserviceaccount.com`
- Same permissions for both
- Simpler IAM management

### ✅ Different Secrets
- LINE bot: `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET`
- Messenger bot: `FACEBOOK_PAGE_ACCESS_TOKEN`, `FACEBOOK_APP_SECRET`, `FACEBOOK_VERIFY_TOKEN`
- Each service only gets its own secrets

## Image Sizes

Both images will be similar in size because:
- Same base image: `python:3.13-slim`
- Same dependencies (mostly)
- Same shared code files
- Only difference: which bot file is the entry point

**Estimated size**: ~500-800 MB each (depending on dependencies)

## Storage Cost

- **Artifact Registry**: ~$0.10 per GB/month
- **Two images**: ~1-1.6 GB total
- **Monthly cost**: ~$0.10-0.16/month for storage

## Deployment Commands Summary

```bash
# Deploy LINE bot (creates 1 image + 1 service)
./deploy_gcs.sh

# Deploy Messenger bot (creates 1 image + 1 service)
./deploy-messenger.sh

# View all images
gcloud artifacts docker images list asia-east1-docker.pkg.dev/line-trnsltrbt/line-trnsltrbt

# View all Cloud Run services
gcloud run services list --region=asia-east1
```

## Verification

After deploying both:

```bash
# Check Cloud Run services
gcloud run services list --region=asia-east1 --project=line-trnsltrbt

# Should show:
# NAME                      REGION      URL
# line-translator-bot        asia-east1  https://line-translator-bot-xxx.run.app
# messenger-translator-bot  asia-east1  https://messenger-translator-bot-xxx.run.app

# Check Artifact Registry images
gcloud artifacts docker images list asia-east1-docker.pkg.dev/line-trnsltrbt/line-trnsltrbt

# Should show:
# IMAGE                                    TAGS
# line-translator-bot                     latest, v0.1, ...
# messenger-translator-bot                latest, v0.1, ...
```

## Summary

✅ **2 Docker images** (one per bot)  
✅ **2 Cloud Run services** (one per bot)  
✅ **1 Artifact Registry repository** (shared)  
✅ **1 Service Account** (shared)  
✅ **1 GCP Project** (shared)  
✅ **Separate secrets** (per bot)  

Each deployment script creates one complete deployment (image + service).
