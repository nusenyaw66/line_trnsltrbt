#!/bin/bash
# Setup script for running LINE translator bot as a macOS daemon

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PLIST_NAME="com.line.translator.bot.plist"
PLIST_PATH="$SCRIPT_DIR/$PLIST_NAME"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LAUNCH_AGENTS_PLIST="$LAUNCH_AGENTS_DIR/$PLIST_NAME"

# Create logs directory
mkdir -p "$SCRIPT_DIR/logs"

# Update plist with correct paths
sed -i '' "s|/Users/wsun/Programming/line_trnsltrchtbt|$SCRIPT_DIR|g" "$PLIST_PATH"

# Find poetry path
POETRY_PATH=$(which poetry)
if [ -z "$POETRY_PATH" ]; then
    echo "ERROR: Poetry not found in PATH"
    echo "Please install Poetry or update the plist file with the correct path"
    exit 1
fi

# Update poetry path in plist
sed -i '' "s|/usr/local/bin/poetry|$POETRY_PATH|g" "$PLIST_PATH"

# Copy plist to LaunchAgents
cp "$PLIST_PATH" "$LAUNCH_AGENTS_PLIST"

echo "✅ LaunchAgent installed at: $LAUNCH_AGENTS_PLIST"
echo ""
echo "To start the daemon:"
echo "  launchctl load $LAUNCH_AGENTS_PLIST"
echo ""
echo "To stop the daemon:"
echo "  launchctl unload $LAUNCH_AGENTS_PLIST"
echo ""
echo "To check status:"
echo "  launchctl list | grep com.line.translator.bot"
echo ""
echo "To view logs:"
echo "  tail -f $SCRIPT_DIR/logs/stdout.log"
echo "  tail -f $SCRIPT_DIR/logs/stderr.log"

