#!/bin/bash
# Deployment script for Telegram Translator Bot to Google Cloud Run
# This script handles setup and deployment in one go

set -e

# Flag for API, Service Account, Secrets update - false to skip update
gcs_update=true

# Load .env file first (for TELEGRAM_* variables, APP_VERSION, etc.)
if [ -f .env ]; then
    set -a
    source .env 2>/dev/null || {
        while IFS= read -r line || [ -n "$line" ]; do
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$line" ]] && continue
            [[ "$line" =~ = ]] && export "$line"
        done < .env
    }
    set +a
fi

# Configuration (override with env vars; TELEGRAM_* from .env)
# .env: TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET (required for secrets)
# Optional in .env: TELEGRAM_PROJECT_ID, TELEGRAM_REGION, TELEGRAM_SERVICE_NAME, etc.
PROJECT_ID="${GCP_PROJECT_ID:-${TELEGRAM_PROJECT_ID:-line-trnsltrbt}}"
REGION="${GCP_REGION:-${TELEGRAM_REGION:-us-central1}}"
SERVICE_NAME="${SERVICE_NAME:-${TELEGRAM_SERVICE_NAME:-telegram-translator-bot}}"
REPOSITORY_NAME="line-trnsltrbt"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-${TELEGRAM_SERVICE_ACCOUNT:-user-704@line-trnsltrbt.iam.gserviceaccount.com}}"
SECRET_BOT_TOKEN="${SECRET_BOT_TOKEN:-${TELEGRAM_SECRET_BOT_TOKEN:-telegram-bot-token}}"
SECRET_WEBHOOK_SECRET="${SECRET_WEBHOOK_SECRET:-telegram-webhook-secret}"
SECRET_XAI_API_KEY="${SECRET_XAI_API_KEY:-xai-api-key}"
SECRET_GEMINI_API_KEY="${SECRET_GEMINI_API_KEY:-gemini-api-key}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Telegram Translator Bot - GCS Deployment ===${NC}"
echo "App Version: $APP_VERSION"
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

