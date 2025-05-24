#!/bin/bash

echo "✅ init.sh started"
echo "🔄 Starting initialization script..."

# Ensure FLASK_ENV is set
FLASK_ENV=${FLASK_ENV:-development}
echo "🌍 FLASK_ENV is set to: $FLASK_ENV"

# If not development, skip all DB init and run app
if [ "$FLASK_ENV" != "development" ]; then
    echo "✅ Skipping DB init in $FLASK_ENV environment"
    exec gunicorn -w 1 -b 0.0.0.0:$PORT app:app
    exit 0
fi

# In development, continue with DB checks
echo "🧪 Running DB checks in development..."

DB_PATH=${DATABASE_NAME:-crm_multi.db}
mkdir -p "$(dirname "$DB_PATH")"
echo "📁 Checking DB at: $DB_PATH"

# If DB exists and is not empty
if [ -s "$DB_PATH" ]; then
    echo "✅ Database exists. Skipping re-initialization."
else
    echo "⚠️ DB missing or empty. Running initial setup..."
    flask db init || true
    flask db migrate -m "Initial migration" || true
    flask db upgrade || true
    python database_setup.py
fi

echo "🚀 Launching app..."
exec gunicorn -w 1 -b 0.0.0.0:$PORT app:app 