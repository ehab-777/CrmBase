#!/bin/bash

echo "✅ init.sh started"

FLASK_ENV=${FLASK_ENV:-development}
echo "🌍 FLASK_ENV: $FLASK_ENV"

DB_PATH=${DATABASE_NAME:-/data/crm_multi.db}
echo "📁 DB path: $DB_PATH"

# Always ensure the data directory exists
mkdir -p "$(dirname "$DB_PATH")"

# Initialize DB if it doesn't exist (any environment)
if [ ! -s "$DB_PATH" ]; then
    echo "⚠️  DB missing — running first-time setup..."
    python setup_production_db.py
    echo "✅ DB setup complete"
else
    echo "✅ DB exists, skipping init"
fi

echo "🚀 Starting gunicorn on port ${PORT:-8000}..."
exec gunicorn -w 1 -b 0.0.0.0:${PORT:-8000} app:app
