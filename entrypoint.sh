#!/bin/bash
set -e

# Environment variables from .env will already be loaded
DB_PATH=${DB_PATH:-"/app/data/history.db"}
RESET_DB=${RESET_DB:-"false"}

# Check if database reset is requested
if [ "$RESET_DB" = "true" ]; then
    echo "Database reset requested (RESET_DB=true)"
    
    # Remove the database file if it exists
    if [ -f "$DB_PATH" ]; then
        echo "Removing existing database at $DB_PATH"
        rm "$DB_PATH"
        echo "Database reset successfully"
    else
        echo "No existing database found at $DB_PATH"
    fi

    # Also remove any journal files that might exist
    if [ -f "${DB_PATH}-journal" ]; then
        echo "Removing existing journal file at ${DB_PATH}-journal"
        rm "${DB_PATH}-journal"
    fi
else
    echo "Database reset not requested (RESET_DB=false)"
fi

# Start the application
echo "Starting application..."
exec python app.py