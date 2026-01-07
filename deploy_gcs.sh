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

# Read APP_VERSION from .env file (always, not just when updating secrets)
APP_VERSION=""
if [ -f .env ]; then
    # Source .env file to get APP_VERSION
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
    
    # Extract APP_VERSION if it exists
    if [ -n "${APP_VERSION:-}" ]; then
        echo -e "${GREEN}Found APP_VERSION in .env: ${APP_VERSION}${NC}"
    else
        echo -e "${YELLOW}Warning: APP_VERSION not found in .env, using default${NC}"
        APP_VERSION="unknown"
    fi
else
    echo -e "${YELLOW}Warning: .env file not found, APP_VERSION will be 'unknown'${NC}"
    APP_VERSION="unknown"
fi

# Setup secrets if .env file exists
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT}"
if [ "$secret_update" = true ]; then
    if [ -f .env ]; then
        echo -e "${GREEN}Setting up secrets from .env file...${NC}"
        
        # Variables from .env should already be available from above, but ensure they're set
        # (in case secret_update=true but .env wasn't read above)
        if [ -z "${LINE_CHANNEL_ACCESS_TOKEN:-}" ] && [ -z "${LINE_CHANNEL_SECRET:-}" ]; then
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
            if gcloud secrets get-iam-policy "$SECRET_ACCESS_TOKEN" \
                --flatten="bindings[].members" \
                --filter="bindings.members:serviceAccount:${SERVICE_ACCOUNT_EMAIL} AND bindings.role:roles/secretmanager.secretAccessor" \
                --format="value(bindings.role)" \
                --project="$PROJECT_ID" 2>/dev/null | grep -q "^roles/secretmanager.secretAccessor$"; then
                echo -e "${GREEN}Secret access already granted: $SECRET_ACCESS_TOKEN${NC}"
            else
                echo -e "${YELLOW}Granting secret access: $SECRET_ACCESS_TOKEN${NC}"
                gcloud secrets add-iam-policy-binding "$SECRET_ACCESS_TOKEN" \
                    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
                    --role="roles/secretmanager.secretAccessor" \
                    --project="$PROJECT_ID" 2>/dev/null || {
                    echo -e "${RED}Failed to grant secret access: $SECRET_ACCESS_TOKEN${NC}"
                }
            fi
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
            if gcloud secrets get-iam-policy "$SECRET_CHANNEL_SECRET" \
                --flatten="bindings[].members" \
                --filter="bindings.members:serviceAccount:${SERVICE_ACCOUNT_EMAIL} AND bindings.role:roles/secretmanager.secretAccessor" \
                --format="value(bindings.role)" \
                --project="$PROJECT_ID" 2>/dev/null | grep -q "^roles/secretmanager.secretAccessor$"; then
                echo -e "${GREEN}Secret access already granted: $SECRET_CHANNEL_SECRET${NC}"
            else
                echo -e "${YELLOW}Granting secret access: $SECRET_CHANNEL_SECRET${NC}"
                gcloud secrets add-iam-policy-binding "$SECRET_CHANNEL_SECRET" \
                    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
                    --role="roles/secretmanager.secretAccessor" \
                    --project="$PROJECT_ID" 2>/dev/null || {
                    echo -e "${RED}Failed to grant secret access: $SECRET_CHANNEL_SECRET${NC}"
                }
            fi
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

# Helper function to check if a project-level IAM binding already exists
check_and_grant_project_iam() {
    local member="$1"
    local role="$2"
    local description="$3"
    
    # Check if the binding already exists
    if gcloud projects get-iam-policy "$PROJECT_ID" \
        --flatten="bindings[].members" \
        --filter="bindings.members:${member} AND bindings.role:${role}" \
        --format="value(bindings.role)" \
        --project="$PROJECT_ID" 2>/dev/null | grep -q "^${role}$"; then
        echo -e "${GREEN}Permission already granted: ${description}${NC}"
        return 0
    fi
    
    # Grant the permission if it doesn't exist
    echo -e "${YELLOW}Granting permission: ${description}${NC}"
    if gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="${member}" \
        --role="${role}" \
        --project="$PROJECT_ID"; then
        echo -e "${GREEN}Successfully granted permission: ${description}${NC}"
        return 0
    else
        local exit_code=$?
        echo -e "${RED}Failed to grant permission: ${description}${NC}"
        echo -e "${RED}Member: ${member}, Role: ${role}${NC}"
        # Don't fail the script - permission might already exist or there might be a transient issue
        return $exit_code
    fi
}

