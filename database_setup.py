import os
from flask import Flask
from models import db, Tenant, SalesPerson, Role, Permission, AuditLog, User, Customer, SalesFollowup
from werkzeug.security import generate_password_hash
from datetime import datetime
import sqlite3
import sys
from security import bcrypt
from app import app

DB_PATH = os.getenv("DATABASE_NAME", "/data/crm_multi.db")

def log_message(message):
    """Log message to both stdout and stderr."""
    print(message, file=sys.stderr)
    print(message)

def get_db_path():
    """Get the database path from environment variables."""
    log_message(f"Database path: {DB_PATH}")
    return DB_PATH

def create_tables(app, table_names):
    """Create specific tables without reinitializing the entire database."""
    with app.app_context():
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # Create tables based on the provided names
            if 'tenants' in table_names:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS tenants (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        db_key TEXT NOT NULL UNIQUE
                    )
                ''')
            
            if 'sales_team' in table_names:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sales_team (
                        salesperson_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE,
                        first_name TEXT NOT NULL,
                        last_name TEXT NOT NULL,
                        password TEXT NOT NULL,
                        salesperson_name TEXT NOT NULL,
                        work_email TEXT,
                        phone_number TEXT,
                        role TEXT NOT NULL DEFAULT 'salesperson',
                        tenant_id INTEGER NOT NULL,
                        FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                    )
                ''')
            
            if 'customers' in table_names:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS customers (
                        customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        company_name TEXT NOT NULL,
                        contact_person TEXT,
                        phone_number TEXT,
                        email TEXT,
                        assigned_salesperson_id INTEGER,
                        tenant_id INTEGER NOT NULL,
                        FOREIGN KEY (assigned_salesperson_id) REFERENCES sales_team (salesperson_id),
                        FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                    )
                ''')
            
            if 'sales_followup' in table_names:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sales_followup (
                        followup_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        customer_id INTEGER NOT NULL,
                        salesperson_id INTEGER NOT NULL,
                        followup_date DATE NOT NULL,
                        followup_time TIME NOT NULL,
                        followup_type TEXT NOT NULL,
                        notes TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        current_sales_stage TEXT,
                        deal_value REAL,
                        next_action TEXT,
                        next_action_date DATE,
                        last_contact_date DATE,
                        tenant_id INTEGER NOT NULL,
                        FOREIGN KEY (customer_id) REFERENCES customers (customer_id),
                        FOREIGN KEY (salesperson_id) REFERENCES sales_team (salesperson_id),
                        FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                    )
                ''')
            
            conn.commit()
            return True
        except Exception as e:
            print(f"Error creating tables: {str(e)}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()

def verify_tables_exist():
    """Verify that all required tables exist in the database."""
    try:
        log_message(f"Database exists: {os.path.exists(DB_PATH)}")
        if not os.path.exists(DB_PATH):
            log_message(f"Database file does not exist at {DB_PATH}")
            return False

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
        tables = [table[0] for table in cursor.fetchall()]
        
        # Get table schemas
        for table in tables:
            cursor.execute(f"PRAGMA table_info({table})")
            columns = cursor.fetchall()
            log_message(f"Table {table} columns: {columns}")
        
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

def init_db():
    with app.app_context():
        try:
            print("🔄 Starting database initialization...")
            
            # Drop all tables first to ensure clean state
            db.drop_all()
            print("✅ Dropped all existing tables")
            
            # Create all tables
            db.create_all()
            print("✅ Created all tables")
            
            # Create default tenant
            default_tenant = Tenant(
                name='Default Tenant',
                db_key='default',
                created_at=datetime.utcnow()
            )
            db.session.add(default_tenant)
            db.session.commit()
            print("✅ Created default tenant")
            
            # Create admin role
            admin_role = Role(
                name='admin',
                description='Administrator role with full access'
            )
            db.session.add(admin_role)
            db.session.commit()
            print("✅ Created admin role")
            
            # Create admin user
            admin = SalesPerson(
                username='admin',
                first_name='Admin',
                last_name='User',
                password=bcrypt.generate_password_hash('admin123').decode('utf-8'),
                salesperson_name='Admin User',
                work_email='admin@example.com',
                role='admin',
                tenant_id=default_tenant.id,
                created_at=datetime.utcnow()
            )
            db.session.add(admin)
            db.session.commit()
            print("✅ Created admin user")
            
            # Verify tables exist
            tables = db.engine.table_names()
            print(f"📊 Available tables: {tables}")
            
            # Verify data was created
            tenant_count = Tenant.query.count()
            user_count = SalesPerson.query.count()
            role_count = Role.query.count()
            
            print(f"📊 Verification:")
            print(f"- Tenants: {tenant_count}")
            print(f"- Users: {user_count}")
            print(f"- Roles: {role_count}")
            
            print("✅ Database initialization completed successfully")
            return True
            
        except Exception as e:
            print(f"❌ Error during database initialization: {str(e)}")
            db.session.rollback()
            return False

def verify_db_setup(app):
    """Verify that the database is properly set up."""
    try:
        with app.app_context():
            log_message(f"Verifying database setup... Database exists: {os.path.exists(DB_PATH)}")
            
            # Check if database file exists and has content
            if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
                log_message("Database file does not exist or is empty")
                return False
            
            # Verify tables exist and have correct structure
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
            log_message(f"Force initializing database... Database exists: {os.path.exists(DB_PATH)}")
            
            # Drop all tables
            db.drop_all()
            log_message("Dropped all tables")
            
            # Create tables
            if not create_tables(app, ['tenants', 'sales_team', 'customers', 'sales_followup']):
                log_message("Failed to create tables during force initialization")
                return False
            
            # Initialize database
            return init_db()
            
    except Exception as e:
        log_message(f"Error during force initialization: {str(e)}")
        return False

if __name__ == '__main__':
    # This allows running the script directly for testing
    if init_db():
        log_message("Database setup completed successfully")
    else:
        log_message("Database setup failed, attempting force initialization...")
        if force_init_db(app):
            log_message("Force initialization completed successfully")
        else:
            log_message("Force initialization failed") 