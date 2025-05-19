import os
from flask import Flask
from flask_migrate import Migrate, current
from models import db, Tenant, SalesPerson
from werkzeug.security import generate_password_hash
from datetime import datetime
import sqlite3
import sys

def log_message(message):
    """Log message to both stdout and stderr."""
    print(message, file=sys.stderr)
    print(message)

def get_db_path():
    """Get the database path from environment variables."""
    db_path = os.getenv('DATABASE_NAME', '/data/crm_multi.db')
    log_message(f"Database path: {db_path}")
    return db_path

def verify_tables_exist():
    """Verify that all required tables exist in the database."""
    try:
        db_path = get_db_path()
        if not os.path.exists(db_path):
            log_message(f"Database file does not exist at {db_path}")
            return False

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
        tables = [table[0] for table in cursor.fetchall()]
        conn.close()

        required_tables = ['tenants', 'sales_team', 'customers', 'sales_followup']
        missing_tables = [table for table in required_tables if table not in tables]
        
        if missing_tables:
            log_message(f"Missing tables: {missing_tables}")
            return False
        
        log_message(f"All required tables exist: {tables}")
        return True
    except Exception as e:
        log_message(f"Error verifying tables: {str(e)}")
        return False

def init_db(app):
    """Initialize the database with required tables and default data."""
    try:
        with app.app_context():
            db_path = get_db_path()
            log_message(f"Starting database initialization... Database exists: {os.path.exists(db_path)}")
            
            # Check if database file exists and has content
            if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
                log_message("Database file exists and has content")
                if verify_tables_exist():
                    log_message("All required tables exist, skipping initialization")
                    return True
                else:
                    log_message("Database file exists but tables are missing")
            
            # Ensure migrations are up to date
            try:
                current_revision = current()
                log_message(f"Current migration revision: {current_revision}")
            except Exception as e:
                log_message(f"Error checking migration status: {str(e)}")
                return False
            
            # Create default tenant
            log_message("Checking for default tenant...")
            default_tenant = Tenant.query.filter_by(name='Default Tenant').first()
            if not default_tenant:
                log_message("Creating default tenant...")
                default_tenant = Tenant(
                    name='Default Tenant',
                    db_key='default',
                    created_at=datetime.utcnow()
                )
                db.session.add(default_tenant)
                db.session.commit()
                log_message("Default tenant created successfully")
            else:
                log_message("Default tenant already exists")

            # Create admin user
            log_message("Checking for admin user...")
            admin_user = SalesPerson.query.filter_by(username='admin').first()
            if not admin_user:
                log_message("Creating admin user...")
                admin_user = SalesPerson(
                    username='admin',
                    first_name='Admin',
                    last_name='User',
                    password=generate_password_hash('admin123'),
                    salesperson_name='admin',
                    work_email='admin@example.com',
                    role='admin',
                    tenant_id=default_tenant.id,
                    created_at=datetime.utcnow()
                )
                db.session.add(admin_user)
                db.session.commit()
                log_message("Admin user created successfully")
            else:
                log_message("Admin user already exists")

            # Verify the setup
            if verify_db_setup(app):
                log_message("Database initialization completed successfully")
                return True
            else:
                log_message("Database initialization failed verification")
                return False

    except Exception as e:
        log_message(f"Error during database initialization: {str(e)}")
        return False

def verify_db_setup(app):
    """Verify that the database is properly set up."""
    try:
        with app.app_context():
            db_path = get_db_path()
            log_message(f"Verifying database setup... Database exists: {os.path.exists(db_path)}")
            
            # Check if database file exists and has content
            if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
                log_message("Database file does not exist or is empty")
                return False
            
            # Verify tables exist
            if not verify_tables_exist():
                return False

            # Check if default tenant exists
            default_tenant = Tenant.query.filter_by(name='Default Tenant').first()
            if not default_tenant:
                log_message("Default tenant is missing")
                return False
            log_message("Default tenant exists")

            # Check if admin user exists
            admin_user = SalesPerson.query.filter_by(username='admin').first()
            if not admin_user:
                log_message("Admin user is missing")
                return False
            log_message("Admin user exists")

            log_message("Database verification completed successfully")
            return True

    except Exception as e:
        log_message(f"Error during database verification: {str(e)}")
        return False

def force_init_db(app):
    """Force reinitialize the database by dropping all tables and recreating them."""
    try:
        with app.app_context():
            db_path = get_db_path()
            log_message(f"Force initializing database... Database exists: {os.path.exists(db_path)}")
            
            # Drop all tables
            db.drop_all()
            log_message("Dropped all tables")
            
            # Run migrations
            from flask_migrate import upgrade
            upgrade()
            log_message("Ran migrations")
            
            # Initialize database
            return init_db(app)
            
    except Exception as e:
        log_message(f"Error during force initialization: {str(e)}")
        return False

if __name__ == '__main__':
    # This allows running the script directly for testing
    from app import app
    if init_db(app):
        log_message("Database setup completed successfully")
    else:
        log_message("Database setup failed, attempting force initialization...")
        if force_init_db(app):
            log_message("Force initialization completed successfully")
        else:
            log_message("Force initialization failed") 