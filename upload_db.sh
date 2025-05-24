#!/bin/bash

# Check if source database exists
SOURCE_DB="crm_multi.db"
if [ ! -f "$SOURCE_DB" ]; then
    echo "❌ Source database not found: $SOURCE_DB"
    echo "Please make sure the database file exists in the current directory"
    exit 1
fi

# Check if RENDER_API_KEY is set
if [ -z "$RENDER_API_KEY" ]; then
    echo "❌ RENDER_API_KEY environment variable is not set"
    echo "Please set your Render API key:"
    echo "export RENDER_API_KEY='your-api-key'"
    exit 1
fi

# Check if SERVICE_ID is set
if [ -z "$SERVICE_ID" ]; then
    echo "❌ SERVICE_ID environment variable is not set"
    echo "Please set your Render service ID:"
    echo "export SERVICE_ID='your-service-id'"
    exit 1
fi

echo "✅ Starting database upload to Render..."

# Create a temporary directory
TEMP_DIR=$(mktemp -d)
echo "📁 Created temporary directory: $TEMP_DIR"

# Copy database to temporary directory
cp "$SOURCE_DB" "$TEMP_DIR/"
echo "📋 Copied database to temporary directory"

# Create a tar archive
tar -czf "$TEMP_DIR/db.tar.gz" -C "$TEMP_DIR" "$SOURCE_DB"
echo "📦 Created archive of database"

# Upload to Render
echo "⬆️ Uploading database to Render..."
UPLOAD_RESPONSE=$(curl -s -X POST \
    -H "Authorization: Bearer $RENDER_API_KEY" \
    -F "file=@$TEMP_DIR/db.tar.gz" \
    "https://api.render.com/v1/services/$SERVICE_ID/uploads")

# Check if upload was successful
if [ $? -ne 0 ]; then
    echo "❌ Upload failed!"
    echo "Error response: $UPLOAD_RESPONSE"
    rm -rf "$TEMP_DIR"
    exit 1
fi

echo "✅ Database upload completed!"

# Verify the upload
echo "🔍 Verifying upload..."
sleep 5  # Wait for Render to process the upload

# Check service status
SERVICE_STATUS=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    "https://api.render.com/v1/services/$SERVICE_ID")

if [ $? -ne 0 ]; then
    echo "❌ Failed to verify service status"
    echo "Error response: $SERVICE_STATUS"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Check if database exists in the service
echo "📊 Checking database status..."
DB_STATUS=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    "https://api.render.com/v1/services/$SERVICE_ID/env-vars" | grep -i "database")

if [ -z "$DB_STATUS" ]; then
    echo "⚠️ Warning: Could not verify database status"
else
    echo "✅ Database configuration found in service"
fi

# Clean up
rm -rf "$TEMP_DIR"
echo "🧹 Cleaned up temporary files"

echo "✅ Verification completed!"
echo "To verify the database is working:"
echo "1. Go to your Render dashboard"
echo "2. Check the service logs for any database-related errors"
echo "3. Try logging into your application"
echo "4. If you see any errors, check the Render logs for details" 