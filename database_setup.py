import os
from flask import Flask
from flask_migrate import Migrate
from models import db, Tenant, SalesPerson
from werkzeug.security import generate_password_hash
from datetime import datetime

def init_db(app):
    """Initialize the database with required tables and default data."""
    try:
        # Create all tables
        with app.app_context():
            # Run migrations
            from flask_migrate import upgrade
            upgrade()
            
            # Check if default tenant exists
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

            # Check if admin user exists
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

            print("Database initialization completed successfully")
            return True

    except Exception as e:
        print(f"Error during database initialization: {str(e)}")
        return False

def verify_db_setup(app):
    """Verify that the database is properly set up."""
    try:
        with app.app_context():
            # Check if tables exist
            tables = db.engine.table_names()
            required_tables = ['tenants', 'sales_team', 'customers', 'sales_followup']
            
            for table in required_tables:
                if table not in tables:
                    print(f"Missing required table: {table}")
                    return False

            # Check if default tenant exists
            default_tenant = Tenant.query.filter_by(name='Default Tenant').first()
            if not default_tenant:
                print("Default tenant is missing")
                return False

            # Check if admin user exists
            admin_user = SalesPerson.query.filter_by(username='admin').first()
            if not admin_user:
                print("Admin user is missing")
                return False

            print("Database verification completed successfully")
            return True

    except Exception as e:
        print(f"Error during database verification: {str(e)}")
        return False

if __name__ == '__main__':
    # This allows running the script directly for testing
    from app import app
    if init_db(app):
        print("Database setup completed successfully")
    else:
        print("Database setup failed") 