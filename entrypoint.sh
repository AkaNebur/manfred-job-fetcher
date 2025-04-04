#!/bin/bash
# This script ensures the data directory structure exists 
# and tries to fetch the latest BUILD_ID_HASH on startup

# Create a lock file to prevent multiple runs
LOCK_FILE="/tmp/update-build-hash.lock"

if [ -f "$LOCK_FILE" ]; then
    # Check if the lock file is stale (older than 5 minutes)
    if test `find "$LOCK_FILE" -mmin -5`; then
        echo "Another instance is already running. Exiting."
        exit 1
    else
        echo "Removing stale lock file."
        rm -f "$LOCK_FILE"
    fi
fi

# Create the lock file
touch "$LOCK_FILE"

# Ensure cleanup on exit
trap "rm -f $LOCK_FILE; exit" INT TERM EXIT

# Ensure data and config directories exist
mkdir -p ./data/config

# Check if build_hash.json exists - we won't modify it here
# as the application will handle fetching and updating the hash
JSON_FILE="./data/config/build_hash.json"
if [ -f "$JSON_FILE" ]; then
    echo "Found existing build_hash.json file. The application will validate and update if needed."
    # Display current hash for logging purposes only
    JSON_CURRENT_HASH=$(grep -o '"BUILD_ID_HASH": "[^"]*"' "$JSON_FILE" | cut -d'"' -f4)
    echo "Current BUILD_ID_HASH in JSON file: $JSON_CURRENT_HASH"
else
    echo "No build_hash.json file found. Creating an empty placeholder."
    # Create an empty JSON structure that the application will update
    echo '{"BUILD_ID_HASH": ""}' > "$JSON_FILE"
    echo "The application will fetch the current hash on startup."
fi

# Remove the lock file
rm -f "$LOCK_FILE"

echo "Starting FastAPI application..."
exec python -m uvicorn app:app --host 0.0.0.0 --port 5000