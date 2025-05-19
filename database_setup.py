import os
from flask import Flask
from flask_migrate import Migrate
from models import db, Tenant, SalesPerson
from werkzeug.security import generate_password_hash
from datetime import datetime

def get_db_path():
    """Get the database path from environment variables."""
    db_path = os.getenv('DATABASE_NAME', '/data/crm_multi.db')
    print(f"Database path: {db_path}")
    return db_path

def init_db(app):
    """Initialize the database with required tables and default data."""
    try:
        with app.app_context():
            db_path = get_db_path()
            print(f"Starting database initialization... Database exists: {os.path.exists(db_path)}")
            
            # Check if database file exists and has content
            if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
                print("Database file exists and has content")
                # Verify tables exist
                tables = db.engine.table_names()
                if 'tenants' in tables:
                    print("Database tables exist, skipping initialization")
                    return True
                else:
                    print("Database file exists but tables are missing")
            
            # Run migrations
            print("Running database migrations...")
            from flask_migrate import upgrade
            upgrade()
            
            # Create default tenant
            print("Checking for default tenant...")
            default_tenant = Tenant.query.filter_by(name='Default Tenant').first()
            if not default_tenant:
                print("Creating default tenant...")
                default_tenant = Tenant(
                    name='Default Tenant',
                    db_key='default',
                    created_at=datetime.utcnow()
                )
                db.session.add(default_tenant)
                db.session.commit()
                print("Default tenant created successfully")
            else:
                print("Default tenant already exists")

            # Create admin user
            print("Checking for admin user...")
            admin_user = SalesPerson.query.filter_by(username='admin').first()
            if not admin_user:
                print("Creating admin user...")
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
                print("Admin user created successfully")
            else:
                print("Admin user already exists")

            # Verify the setup
            if verify_db_setup(app):
                print("Database initialization completed successfully")
                return True
            else:
                print("Database initialization failed verification")
                return False

    except Exception as e:
        print(f"Error during database initialization: {str(e)}")
        return False

def verify_db_setup(app):
    """Verify that the database is properly set up."""
    try:
        with app.app_context():
            db_path = get_db_path()
            print(f"Verifying database setup... Database exists: {os.path.exists(db_path)}")
            
            # Check if database file exists and has content
            if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
                print("Database file does not exist or is empty")
                return False
            
            # Check if tables exist
            tables = db.engine.table_names()
            required_tables = ['tenants', 'sales_team', 'customers', 'sales_followup']
            
            for table in required_tables:
                if table not in tables:
                    print(f"Missing required table: {table}")
                    return False
            print("All required tables exist")

            # Check if default tenant exists
            default_tenant = Tenant.query.filter_by(name='Default Tenant').first()
            if not default_tenant:
                print("Default tenant is missing")
                return False
            print("Default tenant exists")

            # Check if admin user exists
            admin_user = SalesPerson.query.filter_by(username='admin').first()
            if not admin_user:
                print("Admin user is missing")
                return False
            print("Admin user exists")

            print("Database verification completed successfully")
            return True

    except Exception as e:
        print(f"Error during database verification: {str(e)}")
        return False

def force_init_db(app):
    """Force reinitialize the database by dropping all tables and recreating them."""
    try:
        with app.app_context():
            db_path = get_db_path()
            print(f"Force initializing database... Database exists: {os.path.exists(db_path)}")
            
            # Drop all tables
            db.drop_all()
            print("Dropped all tables")
            
            # Run migrations
            from flask_migrate import upgrade
            upgrade()
            print("Ran migrations")
            
            # Initialize database
            return init_db(app)
            
    except Exception as e:
        print(f"Error during force initialization: {str(e)}")
        return False

if __name__ == '__main__':
    # This allows running the script directly for testing
    from app import app
    if init_db(app):
        print("Database setup completed successfully")
    else:
        print("Database setup failed, attempting force initialization...")
        if force_init_db(app):
            print("Force initialization completed successfully")
        else:
            print("Force initialization failed") 