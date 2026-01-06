###gcs 
service account: user-704@line-trnsltrbt.iam.gserviceaccount.com

# 1. Log in with your personal Google Cloud user account (once)
gcloud auth login

# 2. Set ADC to impersonate the target service account (no key needed)
# For application code (ADC) - ideal for local testing of Cloud Translation/GCS 
gcloud auth application-default login --impersonate-service-account=user-704@line-trnsltrbt.iam.gserviceaccount.com

# Or for gcloud CLI commands
gcloud config set auth/impersonate_service_account your-sa@your-project.iam.gserviceaccount.com

### poetry 
$ poetry env use 3.13

$ poetry install --no-root

poetry shell activate:
$ eval $(poetry env activate)

poetry shell exit
$ deactivate

### ngrok
Default port is `8080`. Use Ngrok (`ngrok http 8080`) to expose the webhook for Line validation.

### GCS deployment
# update your Application Default Credentials quota project
gcloud auth application-default set-quota-project line-trnsltrbt

Create Artifact Registry repo once: 
gcloud artifacts repositories create line-trnsltrbt --repository-format=docker --location=asia-east1

Build/deploy: 
gcloud builds submit --config cloudbuild.yaml --substitutions _REGION=asia-east1,_SERVICE=line-translator-bot,_TAG=$(date +%Y%m%d-%H%M)

Set Cloud Run env/secret bindings for LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET; ensure the service account has Translation API + Secret Manager access.
Local test: docker build -t line_trnsltrbt:dev . then docker run -p 8080:8080 --env-file .env line_trnsltrbt:dev.

### Docker (local)
$ docker build -t line_trnsltrbt:v0.1 .
$ docker run -p 8080:8080 --env-file .env \
    -v $(pwd)/gcp-key.json:/app/gcp-key.json \
    -e GOOGLE_APPLICATION_CREDENTIALS=/app/gcp-key.json \
    flask-messenger-webhook:v0.1


### launchd (macOS native daemon)
# Run the setup script (it will configure paths automatically)
./daemon_setup.sh

# Start the daemon
launchctl load ~/Library/LaunchAgents/com.line.translator.bot.plist

# Check if it's running
launchctl list | grep com.line.translator.bot

# View logs
tail -f logs/stdout.log
tail -f logs/stderr.log

# Stop the daemon
launchctl unload ~/Library/LaunchAgents/com.line.translator.bot.plist

channel id: 2008732694
channel secret: 370fbf5e5e8e6ed3f46c77584de9acc1

key=AIzaSyCKN9m1kSmciHm3QPaRrQz4t90LVIh3ox4

Usage
Simple deployment:
./deploy_gcs.sh
With custom values (via environment variables):
GCP_PROJECT_ID=your-project \SERVICE_NAME=my-bot \./deploy_gcs.sh
Manual deployment (if you prefer):
gcloud builds submit --config cloudbuild.yaml
The script will:
Check prerequisites (gcloud CLI, authentication)
Enable required APIs
Create Artifact Registry repo if needed
Create/update secrets from your .env file
Grant IAM permissions
Build and deploy to Cloud Run
The Cloud Run service will be publicly accessible (for LINE webhook) and configured with secrets from Secret Manager.
