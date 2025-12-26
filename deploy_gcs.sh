#!/bin/bash
# Deployment script for LINE Translator Bot to Google Cloud Run
# This script handles setup and deployment in one go

set -e

# WSX: Flag for Secrets update - false to skip update
secret_update=false

# Configuration (override with environment variables)
PROJECT_ID="${GCP_PROJECT_ID:-line-trnsltrbt}"
REGION="${GCP_REGION:-asia-east1}"
SERVICE_NAME="${SERVICE_NAME:-line-translator-bot}"
REPOSITORY_NAME="line-trnsltrbt"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-user-704@line-trnsltrbt.iam.gserviceaccount.com}"
SECRET_ACCESS_TOKEN="${SECRET_ACCESS_TOKEN:-line-channel-access-token}"
SECRET_CHANNEL_SECRET="${SECRET_CHANNEL_SECRET:-line-channel-secret}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== LINE Translator Bot - GCS Deployment ===${NC}"
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
    --project="$PROJECT_ID" 2>/dev/null || true

# Create Artifact Registry repository if it doesn't exist
echo -e "${GREEN}Checking Artifact Registry repository...${NC}"
if ! gcloud artifacts repositories describe "$REPOSITORY_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" &>/dev/null; then
    echo -e "${YELLOW}Creating Artifact Registry repository...${NC}"
    gcloud artifacts repositories create "$REPOSITORY_NAME" \
        --repository-format=docker \
        --location="$REGION" \
        --description="LINE Translator Bot Docker images" \
        --project="$PROJECT_ID"
else
    echo -e "${GREEN}Artifact Registry repository already exists${NC}"
fi

# Setup secrets if .env file exists
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT}"
if [ "$secret_update" = true ]; then
    if [ -f .env ]; then
        echo -e "${GREEN}Setting up secrets from .env file...${NC}"
        
        # Source .env file
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
        
        # Create or update LINE_CHANNEL_ACCESS_TOKEN secret
        if [ -n "$LINE_CHANNEL_ACCESS_TOKEN" ]; then
            if gcloud secrets describe "$SECRET_ACCESS_TOKEN" --project="$PROJECT_ID" &>/dev/null; then
                echo -e "${YELLOW}Updating existing secret: $SECRET_ACCESS_TOKEN${NC}"
                echo -n "$LINE_CHANNEL_ACCESS_TOKEN" | gcloud secrets versions add "$SECRET_ACCESS_TOKEN" \
                    --data-file=- \
                    --project="$PROJECT_ID"
            else
                echo -e "${GREEN}Creating secret: $SECRET_ACCESS_TOKEN${NC}"
                echo -n "$LINE_CHANNEL_ACCESS_TOKEN" | gcloud secrets create "$SECRET_ACCESS_TOKEN" \
                    --data-file=- \
                    --replication-policy="automatic" \
                    --project="$PROJECT_ID"
            fi
            
            # Grant Cloud Run service account access to the secret
            gcloud secrets add-iam-policy-binding "$SECRET_ACCESS_TOKEN" \
                --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
                --role="roles/secretmanager.secretAccessor" \
                --project="$PROJECT_ID" 2>/dev/null || true
        else
            echo -e "${YELLOW}Warning: LINE_CHANNEL_ACCESS_TOKEN not found in .env${NC}"
        fi
        
        # Create or update LINE_CHANNEL_SECRET secret
        if [ -n "$LINE_CHANNEL_SECRET" ]; then
            if gcloud secrets describe "$SECRET_CHANNEL_SECRET" --project="$PROJECT_ID" &>/dev/null; then
                echo -e "${YELLOW}Updating existing secret: $SECRET_CHANNEL_SECRET${NC}"
                echo -n "$LINE_CHANNEL_SECRET" | gcloud secrets versions add "$SECRET_CHANNEL_SECRET" \
                    --data-file=- \
                    --project="$PROJECT_ID"
            else
                echo -e "${GREEN}Creating secret: $SECRET_CHANNEL_SECRET${NC}"
                echo -n "$LINE_CHANNEL_SECRET" | gcloud secrets create "$SECRET_CHANNEL_SECRET" \
                    --data-file=- \
                    --replication-policy="automatic" \
                    --project="$PROJECT_ID"
            fi
            
            # Grant Cloud Run service account access to the secret
            gcloud secrets add-iam-policy-binding "$SECRET_CHANNEL_SECRET" \
                --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
                --role="roles/secretmanager.secretAccessor" \
                --project="$PROJECT_ID" 2>/dev/null || true
        else
            echo -e "${YELLOW}Warning: LINE_CHANNEL_SECRET not found in .env${NC}"
        fi
    else
        echo -e "${YELLOW}Warning: .env file not found. Secrets must be set up manually or via environment variables.${NC}"
        echo "To set up secrets manually, run:"
        echo "  echo -n 'YOUR_TOKEN' | gcloud secrets create $SECRET_ACCESS_TOKEN --data-file=-"
        echo "  echo -n 'YOUR_SECRET' | gcloud secrets create $SECRET_CHANNEL_SECRET --data-file=-"
    fi
 else
    echo -e "${GREEN}Skipping secrets update.${NC}"
 fi   

