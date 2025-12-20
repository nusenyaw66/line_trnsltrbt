#!/bin/bash
# Local deployment script for LINE Translator Bot

set -e

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Warning: .env file not found. Creating from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "Please edit .env file with your credentials before running."
        exit 1
    else
        echo "Error: .env.example not found. Please create .env file manually."
        exit 1
    fi
fi

# Load environment variables from .env file
# Export variables from .env (this works if .env uses KEY=value format)
if [ -f .env ]; then
    set -a  # automatically export all variables
    # Source .env, but handle errors gracefully
    # This works if .env uses shell-compatible format
    source .env 2>/dev/null || {
        # Fallback: parse line by line if source fails
        while IFS= read -r line || [ -n "$line" ]; do
            # Skip comments and empty lines
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$line" ]] && continue
            # Export the line if it contains =
            [[ "$line" =~ = ]] && export "$line"
        done < .env
    }
    set +a  # stop automatically exporting
fi

# Check Google Cloud credentials
if [ -z "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo "Note: GOOGLE_APPLICATION_CREDENTIALS not set in .env or environment."
    echo "Using Application Default Credentials (ADC)."
    echo "If you get impersonation errors, set GOOGLE_APPLICATION_CREDENTIALS in .env file."
    echo ""
else
    if [ ! -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
        echo "Warning: GOOGLE_APPLICATION_CREDENTIALS points to non-existent file: $GOOGLE_APPLICATION_CREDENTIALS"
        echo ""
    else
        echo "Using Google Cloud credentials from: $GOOGLE_APPLICATION_CREDENTIALS"
        echo ""
    fi
fi

# Activate poetry environment and run the bot
echo "Starting LINE Translator Bot on port ${PORT:-8080}..."
poetry run python line_translator_bot.py

