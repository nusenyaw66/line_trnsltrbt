# Audio Upload Fix - Using Google Cloud Storage

## Problem
LINE Bot API requires a publicly accessible URL for `AudioMessage`, not a direct upload. The previous implementation tried to upload directly to LINE's Content API, which doesn't work for audio messages.

## Solution
Changed the implementation to:
1. Upload audio files to Google Cloud Storage (GCS)
2. Make the file publicly accessible
3. Use the public GCS URL in the `AudioMessage`

## Changes Made

### 1. Added Google Cloud Storage Dependency
- Added `google-cloud-storage = "^2.18.0"` to `pyproject.toml`

### 2. Updated `upload_audio_to_line()` → `upload_audio_to_gcs()`
- Replaced direct LINE upload with GCS upload
- Creates/uploads to bucket: `{PROJECT_ID}-audio-temp` (or from `GCS_AUDIO_BUCKET` env var)
- Makes files publicly readable
- Returns public URL for LINE to access

### 3. Bucket Configuration
The function will:
- Use bucket name from `GCS_AUDIO_BUCKET` environment variable, or
- Default to `{PROJECT_ID}-audio-temp` (e.g., `line-trnsltrbt-audio-temp`)
- Automatically create the bucket if it doesn't exist
- Store files in `audio/` prefix with UUID filenames

## Setup Required

### 1. Create GCS Bucket (Optional - auto-created)
The bucket will be auto-created, but you can create it manually:

```bash
gsutil mb -p line-trnsltrbt -l asia-east1 gs://line-trnsltrbt-audio-temp
```

### 2. Set Bucket Name (Optional)
If you want to use a custom bucket name, set environment variable:

```bash
export GCS_AUDIO_BUCKET=your-custom-bucket-name
```

Or in Cloud Run deployment, add:
```yaml
- "--set-env-vars"
- "GCS_AUDIO_BUCKET=your-custom-bucket-name"
```

### 3. Service Account Permissions
Ensure your Cloud Run service account has:
- `roles/storage.objectCreator` - to upload files
- `roles/storage.objectViewer` - to make files public (or use bucket-level permissions)

The service account should already have these if it has broader storage permissions.

### 4. Bucket Lifecycle Policy (Recommended)
Set up lifecycle policy to auto-delete old audio files:

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

# Apply to bucket WSX1226: set on 12/26
gsutil lifecycle set lifecycle.json gs://line-trnsltrbt-audio-temp
```

This will automatically delete files older than 1 day to save storage costs.

## Testing

After deployment, test with:
1. Set language pair: `/set language pair en id`
2. Send a voice message
3. Verify audio response is received
4. Check GCS bucket for uploaded files

## Cost Considerations

- **Storage**: Minimal cost for temporary audio files (auto-deleted after 1 day)
- **Bandwidth**: Small cost for public access (LINE downloading audio)
- **Operations**: Write/read operations are very cheap

With lifecycle policy, costs should be negligible (< $0.01/month for typical usage).

## Troubleshooting

### Error: "Failed to upload audio"
- Check service account has Storage permissions
- Verify bucket exists or can be created
- Check Cloud Run logs for detailed error messages

### Error: "Audio message not received"
- Verify GCS file is publicly accessible: `gsutil acl get gs://bucket-name/audio/file.mp3`
- Check URL is accessible: `curl -I <public_url>`
- Verify LINE can access HTTPS URLs (GCS URLs are HTTPS)

