#!/bin/bash

# Cards Memex Bot Startup Sequence
# Creates backups, refreshes memory, and starts the bot with logging

set -e  # Exit on error

# Change to script directory
cd "$(dirname "$0")"

echo "🧠 Cards Memex Bot Startup Sequence"
echo ""

# Get timestamp for backup folder name (format: backup_YYYY-MM-DD_HHMM)
TIMESTAMP=$(date +"%Y-%m-%d_%H%M")
BACKUP_DIR="backups/backup_${TIMESTAMP}"

# Create backups directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "📦 Creating backup..."

# Backup knowledge_base folder
if [ -d "data/knowledge_base" ]; then
    cp -r data/knowledge_base "$BACKUP_DIR/"
    echo "   ✅ Backed up data/knowledge_base"
else
    echo "   ⚠️  data/knowledge_base folder not found, skipping..."
fi

# Backup watched_threads.json
if [ -f "data/watched_threads.json" ]; then
    cp data/watched_threads.json "$BACKUP_DIR/"
    echo "   ✅ Backed up watched_threads.json"
else
    echo "   ⚠️  data/watched_threads.json not found, skipping..."
fi

# Backup feedback_log.jsonl if it exists
if [ -f "data/feedback_log.jsonl" ]; then
    cp data/feedback_log.jsonl "$BACKUP_DIR/"
    echo "   ✅ Backed up feedback_log.jsonl"
fi

echo "✅ Backup created: $BACKUP_DIR"
echo ""

# 1. Run Catch Up (Refresh Memory)
echo "🔄 Running Catch Up..."
python3 catchup.py

echo ""
echo "---"
echo ""

# 2. Start the Bot with Logging
# Use -u flag for unbuffered output so logs appear immediately
python3 -u main.py | tee bot.log

