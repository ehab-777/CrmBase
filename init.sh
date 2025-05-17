#!/bin/bash

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export FLASK_APP=app.py
export FLASK_ENV=production
export DATABASE_URL=sqlite:////data/crm_multi.db

# Run database migrations
flask db upgrade

# Start the application
exec gunicorn -w 1 -b 0.0.0.0:$PORT app:app 