#!/bin/bash
# Deployment script for Facebook Messenger Translator Bot to Google Cloud Run
# This script handles setup and deployment in one go

set -e

# WSX: Flag for Secrets update - false to skip update
secret_update=false

# Configuration (override with environment variables)
PROJECT_ID="${GCP_PROJECT_ID:-line-trnsltrbt}"
REGION="${GCP_REGION:-asia-east1}"
SERVICE_NAME="${SERVICE_NAME:-messenger-translator-bot}"
REPOSITORY_NAME="line-trnsltrbt"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-user-704@line-trnsltrbt.iam.gserviceaccount.com}"
SECRET_ACCESS_TOKEN="${SECRET_ACCESS_TOKEN:-facebook-page-access-token}"
SECRET_APP_SECRET="${SECRET_APP_SECRET:-facebook-app-secret}"
SECRET_VERIFY_TOKEN="${SECRET_VERIFY_TOKEN:-facebook-verify-token}"

# Load .env file if it exists (for APP_VERSION and other variables)
if [ -f .env ]; then
    set -a
    source .env 2>/dev/null || {
        # Fallback: parse line by line
        while IFS= read -r line || [ -n "$line" ]; do
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$line" ]] && continue
            [[ "$line" =~ = ]] && export "$line"
        done < .env
    }
    set +a
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Facebook Messenger Translator Bot - GCS Deployment ===${NC}"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Service: $SERVICE_NAME"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}ERROR: gcloud CLI is not installed${NC}"
    echo "Install from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if logged in
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo -e "${YELLOW}Not logged in to gcloud. Please run: gcloud auth login${NC}"
    exit 1
fi

# Set project
echo -e "${GREEN}Setting GCP project to $PROJECT_ID...${NC}"
gcloud config set project "$PROJECT_ID"

# Enable required APIs
echo -e "${GREEN}Enabling required APIs...${NC}"
gcloud services enable cloudbuild.googleapis.com \
    run.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com \
    translate.googleapis.com \
    storage.googleapis.com \
    speech.googleapis.com \
    texttospeech.googleapis.com \
    firestore.googleapis.com \
    --project="$PROJECT_ID" 2>/dev/null || true

# Create Artifact Registry repository if it doesn't exist
echo -e "${GREEN}Checking Artifact Registry repository...${NC}"
if ! gcloud artifacts repositories describe "$REPOSITORY_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" 2>/dev/null; then
    echo -e "${YELLOW}Repository not found. Creating...${NC}"
    gcloud artifacts repositories create "$REPOSITORY_NAME" \
        --repository-format=docker \
        --location="$REGION" \
        --description="Translator Bot Docker images" \
        --project="$PROJECT_ID"
fi

# Grant service account permissions (if needed)
echo -e "${GREEN}Checking service account permissions...${NC}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT}"

# Grant Speech-to-Text permissions
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/speech.client" \
    2>/dev/null || true

# Grant Text-to-Speech permissions
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/cloudtts.user" \
    2>/dev/null || true

# Grant Storage permissions
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/storage.admin" \
    2>/dev/null || true

# Grant Translation permissions
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/cloudtranslate.user" \
    2>/dev/null || true

# Grant Firestore permissions
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/datastore.user" \
    2>/dev/null || true

# Grant Cloud Build service account necessary permissions to deploy
# Using the user-managed service account for Cloud Build to ensure it has all API privileges
echo -e "${GREEN}Checking Cloud Build service account permissions...${NC}"
# Use the same service account as Cloud Run (user-managed, has all API privileges)
CLOUDBUILD_SA="${SERVICE_ACCOUNT}"
# Convert email format to full resource name format for gcloud builds submit
CLOUDBUILD_SA_FULL="projects/${PROJECT_ID}/serviceAccounts/${CLOUDBUILD_SA}"

echo "Using service account for Cloud Build: ${CLOUDBUILD_SA}"
echo "This ensures Cloud Build has the same API privileges as the Cloud Run service."

# Allow Cloud Build (using user-managed SA) to push to Artifact Registry
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="roles/artifactregistry.writer" \
    2>/dev/null || true

# Allow Cloud Build (using user-managed SA) to deploy to Cloud Run
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="roles/run.admin" \
    2>/dev/null || true

# Allow Cloud Build (using user-managed SA) to act as itself (for Cloud Run deployment)
gcloud iam service-accounts add-iam-policy-binding "${SERVICE_ACCOUNT_EMAIL}" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="roles/iam.serviceAccountUser" \
    --project="$PROJECT_ID" \
    2>/dev/null || true

