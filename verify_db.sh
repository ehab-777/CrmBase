#!/bin/bash

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

echo "🔍 Checking database status on Render..."

# Check service status
echo "📊 Checking service status..."
SERVICE_STATUS=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    "https://api.render.com/v1/services/$SERVICE_ID")

if [ $? -ne 0 ]; then
    echo "❌ Failed to get service status"
    exit 1
fi

# Extract service state
STATE=$(echo "$SERVICE_STATUS" | grep -o '"state":"[^"]*"' | cut -d'"' -f4)
echo "Service state: $STATE"

# Check database configuration
echo "📊 Checking database configuration..."
DB_CONFIG=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    "https://api.render.com/v1/services/$SERVICE_ID/env-vars" | grep -i "database")

if [ -z "$DB_CONFIG" ]; then
    echo "⚠️ Warning: No database configuration found"
else
    echo "✅ Database configuration found"
fi

# Check recent logs for database-related messages
echo "📋 Checking recent logs..."
LOGS=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    "https://api.render.com/v1/services/$SERVICE_ID/logs" | grep -i "database\|sqlite\|error")

if [ -z "$LOGS" ]; then
    echo "✅ No database-related errors found in recent logs"
else
    echo "⚠️ Found database-related messages in logs:"
    echo "$LOGS"
fi

echo "✅ Verification completed!"
echo "To fully verify the database is working:"
echo "1. Try logging into your application"
echo "2. Check if you can access the data"
echo "3. Monitor the application logs for any database errors" 