# Grant Cloud Build service account necessary permissions
# Using the project service account for Cloud Build operations
CLOUDBUILD_SA="$SERVICE_ACCOUNT"
# Convert email format to full resource name format for gcloud builds submit
CLOUDBUILD_SA_FULL="projects/${PROJECT_ID}/serviceAccounts/${CLOUDBUILD_SA}"

echo -e "${GREEN}Granting Cloud Build service account permissions...${NC}"
echo "Using service account: ${CLOUDBUILD_SA}"

# Allow Cloud Build to write to GCS (for source code storage bucket)
# Cloud Build automatically creates {PROJECT_ID}_cloudbuild bucket
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="roles/storage.admin" 2>/dev/null || true

# Allow Cloud Build to push to Artifact Registry
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="roles/artifactregistry.writer" 2>/dev/null || true

# Allow Cloud Build to deploy to Cloud Run
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="roles/run.admin" 2>/dev/null || true

# Allow Cloud Build to act as the service account (impersonation for Cloud Run deployment)
# Note: This allows the service account to impersonate itself (may not be needed, but harmless)
gcloud iam service-accounts add-iam-policy-binding "$SERVICE_ACCOUNT" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="roles/iam.serviceAccountUser" \
    --project="$PROJECT_ID" 2>/dev/null || true

# Grant Cloud Run service account permissions for Speech-to-Text and Text-to-Speech APIs
echo -e "${GREEN}Granting Cloud Run service account API permissions...${NC}"
echo "Service account: ${SERVICE_ACCOUNT}"

# Allow service account to use Speech-to-Text API
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/speech.client" \
    --project="$PROJECT_ID" 2>/dev/null || true

# Allow service account to use Text-to-Speech API
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/cloudtts.user" \
    --project="$PROJECT_ID" 2>/dev/null || true

# Generate tag with timestamp
# TAG="v$(date +%Y%m%d-%H%M%S)"
TAG="v0.0.4"

echo -e "${GREEN}Starting Cloud Build deployment...${NC}"
echo -e "${YELLOW}Tag: $TAG${NC}"
echo ""

# Submit build
# Use the service account for Cloud Build operations
echo -e "${GREEN}Submitting Cloud Build with service account: ${CLOUDBUILD_SA}${NC}"
gcloud builds submit \
    --config cloudbuild.yaml \
    --service-account="${CLOUDBUILD_SA_FULL}" \
    --substitutions=_REGION="$REGION",_SERVICE="$SERVICE_NAME",_TAG="$TAG",_LINE_ACCESS_TOKEN_SECRET="$SECRET_ACCESS_TOKEN",_LINE_SECRET_SECRET="$SECRET_CHANNEL_SECRET",_SERVICE_ACCOUNT="$SERVICE_ACCOUNT" \
    --project="$PROJECT_ID"

echo ""
echo -e "${GREEN}=== Deployment Complete! ===${NC}"
echo ""
echo "Service URL:"
gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --format="value(status.url)" \
    --project="$PROJECT_ID"
echo ""
echo "To view logs:"
echo "  gcloud run services logs read $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
echo ""
echo "To update secrets in the future:"
echo "  echo -n 'NEW_TOKEN' | gcloud secrets versions add $SECRET_ACCESS_TOKEN --data-file=-"
echo "  echo -n 'NEW_SECRET' | gcloud secrets versions add $SECRET_CHANNEL_SECRET --data-file=-"

