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

# Check if we're in development environment
if [ "$FLASK_ENV" != "development" ]; then
    echo "Skipping DB initialization in non-dev environment"
    echo "Starting application..."
    exec gunicorn -w 1 -b 0.0.0.0:$PORT app:app
    exit 0
fi

# Function to log database status
log_db_status() {
    if [ -f "/data/crm_multi.db" ]; then
        echo "Database file exists at /data/crm_multi.db"
        echo "Database size: $(du -h /data/crm_multi.db | cut -f1)"
        echo "Database permissions: $(ls -l /data/crm_multi.db)"
    else
        echo "Database file does not exist"
    fi
}

# Log initial database status
echo "Initial database status:"
log_db_status

# Check if database exists and has content
if [ -f "/data/crm_multi.db" ] && [ -s "/data/crm_multi.db" ]; then
    echo "Database file exists and has content, verifying structure..."
    
    # Verify database structure
    if sqlite3 /data/crm_multi.db ".tables" > /dev/null 2>&1; then
        echo "Database structure is valid, proceeding..."
        
        # Check for essential tables
        ESSENTIAL_TABLES="tenants sales_team customers sales_followup"
        MISSING_TABLES=0
        
        for table in $ESSENTIAL_TABLES; do
            if ! sqlite3 /data/crm_multi.db "SELECT name FROM sqlite_master WHERE type='table' AND name='$table';" | grep -q "$table"; then
                echo "Missing essential table: $table"
                MISSING_TABLES=1
            fi
        done
        
        if [ $MISSING_TABLES -eq 1 ]; then
            echo "Some essential tables are missing, initializing database..."
            python3 -c "
from app import app
from database_setup import init_db
if init_db(app):
    print('Database initialized successfully')
else:
    print('Database initialization failed')
    exit(1)
"
        else
            echo "All essential tables exist, skipping initialization"
        fi
    else
        echo "Database structure is invalid, restoring from backup..."
        if [ -f "/data/crm_multi.db.backup" ]; then
            cp /data/crm_multi.db.backup /data/crm_multi.db
            chmod 666 /data/crm_multi.db
            echo "Database restored from backup"
        else
            echo "No backup found, initializing database..."
            python3 -c "
from app import app
from database_setup import init_db
if init_db(app):
    print('Database initialized successfully')
else:
    print('Database initialization failed')
    exit(1)
"
        fi
    fi
else
    echo "Database file does not exist or is empty, initializing..."
    # Check for backup first
    if [ -f "/data/crm_multi.db.backup" ]; then
        echo "Restoring from backup..."
        cp /data/crm_multi.db.backup /data/crm_multi.db
        chmod 666 /data/crm_multi.db
        echo "Database restored from backup"
    else
        echo "No backup found, creating new database..."
        python3 -c "
from app import app
from database_setup import init_db
if init_db(app):
    print('Database initialized successfully')
else:
    print('Database initialization failed')
    exit(1)
"
    fi
fi

# Create a backup of the database
if [ -f "/data/crm_multi.db" ]; then
    echo "Creating backup of database..."
    cp /data/crm_multi.db /data/crm_multi.db.backup
    chmod 666 /data/crm_multi.db.backup
    echo "Database backed up successfully"
fi

# Log final database status
echo "Final database status:"
log_db_status

# Start the application
echo "Starting application..."
exec gunicorn -w 1 -b 0.0.0.0:$PORT app:app 