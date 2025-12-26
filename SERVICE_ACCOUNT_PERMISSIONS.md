# Service Account Permissions for Voice Translation

## Required Permissions

For the voice translation feature to work, your Cloud Run service account needs permissions to use the following Google Cloud APIs:

### 1. Speech-to-Text API
- **Role**: `roles/speech.client`
- **Purpose**: Allows the service account to use the Speech-to-Text API to convert audio to text

### 2. Text-to-Speech API
- **Role**: `roles/cloudtts.user`
- **Purpose**: Allows the service account to use the Text-to-Speech API to convert text to audio

### 3. Cloud Storage
- **Role**: `roles/storage.objectCreator` (or `roles/storage.admin`)
- **Purpose**: Allows uploading audio files to GCS for LINE Bot API

### 4. Translation API
- **Role**: Already configured (via existing setup)
- **Purpose**: Translate text between languages

## Automatic Setup

The `deploy_gcs.sh` script automatically:
1. ✅ Enables the required APIs (`speech.googleapis.com`, `texttospeech.googleapis.com`)
2. ✅ Grants `roles/speech.client` to the service account
3. ✅ Grants `roles/cloudtts.user` to the service account

## Manual Setup (if needed)

If you need to set up permissions manually:

```bash
# Set variables
PROJECT_ID="line-trnsltrbt"
SERVICE_ACCOUNT="user-704@line-trnsltrbt.iam.gserviceaccount.com"

# Enable APIs
gcloud services enable speech.googleapis.com \
    texttospeech.googleapis.com \
    --project="$PROJECT_ID"

# Grant Speech-to-Text permissions
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/speech.client"

# Grant Text-to-Speech permissions
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/cloudtts.user"
```

## Verify Permissions

To verify the service account has the correct permissions:

```bash
# List IAM policy bindings for the service account
gcloud projects get-iam-policy "$PROJECT_ID" \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:${SERVICE_ACCOUNT}" \
    --format="table(bindings.role)"
```

You should see:
- `roles/speech.client`
- `roles/cloudtts.user`
- `roles/storage.admin` (or similar)
- Other existing roles

## Troubleshooting

### Error: "Permission denied" or "403 Forbidden"
- Verify APIs are enabled: `gcloud services list --enabled --project="$PROJECT_ID"`
- Check service account has the roles listed above
- Ensure the service account is correctly set in Cloud Run deployment

### Error: "API not enabled"
- Enable the APIs manually if deployment script didn't run:
  ```bash
  gcloud services enable speech.googleapis.com texttospeech.googleapis.com
  ```

## Alternative: Using Service Usage Consumer Role

If you prefer a broader permission (allows using any enabled API):

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/serviceusage.serviceUsageConsumer"
```

**Note**: This is less secure but simpler. The specific roles (`speech.client`, `cloudtts.user`) are recommended for production.

