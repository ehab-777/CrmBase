import sqlite3
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import os
from security import bcrypt

# Load environment variables
load_dotenv(override=True)

DATABASE_NAME = os.getenv('DATABASE_NAME', 'crm_multi.db')

def create_tables():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Create tenants table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tenants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        db_key TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Create sales_team table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sales_team (
        salesperson_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        first_name TEXT NOT NULL,
        last_name TEXT,
        password TEXT NOT NULL,
        salesperson_name TEXT NOT NULL,
        work_email TEXT,
        phone_number TEXT,
        role TEXT DEFAULT 'salesperson',
        tenant_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants (id)
    )
    ''')

    # Create customers table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS customers (
        customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT NOT NULL,
        company_industry TEXT,
        contact_person TEXT NOT NULL,
        contact_person_position TEXT,
        phone_number TEXT NOT NULL,
        email_address TEXT,
        company_address TEXT,
        lead_source TEXT,
        initial_interest TEXT,
        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        assigned_salesperson_id INTEGER,
        tenant_id INTEGER,
        FOREIGN KEY (assigned_salesperson_id) REFERENCES sales_team (salesperson_id),
        FOREIGN KEY (tenant_id) REFERENCES tenants (id)
    )
    ''')

    # Create followups table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS followups (
        followup_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        salesperson_id INTEGER NOT NULL,
        followup_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        followup_type TEXT NOT NULL,
        notes TEXT,
        next_followup_date TIMESTAMP,
        status TEXT DEFAULT 'Pending',
        tenant_id INTEGER NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES customers (customer_id),
        FOREIGN KEY (salesperson_id) REFERENCES sales_team (salesperson_id),
        FOREIGN KEY (tenant_id) REFERENCES tenants (id)
    )
    ''')

    # Create activities table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS activities (
        activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        salesperson_id INTEGER NOT NULL,
        activity_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        activity_type TEXT NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'Pending',
        tenant_id INTEGER NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES customers (customer_id),
        FOREIGN KEY (salesperson_id) REFERENCES sales_team (salesperson_id),
        FOREIGN KEY (tenant_id) REFERENCES tenants (id)
    )
    ''')

    conn.commit()
    conn.close()
    print("Database and tables created successfully!")

def add_initial_tenant():
    """Add initial tenant if none exists."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    try:
        # Check if any tenant exists
        cursor.execute('SELECT COUNT(*) FROM tenants')
        if cursor.fetchone()[0] == 0:
            # Add default tenant
            cursor.execute('''
            INSERT INTO tenants (name, db_key)
            VALUES (?, ?)
            ''', ('Default Tenant', 'default'))
            conn.commit()
            print("Default tenant added successfully")
    except sqlite3.Error as e:
        print(f"Error adding initial tenant: {e}")
        conn.rollback()
    finally:
        conn.close()

def add_initial_salesperson():
    """Add initial salesperson if none exists."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    try:
        # Get the default tenant ID
        cursor.execute('SELECT id FROM tenants WHERE db_key = ?', ('default',))
        tenant = cursor.fetchone()
        
        if not tenant:
            print("Default tenant not found. Creating one...")
            add_initial_tenant()
            cursor.execute('SELECT id FROM tenants WHERE db_key = ?', ('default',))
            tenant = cursor.fetchone()
        
        if not tenant:
            print("Error: Could not create default tenant")
            return
            
        tenant_id = tenant[0]
        print(f"Using tenant ID: {tenant_id}")  # Debug log

        # Check if any salesperson exists for this tenant
        cursor.execute('SELECT COUNT(*) FROM sales_team WHERE tenant_id = ?', (tenant_id,))
        if cursor.fetchone()[0] == 0:
            # Add default admin salesperson
            hashed_password = bcrypt.generate_password_hash('admin123').decode('utf-8')
            cursor.execute('''
            INSERT INTO sales_team (first_name, last_name, password, salesperson_name, work_email, role, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', ('Admin', 'User', hashed_password, 'admin', 'admin@example.com', 'admin', tenant_id))
            conn.commit()
            print("Default admin user added successfully")
    except sqlite3.Error as e:
        print(f"Error adding initial salesperson: {e}")
        conn.rollback()
    finally:
        conn.close()

def migrate_tables():
    """Migrate existing tables to new schema."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    try:
        # Check if username column exists in sales_team
        cursor.execute("PRAGMA table_info(sales_team)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'username' not in columns:
            # Add username column without UNIQUE constraint initially
            cursor.execute('ALTER TABLE sales_team ADD COLUMN username TEXT')
            print("Added username column to sales_team table")
            
            # Update existing users to use first_name as username
            cursor.execute("""
                UPDATE sales_team 
                SET username = first_name 
                WHERE username IS NULL
            """)
            print("Updated existing users to use first_name as username")
            
            # Now add UNIQUE constraint
            cursor.execute("""
                CREATE TABLE sales_team_new (
                    salesperson_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    first_name TEXT NOT NULL,
                    last_name TEXT,
                    password TEXT NOT NULL,
                    salesperson_name TEXT NOT NULL,
                    work_email TEXT,
                    phone_number TEXT,
                    role TEXT DEFAULT 'salesperson',
                    tenant_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                )
            """)
            
            # Copy data to new table with explicit column mapping
            cursor.execute("""
                INSERT INTO sales_team_new (
                    salesperson_id, username, first_name, last_name, password,
                    salesperson_name, work_email, phone_number, role, tenant_id
                )
                SELECT 
                    salesperson_id, username, first_name, last_name, password,
                    salesperson_name, work_email, phone_number, role, tenant_id
                FROM sales_team
            """)
            
            # Drop old table and rename new one
            cursor.execute("DROP TABLE sales_team")
            cursor.execute("ALTER TABLE sales_team_new RENAME TO sales_team")
            print("Added UNIQUE constraint to username column")
        
        # Check if last_name column exists in sales_team
        if 'last_name' not in columns:
            # Add last_name column
            cursor.execute('ALTER TABLE sales_team ADD COLUMN last_name TEXT')
            print("Added last_name column to sales_team table")
        
        # Check if sales_followup table exists before trying to modify it
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sales_followup'")
        if cursor.fetchone():
            # Check if created_at column exists in sales_followup
            cursor.execute("PRAGMA table_info(sales_followup)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'created_at' not in columns:
                # Add created_at column
                cursor.execute('ALTER TABLE sales_followup ADD COLUMN created_at TEXT')
                # Update existing rows with current timestamp in local timezone
                local_time = datetime.now(timezone(timedelta(hours=3)))  # Riyadh timezone (UTC+3)
                created_at = local_time.strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute("UPDATE sales_followup SET created_at = ? WHERE created_at IS NULL", (created_at,))
                print("Added created_at column to sales_followup table")
        
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

def add_created_by_to_sales_followup():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(sales_followup)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'created_by' not in columns:
        cursor.execute("ALTER TABLE sales_followup ADD COLUMN created_by INTEGER")
        print("Added 'created_by' column to sales_followup table.")
    else:
        print("'created_by' column already exists in sales_followup table.")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    create_tables()
    migrate_tables()  # Run migration after creating tables
    add_initial_tenant()
    add_initial_salesperson()
    add_created_by_to_sales_followup()

