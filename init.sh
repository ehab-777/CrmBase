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

# Function to check if database is initialized
check_database_initialized() {
    if [ ! -f "/data/crm_multi.db" ]; then
        echo "Database file does not exist"
        return 1
    fi

    # Check if database is valid and has required tables
    if ! sqlite3 "/data/crm_multi.db" "SELECT name FROM sqlite_master WHERE type='table' AND name='tenants';" | grep -q "tenants"; then
        echo "Database exists but tenants table is missing"
        return 1
    fi

    # Check if default tenant exists
    if ! sqlite3 "/data/crm_multi.db" "SELECT COUNT(*) FROM tenants WHERE name='Default Tenant';" | grep -q "1"; then
        echo "Database exists but default tenant is missing"
        return 1
    fi

    # Check if default admin user exists
    if ! sqlite3 "/data/crm_multi.db" "SELECT COUNT(*) FROM sales_team WHERE username='admin';" | grep -q "1"; then
        echo "Database exists but default admin user is missing"
        return 1
    fi

    echo "Database is properly initialized"
    return 0
}

# Initialize database if needed
if ! check_database_initialized; then
    echo "Database needs initialization"
    
    # Remove existing database if it exists but is not properly initialized
    if [ -f "/data/crm_multi.db" ]; then
        echo "Removing existing database file"
        rm -f "/data/crm_multi.db"
    fi

    # Initialize migrations
    echo "Initializing migrations..."
    flask db init || true  # Ignore error if migrations already initialized
    
    # Create initial migration if it doesn't exist
    if [ ! -f "migrations/versions/initial_setup.py" ]; then
        echo "Creating initial migration..."
        flask db migrate -m "initial setup"
    fi
    
    # Run migrations
    echo "Running database migrations..."
    flask db upgrade
    
    # Verify database initialization
    if ! check_database_initialized; then
        echo "Error: Database initialization failed"
        exit 1
    fi
else
    echo "Database is already initialized, running migrations only if needed..."
    flask db upgrade
fi

# Final verification
echo "Performing final database verification..."
if ! check_database_initialized; then
    echo "Error: Final database verification failed"
    exit 1
fi

# Start the application
echo "Starting application..."
exec gunicorn -w 1 -b 0.0.0.0:$PORT app:app 