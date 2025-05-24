#!/bin/bash

# Source database path
SOURCE_DB="crm_multi.db"
BACKUP_DIR="database_backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/crm_multi_${TIMESTAMP}.db"

echo "✅ Starting database upload to Git..."

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"
echo "📁 Created backup directory: $BACKUP_DIR"

# Check if source database exists
if [ ! -f "$SOURCE_DB" ]; then
    echo "❌ Source database not found: $SOURCE_DB"
    echo "Please make sure the database file exists in the current directory"
    exit 1
fi

# Create a backup of the database
echo "📋 Creating backup of database..."
cp "$SOURCE_DB" "$BACKUP_FILE"
echo "✅ Backup created: $BACKUP_FILE"

# Add the backup to git
echo "⬆️ Adding database to Git..."
git add "$BACKUP_FILE"

# Commit the changes
echo "💾 Committing changes..."
git commit -m "Add database backup: $TIMESTAMP"

# Push to remote repository
echo "🚀 Pushing to remote repository..."
git push origin main

echo "✅ Database upload completed!"
echo "Backup file: $BACKUP_FILE"
echo "To restore this backup in the future, use:"
echo "cp $BACKUP_FILE crm_multi.db" 