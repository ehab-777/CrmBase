#!/bin/bash

# Install dependencies
pip install -r requirements.txt

# Create data directory if it doesn't exist and set permissions
mkdir -p /data
chmod 777 /data

# Set environment variables
export FLASK_APP=app.py
export FLASK_ENV=staging
export DATABASE_URL=sqlite:////data/crm_multi.db

# Run database migrations
echo "Running database migrations..."
flask db upgrade

# Verify database exists
if [ -f "/data/crm_multi.db" ]; then
    echo "Database file created successfully"
    ls -l /data/crm_multi.db
else
    echo "Error: Database file was not created"
    exit 1
fi

# Start the application
echo "Starting application..."
exec gunicorn -w 1 -b 0.0.0.0:$PORT app:app 