if [ "$gcs_update" = true ]; then
    # Set project
    echo -e "${GREEN}Setting GCP project to $PROJECT_ID...${NC}"
    gcloud config set project "$PROJECT_ID"

    # Set application-default quota project
    echo -e "${GREEN}Setting application-default quota project to $PROJECT_ID...${NC}"
    gcloud auth application-default set-quota-project "$PROJECT_ID" 2>/dev/null || true

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

    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
        --role="roles/speech.client" \
        2>/dev/null || true

    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
        --role="roles/cloudtts.user" \
        2>/dev/null || true

    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
        --role="roles/storage.admin" \
        2>/dev/null || true

    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
        --role="roles/cloudtranslate.user" \
        2>/dev/null || true

    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
        --role="roles/datastore.user" \
        2>/dev/null || true

    # Cloud Build service account permissions
    echo -e "${GREEN}Checking Cloud Build service account permissions...${NC}"
    CLOUDBUILD_SA="${SERVICE_ACCOUNT}"
    CLOUDBUILD_SA_FULL="projects/${PROJECT_ID}/serviceAccounts/${CLOUDBUILD_SA}"

    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${CLOUDBUILD_SA}" \
        --role="roles/artifactregistry.writer" \
        2>/dev/null || true

    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${CLOUDBUILD_SA}" \
        --role="roles/run.admin" \
        2>/dev/null || true

    gcloud iam service-accounts add-iam-policy-binding "${SERVICE_ACCOUNT_EMAIL}" \
        --member="serviceAccount:${CLOUDBUILD_SA}" \
        --role="roles/iam.serviceAccountUser" \
        --project="$PROJECT_ID" \
        2>/dev/null || true

    # Handle secrets
    if [ -f .env ]; then
        echo -e "${GREEN}Setting up secrets from .env file...${NC}"
        set -a
        source .env 2>/dev/null || {
            while IFS= read -r line || [ -n "$line" ]; do
                [[ "$line" =~ ^[[:space:]]*# ]] && continue
                [[ -z "$line" ]] && continue
                [[ "$line" =~ = ]] && export "$line"
            done < .env
        }
        set +a

        # TELEGRAM_BOT_TOKEN from .env
        if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
            if gcloud secrets describe "$SECRET_BOT_TOKEN" --project="$PROJECT_ID" &>/dev/null; then
                echo -e "${GREEN}Updating secret: $SECRET_BOT_TOKEN${NC}"
                echo -n "$TELEGRAM_BOT_TOKEN" | gcloud secrets versions add "$SECRET_BOT_TOKEN" --data-file=- --project="$PROJECT_ID"
            else
                echo -e "${GREEN}Creating secret: $SECRET_BOT_TOKEN${NC}"
                echo -n "$TELEGRAM_BOT_TOKEN" | gcloud secrets create "$SECRET_BOT_TOKEN" --data-file=- --project="$PROJECT_ID"
            fi
        fi

        # TELEGRAM_WEBHOOK_SECRET from .env (optional - for webhook verification)
        if [ -n "$TELEGRAM_WEBHOOK_SECRET" ]; then
            if gcloud secrets describe "$SECRET_WEBHOOK_SECRET" --project="$PROJECT_ID" &>/dev/null; then
                echo -e "${GREEN}Updating secret: $SECRET_WEBHOOK_SECRET${NC}"
                echo -n "$TELEGRAM_WEBHOOK_SECRET" | gcloud secrets versions add "$SECRET_WEBHOOK_SECRET" --data-file=- --project="$PROJECT_ID"
            else
                echo -e "${GREEN}Creating secret: $SECRET_WEBHOOK_SECRET${NC}"
                echo -n "$TELEGRAM_WEBHOOK_SECRET" | gcloud secrets create "$SECRET_WEBHOOK_SECRET" --data-file=- --project="$PROJECT_ID"
            fi
        fi

        # GEMINI_API_KEY for Live Translate (direct Gemini API, not REST proxy)
        if [ -n "$GEMINI_API_KEY" ]; then
            if gcloud secrets describe "$SECRET_GEMINI_API_KEY" --project="$PROJECT_ID" &>/dev/null; then
                echo -e "${GREEN}Updating secret: $SECRET_GEMINI_API_KEY${NC}"
                echo -n "$GEMINI_API_KEY" | gcloud secrets versions add "$SECRET_GEMINI_API_KEY" --data-file=- --project="$PROJECT_ID"
            else
                echo -e "${GREEN}Creating secret: $SECRET_GEMINI_API_KEY${NC}"
                echo -n "$GEMINI_API_KEY" | gcloud secrets create "$SECRET_GEMINI_API_KEY" --data-file=- --project="$PROJECT_ID"
            fi
        fi

        # XAI_API_KEY from .env (Grok TTS speak hop / Live Translate fallback)
        if [ -n "$XAI_API_KEY" ]; then
            if gcloud secrets describe "$SECRET_XAI_API_KEY" --project="$PROJECT_ID" &>/dev/null; then
                echo -e "${GREEN}Updating secret: $SECRET_XAI_API_KEY${NC}"
                echo -n "$XAI_API_KEY" | gcloud secrets versions add "$SECRET_XAI_API_KEY" --data-file=- --project="$PROJECT_ID"
            else
                echo -e "${GREEN}Creating secret: $SECRET_XAI_API_KEY${NC}"
                echo -n "$XAI_API_KEY" | gcloud secrets create "$SECRET_XAI_API_KEY" --data-file=- --project="$PROJECT_ID"
            fi
        fi

        # Grant service account access to secrets
        for secret in "$SECRET_BOT_TOKEN" "$SECRET_WEBHOOK_SECRET" "$SECRET_XAI_API_KEY" "$SECRET_GEMINI_API_KEY"; do
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
    echo -e "${YELLOW}Skipping API, Service Account, Secrets update (set gcs_update=true to update)${NC}"
    # Still set project and quota project even if skipping updates
    echo -e "${GREEN}Setting GCP project to $PROJECT_ID...${NC}"
    gcloud config set project "$PROJECT_ID"
    echo -e "${GREEN}Setting application-default quota project to $PROJECT_ID...${NC}"
    gcloud auth application-default set-quota-project "$PROJECT_ID" 2>/dev/null || true
fi

# Verify required secret exists before deployment
echo -e "${GREEN}Verifying secrets exist...${NC}"
if ! gcloud secrets describe "$SECRET_BOT_TOKEN" --project="$PROJECT_ID" &>/dev/null; then
    echo -e "${RED}ERROR: Secret '$SECRET_BOT_TOKEN' does not exist in Secret Manager!${NC}"
    echo "Please create the secret or set secret_update=true and provide TELEGRAM_BOT_TOKEN in .env"
    exit 1
fi
echo -e "${GREEN}All required secrets exist.${NC}"

# Build and deploy
echo -e "${GREEN}Building and deploying to Cloud Run...${NC}"
TAG="${APP_VERSION:-unknown}"
CLOUDBUILD_SA="${SERVICE_ACCOUNT}"
CLOUDBUILD_SA_FULL="projects/${PROJECT_ID}/serviceAccounts/${CLOUDBUILD_SA}"

# Pass webhook secret name if it exists (TELEGRAM_WEBHOOK_SECRET from .env)
WEBHOOK_SECRET_ARG=""
if gcloud secrets describe "$SECRET_WEBHOOK_SECRET" --project="$PROJECT_ID" &>/dev/null; then
    WEBHOOK_SECRET_ARG="_TELEGRAM_WEBHOOK_SECRET_NAME=$SECRET_WEBHOOK_SECRET"
fi

XAI_SECRET_ARG=""
if gcloud secrets describe "$SECRET_XAI_API_KEY" --project="$PROJECT_ID" &>/dev/null; then
    XAI_SECRET_ARG="_XAI_API_KEY_SECRET=$SECRET_XAI_API_KEY"
fi

GEMINI_SECRET_ARG=""
if gcloud secrets describe "$SECRET_GEMINI_API_KEY" --project="$PROJECT_ID" &>/dev/null; then
    GEMINI_SECRET_ARG="_GEMINI_API_KEY_SECRET=$SECRET_GEMINI_API_KEY"
fi

STARS_ARG="_TELEGRAM_VOICE_SUB_STARS=${TELEGRAM_VOICE_SUB_STARS:-0}"
LIVE_TRANSLATE_ARG="_GEMINI_LIVE_TRANSLATE=${GEMINI_LIVE_TRANSLATE:-0}"

echo -e "${GREEN}Submitting Cloud Build with service account: ${CLOUDBUILD_SA}${NC}"
SUBSTITUTIONS="_REGION=$REGION,_SERVICE=$SERVICE_NAME,_TAG=$TAG,_SERVICE_ACCOUNT=$SERVICE_ACCOUNT,_APP_VERSION=${APP_VERSION:-unknown},_TELEGRAM_BOT_TOKEN_SECRET=$SECRET_BOT_TOKEN,$STARS_ARG"
if [ -n "$WEBHOOK_SECRET_ARG" ]; then
    SUBSTITUTIONS="${SUBSTITUTIONS},${WEBHOOK_SECRET_ARG}"
fi
if [ -n "$XAI_SECRET_ARG" ]; then
    SUBSTITUTIONS="${SUBSTITUTIONS},${XAI_SECRET_ARG}"
fi
if [ -n "$GEMINI_SECRET_ARG" ]; then
    SUBSTITUTIONS="${SUBSTITUTIONS},${GEMINI_SECRET_ARG}"
fi
SUBSTITUTIONS="${SUBSTITUTIONS},${LIVE_TRANSLATE_ARG}"
gcloud builds submit \
    --config=cloudbuild-telegram.yaml \
    --service-account="${CLOUDBUILD_SA_FULL}" \
    --substitutions="$SUBSTITUTIONS" \
    --project="$PROJECT_ID"

echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo "Service URL:"
gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(status.url)"

echo ""
echo -e "${GREEN}After deployment, set your Telegram webhook:${NC}"
if [ -n "$TELEGRAM_WEBHOOK_SECRET" ]; then
    echo "  https://api.telegram.org/bot<TOKEN>/setWebhook?url=<SERVICE_URL>/webhook&secret_token=<TELEGRAM_WEBHOOK_SECRET>"
else
    echo "  https://api.telegram.org/bot<TOKEN>/setWebhook?url=<SERVICE_URL>/webhook"
fi
echo ""
echo -e "${GREEN}To update secrets, set secret_update=true and run again.${NC}"