# Handle secrets
if [ "$secret_update" = true ]; then
    if [ -f .env ]; then
        echo -e "${GREEN}Setting up secrets from .env file...${NC}"
        
        # Load environment variables from .env
        set -a
        source .env 2>/dev/null || {
            # Fallback: parse line by line
            while IFS= read -r line || [ -n "$line" ]; do
                [[ "$line" =~ ^[[:space:]]*# ]] && continue
                [[ -z "$line" ]] && continue
                [[ "$line" =~ = ]] && export "$line"
            done < .env
        }
        set +a
        
        # Create or update FACEBOOK_PAGE_ACCESS_TOKEN secret
        if [ -n "$FACEBOOK_PAGE_ACCESS_TOKEN" ]; then
            if gcloud secrets describe "$SECRET_ACCESS_TOKEN" --project="$PROJECT_ID" &>/dev/null; then
                echo -e "${GREEN}Updating secret: $SECRET_ACCESS_TOKEN${NC}"
                echo -n "$FACEBOOK_PAGE_ACCESS_TOKEN" | gcloud secrets versions add "$SECRET_ACCESS_TOKEN" --data-file=- --project="$PROJECT_ID"
            else
                echo -e "${GREEN}Creating secret: $SECRET_ACCESS_TOKEN${NC}"
                echo -n "$FACEBOOK_PAGE_ACCESS_TOKEN" | gcloud secrets create "$SECRET_ACCESS_TOKEN" --data-file=- --project="$PROJECT_ID"
            fi
        fi
        
        # Create or update FACEBOOK_APP_SECRET secret
        if [ -n "$FACEBOOK_APP_SECRET" ]; then
            if gcloud secrets describe "$SECRET_APP_SECRET" --project="$PROJECT_ID" &>/dev/null; then
                echo -e "${GREEN}Updating secret: $SECRET_APP_SECRET${NC}"
                echo -n "$FACEBOOK_APP_SECRET" | gcloud secrets versions add "$SECRET_APP_SECRET" --data-file=- --project="$PROJECT_ID"
            else
                echo -e "${GREEN}Creating secret: $SECRET_APP_SECRET${NC}"
                echo -n "$FACEBOOK_APP_SECRET" | gcloud secrets create "$SECRET_APP_SECRET" --data-file=- --project="$PROJECT_ID"
            fi
        fi
        
        # Create or update FACEBOOK_VERIFY_TOKEN secret
        if [ -n "$FACEBOOK_VERIFY_TOKEN" ]; then
            if gcloud secrets describe "$SECRET_VERIFY_TOKEN" --project="$PROJECT_ID" &>/dev/null; then
                echo -e "${GREEN}Updating secret: $SECRET_VERIFY_TOKEN${NC}"
                echo -n "$FACEBOOK_VERIFY_TOKEN" | gcloud secrets versions add "$SECRET_VERIFY_TOKEN" --data-file=- --project="$PROJECT_ID"
            else
                echo -e "${GREEN}Creating secret: $SECRET_VERIFY_TOKEN${NC}"
                echo -n "$FACEBOOK_VERIFY_TOKEN" | gcloud secrets create "$SECRET_VERIFY_TOKEN" --data-file=- --project="$PROJECT_ID"
            fi
        fi
        
        # Grant service account access to secrets
        echo -e "${GREEN}Granting service account access to secrets...${NC}"
        for secret in "$SECRET_ACCESS_TOKEN" "$SECRET_APP_SECRET" "$SECRET_VERIFY_TOKEN"; do
            if gcloud secrets describe "$secret" --project="$PROJECT_ID" &>/dev/null; then
                gcloud secrets add-iam-policy-binding "$secret" \
                    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
                    --role="roles/secretmanager.secretAccessor" \
                    --project="$PROJECT_ID" \
                    2>/dev/null || true
            fi
        done
    else
        echo -e "${YELLOW}Warning: .env file not found. Skipping secret setup.${NC}"
        echo "Set secret_update=true and create .env file to update secrets."
    fi
else
    echo -e "${YELLOW}Skipping secret update (set secret_update=true to update secrets)${NC}"
fi

# Verify secrets exist before deployment
echo -e "${GREEN}Verifying secrets exist...${NC}"
for secret in "$SECRET_ACCESS_TOKEN" "$SECRET_APP_SECRET" "$SECRET_VERIFY_TOKEN"; do
    if ! gcloud secrets describe "$secret" --project="$PROJECT_ID" &>/dev/null; then
        echo -e "${RED}ERROR: Secret '$secret' does not exist in Secret Manager!${NC}"
        echo "Please create the secret or set secret_update=true and provide a .env file."
        exit 1
    fi
done
echo -e "${GREEN}All required secrets exist.${NC}"

# Build and deploy
echo -e "${GREEN}Building and deploying to Cloud Run...${NC}"
TAG=$(date +%Y%m%d-%H%M%S)

echo -e "${GREEN}Submitting Cloud Build with service account: ${CLOUDBUILD_SA}${NC}"
gcloud builds submit \
    --config=cloudbuild-messenger.yaml \
    --service-account="${CLOUDBUILD_SA_FULL}" \
    --substitutions=_REGION="$REGION",_SERVICE="$SERVICE_NAME",_TAG="$TAG",_SERVICE_ACCOUNT="$SERVICE_ACCOUNT",_APP_VERSION="${APP_VERSION:-unknown}" \
    --project="$PROJECT_ID"

echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo "Service URL:"
gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(status.url)"

echo ""
echo -e "${GREEN}To update secrets, set secret_update=true and run again.${NC}"
