#!/bin/bash

echo "✅ init.sh started"

echo "🔄 Starting initialization script..."

# Set default FLASK_ENV if not set
FLASK_ENV=${FLASK_ENV:-development}
echo "🌍 FLASK_ENV is set to: $FLASK_ENV"

# Set default database path
DB_PATH=${DATABASE_NAME:-/data/crm_multi.db}
echo "📁 Database path: $DB_PATH"

# Create data directory if it doesn't exist
mkdir -p /data

# Create migrations directory if it doesn't exist
mkdir -p migrations

# Set environment variables
export FLASK_APP=app.py
export SQLALCHEMY_DATABASE_URI="sqlite:///$DB_PATH"

# Check if database exists and is not empty in the persistent disk
if [ -f "$DB_PATH" ] && [ -s "$DB_PATH" ]; then
    echo "✅ Database already exists in persistent disk. Skipping initialization."
else
    echo "⚠️ No database found in persistent disk. Initializing..."
    flask db init || true
    flask db migrate -m "Initial migration" || true
    flask db upgrade || true
    python database_setup.py
fi

echo "🚀 Launching the application..."
exec gunicorn -w 1 -b 0.0.0.0:$PORT app:app 