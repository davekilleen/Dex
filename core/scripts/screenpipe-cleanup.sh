#!/bin/bash
# ScreenPipe Auto-Cleanup Script
# Deletes screen capture data older than configured retention period
# Default: 30 days, configurable via ~/.screenpipe/retention_days

SCREENPIPE_DIR="$HOME/.screenpipe"
RETENTION_FILE="$SCREENPIPE_DIR/retention_days"
DEFAULT_DAYS=30

# Read retention days from config, default to 30
if [ -f "$RETENTION_FILE" ]; then
    DAYS=$(cat "$RETENTION_FILE")
else
    DAYS=$DEFAULT_DAYS
fi

# Validate it's a number
if ! [[ "$DAYS" =~ ^[0-9]+$ ]]; then
    DAYS=$DEFAULT_DAYS
fi

echo "ScreenPipe Cleanup - Retention: $DAYS days"

# Delete old video chunks
if [ -d "$SCREENPIPE_DIR/data" ]; then
    OLD_FILES=$(find "$SCREENPIPE_DIR/data" -type f -mtime +$DAYS 2>/dev/null | wc -l)
    if [ "$OLD_FILES" -gt 0 ]; then
        find "$SCREENPIPE_DIR/data" -type f -mtime +$DAYS -delete 2>/dev/null
        echo "Deleted $OLD_FILES old video chunks"
    else
        echo "No old video chunks to delete"
    fi
fi

# For SQLite, we need to delete old records
# This requires sqlite3 to be installed
if command -v sqlite3 &> /dev/null && [ -f "$SCREENPIPE_DIR/db.sqlite" ]; then
    CUTOFF_DATE=$(date -v-${DAYS}d +"%Y-%m-%d" 2>/dev/null || date -d "-$DAYS days" +"%Y-%m-%d")
    
    # Count records to delete
    OLD_RECORDS=$(sqlite3 "$SCREENPIPE_DIR/db.sqlite" \
        "SELECT COUNT(*) FROM ocr_text WHERE timestamp < '$CUTOFF_DATE';" 2>/dev/null || echo "0")
    
    if [ "$OLD_RECORDS" -gt 0 ]; then
        sqlite3 "$SCREENPIPE_DIR/db.sqlite" \
            "DELETE FROM ocr_text WHERE timestamp < '$CUTOFF_DATE';" 2>/dev/null
        sqlite3 "$SCREENPIPE_DIR/db.sqlite" "VACUUM;" 2>/dev/null
        echo "Deleted $OLD_RECORDS old OCR records from database"
    else
        echo "No old database records to delete"
    fi
fi

echo "Cleanup complete"
