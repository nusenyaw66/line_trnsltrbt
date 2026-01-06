# LINE Translator Bot - Deployment Guide

## Overview

This document consolidates all deployment information for the LINE Translator Bot, including Cloud Run deployment, service account permissions, Google Cloud Storage setup, and infrastructure configuration.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Service Account Setup](#service-account-setup)
3. [Google Cloud APIs](#google-cloud-apis)
4. [Infrastructure Setup](#infrastructure-setup)
5. [Deployment Configuration](#deployment-configuration)
6. [Deployment Process](#deployment-process)
7. [Post-Deployment Setup](#post-deployment-setup)
8. [Monitoring & Troubleshooting](#monitoring--troubleshooting)

---

## Prerequisites

### Required Tools
- `gcloud` CLI installed and configured
- Docker (for local testing)
- Poetry (for dependency management)
- Access to Google Cloud Project: `line-trnsltrbt`

### Authentication
```bash
# Log in with your personal Google Cloud account
gcloud auth login

# Set ADC to impersonate the service account (for local testing)
gcloud auth application-default login --impersonate-service-account=user-704@line-trnsltrbt.iam.gserviceaccount.com

# Update ADC quota project
gcloud auth application-default set-quota-project line-trnsltrbt
```

---

## Service Account Setup

### Service Account Details
- **Service Account**: `user-704@line-trnsltrbt.iam.gserviceaccount.com`
- **Project ID**: `line-trnsltrbt`

### Required IAM Roles

The service account needs the following roles for the application to function:

#### 1. Translation API
- **Role**: `roles/cloudtranslate.user` (or existing translation permissions)
- **Purpose**: Translate text between languages

#### 2. Speech-to-Text API
- **Role**: `roles/speech.client`
- **Purpose**: Convert audio to text for voice translation feature

#### 3. Text-to-Speech API
- **Role**: `roles/cloudtts.user`
- **Purpose**: Convert text to audio (if needed in future)

#### 4. Cloud Storage
- **Roles**: 
  - `roles/storage.objectCreator` - Upload audio files to GCS
  - `roles/storage.objectViewer` - Make files publicly accessible
  - `roles/storage.admin` (alternative, broader permission)
- **Purpose**: Store temporary audio files for LINE Bot API

#### 5. Secret Manager
- **Role**: `roles/secretmanager.secretAccessor`
- **Purpose**: Access LINE channel credentials stored in Secret Manager

#### 6. Cloud Run
- **Role**: `roles/run.invoker` (automatic for service account running the service)
- **Purpose**: Execute Cloud Run service

### Automatic Permission Setup

The `deploy_gcs.sh` script automatically grants the following permissions:
- ✅ Speech-to-Text API permissions (`roles/speech.client`)
- ✅ Text-to-Speech API permissions (`roles/cloudtts.user`)
- ✅ Storage permissions (via `roles/storage.admin`)
- ✅ Secret Manager access (via secret IAM bindings)

### Manual Permission Setup (if needed)

```bash
PROJECT_ID="line-trnsltrbt"
SERVICE_ACCOUNT="user-704@line-trnsltrbt.iam.gserviceaccount.com"

# Grant Speech-to-Text permissions
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/speech.client"

# Grant Text-to-Speech permissions
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/cloudtts.user"

# Grant Storage permissions
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/storage.admin"
```

### Verify Permissions

```bash
# List IAM policy bindings for the service account
gcloud projects get-iam-policy "$PROJECT_ID" \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:${SERVICE_ACCOUNT}" \
    --format="table(bindings.role)"
```

---

## Google Cloud APIs

### Required APIs

The following APIs must be enabled:

1. **Cloud Build API** (`cloudbuild.googleapis.com`)
2. **Cloud Run API** (`run.googleapis.com`)
3. **Artifact Registry API** (`artifactregistry.googleapis.com`)
4. **Secret Manager API** (`secretmanager.googleapis.com`)
5. **Cloud Translation API** (`translate.googleapis.com`)
6. **Cloud Storage API** (`storage.googleapis.com`)
7. **Speech-to-Text API** (`speech.googleapis.com`)
8. **Text-to-Speech API** (`texttospeech.googleapis.com`)

### Automatic API Enablement

The `deploy_gcs.sh` script automatically enables all required APIs.

### Manual API Enablement

```bash
gcloud services enable \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com \
    translate.googleapis.com \
    storage.googleapis.com \
    speech.googleapis.com \
    texttospeech.googleapis.com \
    --project="line-trnsltrbt"
```

### Verify APIs

```bash
gcloud services list --enabled --project="line-trnsltrbt"
```

---

## Infrastructure Setup

### Artifact Registry Repository

**Repository Name**: `line-trnsltrbt`  
**Location**: `asia-east1`  
**Format**: Docker

#### Create Repository (one-time setup)

The deployment script creates this automatically, but you can create it manually:

```bash
gcloud artifacts repositories create line-trnsltrbt \
    --repository-format=docker \
    --location=asia-east1 \
    --description="LINE Translator Bot Docker images" \
    --project=line-trnsltrbt
```

### Google Cloud Storage Bucket

**Bucket Name**: `line-trnsltrbt-audio-temp` (default)  
**Custom Bucket**: Set via `GCS_AUDIO_BUCKET` environment variable  
**Purpose**: Store temporary audio files for LINE Bot API (audio messages require public URLs)

#### Bucket Configuration

The bucket is auto-created by the application if it doesn't exist. To create manually:

```bash
gsutil mb -p line-trnsltrbt -l asia-east1 gs://line-trnsltrbt-audio-temp
```

#### Lifecycle Policy (Recommended)

Set up automatic deletion of old audio files to minimize storage costs:

```bash
# Create lifecycle policy file
cat > lifecycle.json << EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 1}
      }
    ]
  }
}
EOF

# Apply to bucket
gsutil lifecycle set lifecycle.json gs://line-trnsltrbt-audio-temp
```

This automatically deletes files older than 1 day.

#### Custom Bucket Name

To use a custom bucket name, set the environment variable in Cloud Run:

```yaml
--set-env-vars
GCS_AUDIO_BUCKET=your-custom-bucket-name
```

### Secret Manager

Secrets are stored in Google Cloud Secret Manager and automatically injected into Cloud Run.

#### Required Secrets

1. **LINE Channel Access Token**
   - Secret Name: `line-channel-access-token`
   - Environment Variable: `LINE_CHANNEL_ACCESS_TOKEN`

2. **LINE Channel Secret**
   - Secret Name: `line-channel-secret`
   - Environment Variable: `LINE_CHANNEL_SECRET`

#### Create Secrets Manually

```bash
PROJECT_ID="line-trnsltrbt"
SERVICE_ACCOUNT="user-704@line-trnsltrbt.iam.gserviceaccount.com"

# Create access token secret
echo -n 'YOUR_ACCESS_TOKEN' | gcloud secrets create line-channel-access-token \
    --data-file=- \
    --replication-policy="automatic" \
    --project="$PROJECT_ID"

# Create channel secret
echo -n 'YOUR_CHANNEL_SECRET' | gcloud secrets create line-channel-secret \
    --data-file=- \
    --replication-policy="automatic" \
    --project="$PROJECT_ID"

# Grant service account access
gcloud secrets add-iam-policy-binding line-channel-access-token \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="$PROJECT_ID"

gcloud secrets add-iam-policy-binding line-channel-secret \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="$PROJECT_ID"
```

#### Update Secrets

```bash
# Update access token
echo -n 'NEW_TOKEN' | gcloud secrets versions add line-channel-access-token --data-file=-

# Update channel secret
echo -n 'NEW_SECRET' | gcloud secrets versions add line-channel-secret --data-file=-
```

---

## Deployment Configuration

### Cloud Run Service Configuration

**Service Name**: `line-translator-bot`  
**Region**: `asia-east1`  
**Port**: `8080`

#### Resource Configuration

**Current Settings** (from `cloudbuild.yaml`):
- **Memory**: `2Gi`
- **CPU**: `2`
- **Min Instances**: `0` (scale to zero)
- **Max Instances**: `10`

**Recommended Settings** (for voice translation):
- **Memory**: `1Gi` (sufficient for audio buffering)
- **CPU**: `1-2` (1 CPU sufficient, 2 for better concurrency)
- **Min Instances**: `0` (for cost efficiency)
- **Max Instances**: `10` (adjust based on expected traffic)

**Note**: The current deployment uses 2Gi memory and 2 CPU. For text-only translation, 512Mi memory and 1 CPU is sufficient. Voice translation requires additional memory for audio processing.

#### Environment Variables

- `APP_VERSION`: Application version (from `.env` file)
- `GCS_AUDIO_BUCKET`: Optional custom GCS bucket name
- `LINE_CHANNEL_ACCESS_TOKEN`: Injected from Secret Manager
- `LINE_CHANNEL_SECRET`: Injected from Secret Manager

### Docker Configuration

**Base Image**: `python:3.13-slim`  
**Platform**: `linux/amd64` (required for Cloud Run)

The Dockerfile:
1. Installs system dependencies for building Python packages
2. Uses Poetry to install Python dependencies
3. Copies application code
4. Runs the application with Gunicorn on port 8080

### Build Configuration

**Build File**: `cloudbuild.yaml`

The build process:
1. Builds Docker image with `linux/amd64` platform
2. Tags image with version and timestamp
3. Pushes to Artifact Registry
4. Deploys to Cloud Run with configuration

---

## Deployment Process

### Quick Deployment

Use the automated deployment script:

```bash
./deploy_gcs.sh
```

### Custom Deployment

With custom environment variables:

```bash
GCP_PROJECT_ID=your-project \
SERVICE_NAME=my-bot \
./deploy_gcs.sh
```

### What the Deployment Script Does

1. ✅ Checks prerequisites (gcloud CLI, authentication)
2. ✅ Sets GCP project
3. ✅ Enables required APIs
4. ✅ Creates Artifact Registry repository (if needed)
5. ✅ Reads APP_VERSION from `.env` file
6. ✅ Creates/updates secrets from `.env` file (if `secret_update=true`)
7. ✅ Grants IAM permissions to service account
8. ✅ Grants Cloud Build permissions
9. ✅ Builds and deploys to Cloud Run

### Manual Deployment Steps

If you prefer manual deployment:

```bash
PROJECT_ID="line-trnsltrbt"
REGION="asia-east1"
SERVICE_NAME="line-translator-bot"
TAG="v$(date +%Y%m%d-%H%M%S)"

# Build and deploy
gcloud builds submit \
    --config cloudbuild.yaml \
    --substitutions=_REGION="$REGION",_SERVICE="$SERVICE_NAME",_TAG="$TAG" \
    --project="$PROJECT_ID"
```

### Deployment Tag

The deployment script uses a fixed tag `v0.0.4`. To use timestamp-based tags, modify the script:

```bash
# In deploy_gcs.sh, change:
TAG="v0.0.4"
# To:
TAG="v$(date +%Y%m%d-%H%M%S)"
```

---

## Post-Deployment Setup

### Verify Deployment

```bash
# Get service URL
gcloud run services describe line-translator-bot \
    --region=asia-east1 \
    --format="value(status.url)" \
    --project=line-trnsltrbt

# View logs
gcloud run services logs read line-translator-bot \
    --region=asia-east1 \
    --project=line-trnsltrbt
```

### LINE Webhook Configuration

1. Go to LINE Developers Console
2. Navigate to your channel
3. Set webhook URL to your Cloud Run service URL
4. Verify webhook is accessible (should return 200 OK)

### Test Voice Translation

1. Set language pair: `/set language pair en id`
2. Send a voice message in English or Indonesian
3. Verify the bot responds with translated text (voice-to-text only)

---

## Monitoring & Troubleshooting

### View Logs

```bash
# Real-time logs
gcloud run services logs tail line-translator-bot \
    --region=asia-east1 \
    --project=line-trnsltrbt

# Recent logs
gcloud run services logs read line-translator-bot \
    --region=asia-east1 \
    --project=line-trnsltrbt \
    --limit=50
```

### Common Issues

#### 1. Permission Denied (403 Forbidden)

**Symptoms**: API calls fail with permission errors

**Solutions**:
- Verify APIs are enabled: `gcloud services list --enabled`
- Check service account has required roles
- Ensure service account is correctly set in Cloud Run

#### 2. Secret Access Failed

**Symptoms**: Application can't access secrets

**Solutions**:
- Verify secrets exist: `gcloud secrets list`
- Check service account has `roles/secretmanager.secretAccessor`
- Verify secret names match in Cloud Run configuration

#### 3. Audio Upload Failed

**Symptoms**: Voice translation fails to upload audio

**Solutions**:
- Check GCS bucket exists and is accessible
- Verify service account has Storage permissions
- Check bucket is publicly accessible (for LINE API)
- Verify GCS file URL is accessible: `curl -I <public_url>`

#### 4. API Not Enabled

**Symptoms**: API calls fail with "API not enabled" error

**Solutions**:
```bash
# Enable missing APIs
gcloud services enable speech.googleapis.com texttospeech.googleapis.com
```

#### 5. Memory Issues

**Symptoms**: Container crashes or out of memory errors

**Solutions**:
- Increase memory allocation in `cloudbuild.yaml`
- Check audio file sizes (should be small)
- Monitor Cloud Run metrics for memory usage

### Cost Monitoring

#### Expected Costs

- **Cloud Run**: Based on memory, CPU, and request volume
  - 1Gi memory + 2 CPU: ~$0.00002400 per request (minimum)
  - Scale-to-zero helps minimize costs when idle
  
- **Speech-to-Text API**: Per 15-second increment
  - Check current pricing: https://cloud.google.com/speech-to-text/pricing

- **Translation API**: Per character
  - Check current pricing: https://cloud.google.com/translate/pricing

- **Cloud Storage**: Minimal (auto-deleted after 1 day)
  - Storage: ~$0.020 per GB/month
  - Operations: Very cheap
  - With lifecycle policy: Negligible cost (< $0.01/month)

#### Monitor Costs

```bash
# View Cloud Run metrics
gcloud run services describe line-translator-bot \
    --region=asia-east1 \
    --format="value(status.conditions)"

# Check API usage in Cloud Console
# - Navigate to APIs & Services > Dashboard
# - View usage for Speech-to-Text, Translation, etc.
```

---

## Local Development

### Local Testing with Docker

```bash
# Build image
docker build -t line_trnsltrbt:dev .

# Run container
docker run -p 8080:8080 \
    --env-file .env \
    -v $(pwd)/gcp-key.json:/app/gcp-key.json \
    -e GOOGLE_APPLICATION_CREDENTIALS=/app/gcp-key.json \
    line_trnsltrbt:dev
```

### Local Testing with Poetry

```bash
# Set up environment
poetry env use 3.13
poetry install --no-root

# Activate shell
eval $(poetry env activate)

# Run application
python line_translator_bot.py

# Exit shell
deactivate
```

### Expose Local Server

Use ngrok to expose local server for LINE webhook validation:

```bash
ngrok http 8080
```

Update LINE webhook URL to ngrok URL for testing.

---

## Summary

### Key Deployment Points

1. **Service Account**: `user-704@line-trnsltrbt.iam.gserviceaccount.com`
2. **Project**: `line-trnsltrbt`
3. **Region**: `asia-east1`
4. **Service**: `line-translator-bot`
5. **Bucket**: `line-trnsltrbt-audio-temp` (auto-created)
6. **Repository**: `line-trnsltrbt` in Artifact Registry

### Required Permissions Summary

- Translation API access
- Speech-to-Text API (`roles/speech.client`)
- Text-to-Speech API (`roles/cloud.texttospeech.user`)
- Cloud Storage (`roles/storage.admin` or specific roles)
- Secret Manager (`roles/secretmanager.secretAccessor`)


### Deployment Command

```bash
./deploy_gcs.sh
```

This single command handles all setup and deployment tasks.

---

## Additional Resources

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Artifact Registry Documentation](https://cloud.google.com/artifact-registry/docs)
- [Secret Manager Documentation](https://cloud.google.com/secret-manager/docs)
- [Speech-to-Text API Documentation](https://cloud.google.com/speech-to-text/docs)
- [Translation API Documentation](https://cloud.google.com/translate/docs)

