#!/bin/bash

echo "✅ init.sh started"

echo "🔄 Starting initialization script..."

# Set default FLASK_ENV if not set
FLASK_ENV=${FLASK_ENV:-development}
echo "🌍 FLASK_ENV is set to: $FLASK_ENV"

# If we're not in development, skip DB initialization
if [ "$FLASK_ENV" != "development" ]; then
  echo "✅ Skipping DB init in $FLASK_ENV environment"
  exec gunicorn -w 1 -b 0.0.0.0:$PORT app:app
  exit 0
fi

echo "⚠️ Running DB init in development mode..."

# Default path for database
DB_PATH=${DATABASE_NAME:-/data/crm_multi.db}
echo "📁 Database path: $DB_PATH"

# Create data directory if not exists
mkdir -p "$(dirname "$DB_PATH")"

# Check if DB file exists and not empty
if [ -s "$DB_PATH" ]; then
  echo "✅ Existing database found. Skipping initialization."
else
  echo "⚠️ Database missing or empty. Running full initialization..."
  flask db init || true
  flask db migrate -m "Initial migration" || true
  flask db upgrade
  python database_setup.py
fi

echo "🚀 Launching the application..."
exec gunicorn -w 1 -b 0.0.0.0:$PORT app:app 