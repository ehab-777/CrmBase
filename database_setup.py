import os
from flask import Flask
from models import db, Tenant, SalesPerson, Role, Permission, User, Customer, SalesFollowup
from werkzeug.security import generate_password_hash
from datetime import datetime
import sqlite3
import sys
from security import bcrypt
from app import app

# Get database URI from environment
DB_URI = os.getenv("SQLALCHEMY_DATABASE_URI", "sqlite:///crm_multi.db")

def log_message(message):
    """Log message to both stdout and stderr."""
    print(message, file=sys.stderr)
    print(message)

def get_db_path():
    """Get the database path from environment variables."""
    log_message(f"Database URI: {DB_URI}")
    return DB_URI

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
        # Extract file path from SQLite URI
        db_path = DB_URI.replace('sqlite:///', '')
        log_message(f"Database exists: {os.path.exists(db_path)}")
        if not os.path.exists(db_path):
            log_message(f"Database file does not exist at {db_path}")
            return False

        conn = sqlite3.connect(db_path)
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

def force_init_db(app):
    """Force initialize the database. Only allowed in development environment."""
    if os.getenv("FLASK_ENV") != "development":
        log_message("❌ Force initialization is only allowed in development environment")
        return False
        
    with app.app_context():
        try:
            log_message("🔄 Starting force database initialization...")
            
            # Force drop all tables
            log_message("🗑️ Dropping all existing tables...")
            db.drop_all()
            db.session.commit()
            log_message("✅ Tables dropped")
            
            # Create all tables
            log_message("📦 Creating tables...")
            db.create_all()
            db.session.commit()
            log_message("✅ Tables created")
            
            # Verify tables exist
            tables = db.engine.table_names()
            log_message(f"📊 Available tables: {tables}")
            
            if 'tenants' not in tables:
                raise Exception("tenants table was not created")
            
            # Create default tenant
            log_message("👥 Creating default tenant...")
            default_tenant = Tenant(
                name='Default Tenant',
                db_key='default',
                created_at=datetime.utcnow()
            )
            db.session.add(default_tenant)
            db.session.commit()
            log_message("✅ Default tenant created")
            
            # Create admin role
            log_message("👮 Creating admin role...")
            admin_role = Role(
                name='admin',
                description='Administrator role with full access'
            )
            db.session.add(admin_role)
            db.session.commit()
            log_message("✅ Admin role created")
            
            # Create admin user
            log_message("👤 Creating admin user...")
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
            log_message("✅ Admin user created")
            
            # Verify data was created
            tenant_count = Tenant.query.count()
            user_count = SalesPerson.query.count()
            role_count = Role.query.count()
            
            log_message(f"📊 Verification:")
            log_message(f"- Tenants: {tenant_count}")
            log_message(f"- Users: {user_count}")
            log_message(f"- Roles: {role_count}")
            
            if tenant_count == 0 or user_count == 0 or role_count == 0:
                raise Exception("Data verification failed")
            
            log_message("✅ Force database initialization completed successfully")
            return True
            
        except Exception as e:
            log_message(f"❌ Error during force database initialization: {str(e)}")
            db.session.rollback()
            return False

def init_db():
    """Initialize the database. Only allowed in development environment."""
    if os.getenv("FLASK_ENV") != "development":
        log_message("❌ Database initialization is only allowed in development environment")
        return False
        
    with app.app_context():
        try:
            log_message("🔄 Starting database initialization...")
            
            # Force drop all tables
            log_message("🗑️ Dropping all existing tables...")
            db.drop_all()
            db.session.commit()
            log_message("✅ Tables dropped")
            
            # Create all tables
            log_message("📦 Creating tables...")
            db.create_all()
            db.session.commit()
            log_message("✅ Tables created")
            
            # Verify tables exist
            tables = db.engine.table_names()
            log_message(f"📊 Available tables: {tables}")
            
            if 'tenants' not in tables:
                raise Exception("tenants table was not created")
            
            # Create default tenant
            log_message("👥 Creating default tenant...")
            default_tenant = Tenant(
                name='Default Tenant',
                db_key='default',
                created_at=datetime.utcnow()
            )
            db.session.add(default_tenant)
            db.session.commit()
            log_message("✅ Default tenant created")
            
            # Create admin role
            log_message("👮 Creating admin role...")
            admin_role = Role(
                name='admin',
                description='Administrator role with full access'
            )
            db.session.add(admin_role)
            db.session.commit()
            log_message("✅ Admin role created")
            
            # Create admin user
            log_message("👤 Creating admin user...")
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
            log_message("✅ Admin user created")
            
            # Verify data was created
            tenant_count = Tenant.query.count()
            user_count = SalesPerson.query.count()
            role_count = Role.query.count()
            
            log_message(f"📊 Verification:")
            log_message(f"- Tenants: {tenant_count}")
            log_message(f"- Users: {user_count}")
            log_message(f"- Roles: {role_count}")
            
            if tenant_count == 0 or user_count == 0 or role_count == 0:
                raise Exception("Data verification failed")
            
            log_message("✅ Database initialization completed successfully")
            return True
            
        except Exception as e:
            log_message(f"❌ Error during database initialization: {str(e)}")
            db.session.rollback()
            return False

if __name__ == '__main__':
    # This allows running the script directly for testing
    if os.getenv("FLASK_ENV") != "development":
        log_message("❌ This script can only be run in development environment")
        sys.exit(1)
        
    if init_db():
        log_message("Database setup completed successfully")
    else:
        log_message("Database setup failed, attempting force initialization...")
        if force_init_db(app):
            log_message("Force initialization completed successfully")
        else:
            log_message("Force initialization failed") 