# Helper function to check if a service account IAM binding already exists
check_and_grant_service_account_iam() {
    local sa_email="$1"
    local member="$2"
    local role="$3"
    local description="$4"
    
    # Check if the binding already exists
    if gcloud iam service-accounts get-iam-policy "$sa_email" \
        --flatten="bindings[].members" \
        --filter="bindings.members:${member} AND bindings.role:${role}" \
        --format="value(bindings.role)" \
        --project="$PROJECT_ID" 2>/dev/null | grep -q "^${role}$"; then
        echo -e "${GREEN}Permission already granted: ${description}${NC}"
        return 0
    fi
    
    # Grant the permission if it doesn't exist
    echo -e "${YELLOW}Granting permission: ${description}${NC}"
    gcloud iam service-accounts add-iam-policy-binding "$sa_email" \
        --member="${member}" \
        --role="${role}" \
        --project="$PROJECT_ID" 2>/dev/null || {
        echo -e "${RED}Failed to grant permission: ${description}${NC}"
        return 1
    }
    return 0
}

# Grant Cloud Build service account necessary permissions
# Using the project service account for Cloud Build operations
CLOUDBUILD_SA="$SERVICE_ACCOUNT"
# Convert email format to full resource name format for gcloud builds submit
CLOUDBUILD_SA_FULL="projects/${PROJECT_ID}/serviceAccounts/${CLOUDBUILD_SA}"

echo -e "${GREEN}Checking Cloud Build service account permissions...${NC}"
echo "Using service account: ${CLOUDBUILD_SA}"

# Allow Cloud Build to write to GCS (for source code storage bucket)
# Cloud Build automatically creates {PROJECT_ID}_cloudbuild bucket
check_and_grant_project_iam \
    "serviceAccount:${CLOUDBUILD_SA}" \
    "roles/storage.admin" \
    "Cloud Build - Storage Admin"

# Allow Cloud Build to push to Artifact Registry
check_and_grant_project_iam \
    "serviceAccount:${CLOUDBUILD_SA}" \
    "roles/artifactregistry.writer" \
    "Cloud Build - Artifact Registry Writer"

# Allow Cloud Build to deploy to Cloud Run
check_and_grant_project_iam \
    "serviceAccount:${CLOUDBUILD_SA}" \
    "roles/run.admin" \
    "Cloud Build - Cloud Run Admin"

# Allow Cloud Build to act as the service account (impersonation for Cloud Run deployment)
# Note: This allows the service account to impersonate itself (may not be needed, but harmless)
check_and_grant_service_account_iam \
    "$SERVICE_ACCOUNT" \
    "serviceAccount:${CLOUDBUILD_SA}" \
    "roles/iam.serviceAccountUser" \
    "Cloud Build - Service Account User"

# Grant Cloud Run service account permissions for Speech-to-Text and Text-to-Speech APIs
echo -e "${GREEN}Checking Cloud Run service account API permissions...${NC}"
echo "Service account: ${SERVICE_ACCOUNT}"

# Allow service account to use Speech-to-Text API
check_and_grant_project_iam \
    "serviceAccount:${SERVICE_ACCOUNT}" \
    "roles/speech.client" \
    "Cloud Run - Speech-to-Text API"

# Generate tag from APP_VERSION (read from .env file)
if [ -n "${APP_VERSION:-}" ] && [ "${APP_VERSION}" != "unknown" ]; then
    # Use APP_VERSION, add 'v' prefix if not already present
    if [[ "$APP_VERSION" =~ ^v ]]; then
        TAG="$APP_VERSION"
    else
        TAG="v${APP_VERSION}"
    fi
else
    # Fallback to timestamp if APP_VERSION is not set or is "unknown"
    echo -e "${YELLOW}Warning: APP_VERSION not available, using timestamp for tag${NC}"
    TAG="v$(date +%Y%m%d-%H%M%S)"
fi

echo -e "${GREEN}Starting Cloud Build deployment...${NC}"
echo -e "${YELLOW}Tag: $TAG${NC}"
echo ""

# Submit build
# Use the service account for Cloud Build operations
echo -e "${GREEN}Submitting Cloud Build with service account: ${CLOUDBUILD_SA}${NC}"
gcloud builds submit \
    --config cloudbuild.yaml \
    --service-account="${CLOUDBUILD_SA_FULL}" \
    --substitutions=_REGION="$REGION",_SERVICE="$SERVICE_NAME",_TAG="$TAG",_LINE_ACCESS_TOKEN_SECRET="$SECRET_ACCESS_TOKEN",_LINE_SECRET_SECRET="$SECRET_CHANNEL_SECRET",_SERVICE_ACCOUNT="$SERVICE_ACCOUNT",_APP_VERSION="$APP_VERSION" \
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

