#!/bin/bash

# Exit on error
set -e

# Print commands
set -x

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create data directory if it doesn't exist and set permissions
echo "Creating data directory..."
mkdir -p /data
chmod 777 /data

# Verify data directory exists and is writable
if [ ! -d "/data" ]; then
    echo "Error: Failed to create /data directory"
    exit 1
fi

if [ ! -w "/data" ]; then
    echo "Error: /data directory is not writable"
    exit 1
fi

# Set environment variables
export FLASK_APP=app.py
export FLASK_ENV=staging
export DATABASE_URL=sqlite:////data/crm_multi.db
export DATABASE_NAME=/data/crm_multi.db
export SQLALCHEMY_DATABASE_URI=sqlite:////data/crm_multi.db

# Print environment variables for debugging
echo "Environment variables:"
echo "FLASK_ENV: $FLASK_ENV"
echo "DATABASE_URL: $DATABASE_URL"
echo "DATABASE_NAME: $DATABASE_NAME"
echo "SQLALCHEMY_DATABASE_URI: $SQLALCHEMY_DATABASE_URI"

# Check if database file exists
if [ -f "/data/crm_multi.db" ]; then
    echo "Database file exists at /data/crm_multi.db"
    ls -l /data/crm_multi.db
else
    echo "Database file does not exist at /data/crm_multi.db"
fi

# Initialize database
echo "Initializing database..."
python3 -c "
from app import app
from database_setup import init_db, verify_db_setup, force_init_db
import os

# Print current working directory and database path
print(f'Current working directory: {os.getcwd()}')
print(f'Database path: {os.getenv(\"DATABASE_NAME\")}')

# First try normal initialization
if not verify_db_setup(app):
    print('Database needs initialization')
    if init_db(app):
        print('Database initialized successfully')
    else:
        print('Normal initialization failed, attempting force initialization...')
        if force_init_db(app):
            print('Force initialization completed successfully')
        else:
            print('Force initialization failed')
            exit(1)
else:
    print('Database is already initialized')
"

# Verify database file after initialization
if [ -f "/data/crm_multi.db" ]; then
    echo "Database file exists after initialization"
    ls -l /data/crm_multi.db
else
    echo "Error: Database file was not created"
    exit 1
fi

# Start the application
echo "Starting application..."
exec gunicorn -w 1 -b 0.0.0.0:$PORT app:app 