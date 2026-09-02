#!/bin/bash

echo "🚀 Starting local development setup..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# Install requirements
echo "📥 Installing requirements..."
pip install -r requirements.txt

# Set environment variables
export FLASK_APP=app.py
export FLASK_ENV=development
export FLASK_DEBUG=1
export SECRET_KEY="dev-secret-key"
export SQLALCHEMY_DATABASE_URI="sqlite:///crm_multi.db"
export DATABASE_NAME="crm_multi.db"
export SQLALCHEMY_TRACK_MODIFICATIONS=False

# Extract database path from URI for file operations
DB_PATH="crm_multi.db"

# Remove existing database if it exists
# if [ -f "$DB_PATH" ]; then
#     echo "🗑️ Removing existing database..."
#     rm "$DB_PATH"
# fi

## API Keys for testing
export N8N_API_KEY="test_n8n_key_123"

echo "Initializing database schema using Flask-Migrate via Python scripts if needed..."
python3 database_setup.py

# Verify database was created
if [ ! -f "$DB_PATH" ]; then
    echo "❌ Database initialization failed"
    exit 1
fi

# Run migrations
echo "🔄 Running migrations..."
python3 db_migrations.py

# Find an available port
PORT=5000
while lsof -i :$PORT > /dev/null; do
    echo "Port $PORT is in use, trying next port..."
    PORT=$((PORT + 1))
done

echo "🚀 Starting Flask application on port $PORT..."
flask run --host=0.0.0.0 --port=$PORT 