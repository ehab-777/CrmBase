import sqlite3
from datetime import datetime, timezone, timedelta

DATABASE_NAME = 'crm.db'

def create_tables():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Create companies table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS companies (
            company_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create customers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            company_name TEXT NOT NULL,
            contact_person TEXT,
            phone_number TEXT,
            email_address TEXT,
            company_address TEXT,
            lead_source TEXT,
            initial_interest TEXT,
            date_added TEXT,
            last_contact_date TEXT,
            current_sales_stage TEXT,
            assigned_salesperson_id INTEGER,
            FOREIGN KEY (company_id) REFERENCES companies(company_id),
            FOREIGN KEY (assigned_salesperson_id) REFERENCES sales_team(salesperson_id)
        )
    ''')

    # Create sales_team table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales_team (
            salesperson_id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT,
            password TEXT NOT NULL,
            salesperson_name TEXT,
            work_email TEXT,
            role TEXT DEFAULT 'salesperson',
            FOREIGN KEY (company_id) REFERENCES companies(company_id),
            UNIQUE(first_name, last_name, company_id)
        )
    ''')

    # Create sales_followup table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales_followup (
            followup_id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            assigned_salesperson_id INTEGER NOT NULL,
            last_contact_date TEXT,
            last_contact_method TEXT,
            summary_last_contact TEXT,
            next_action TEXT,
            next_action_due_date TEXT,
            current_sales_stage TEXT,
            potential_deal_value REAL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(company_id),
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
            FOREIGN KEY (assigned_salesperson_id) REFERENCES sales_team(salesperson_id)
        )
    ''')

    conn.commit()
    conn.close()
    print("Database and tables created successfully!")

def migrate_to_multi_tenant():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    try:
        # Create companies table if it doesn't exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS companies (
                company_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Add company_id columns to existing tables
        tables = ['customers', 'sales_team', 'sales_followup']
        for table in tables:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN company_id INTEGER")
            except sqlite3.OperationalError:
                print(f"Column company_id already exists in {table}")

        # Create a default company
        cursor.execute("INSERT INTO companies (name) VALUES ('Default Company')")
        default_company_id = cursor.lastrowid

        # Update existing records with default company_id
        for table in tables:
            cursor.execute(f"UPDATE {table} SET company_id = ? WHERE company_id IS NULL", (default_company_id,))

        # Add foreign key constraints
        for table in tables:
            cursor.execute(f'''
                CREATE TABLE {table}_new AS 
                SELECT * FROM {table}
            ''')
            cursor.execute(f"DROP TABLE {table}")
            cursor.execute(f"ALTER TABLE {table}_new RENAME TO {table}")

        conn.commit()
        print("Migration to multi-tenant completed successfully!")
    except sqlite3.Error as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

def add_initial_salesperson(first_name, password, company_id=1):
    import hashlib
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Hash the password
    hashed_password = hashlib.sha256(password.encode()).hexdigest()

    try:
        cursor.execute("INSERT INTO sales_team (first_name, password, company_id) VALUES (?, ?, ?)", 
                      (first_name, hashed_password, company_id))
        conn.commit()
        print(f"Salesperson '{first_name}' added successfully.")
    except sqlite3.IntegrityError:
        print(f"Salesperson with first name '{first_name}' already exists.")
    finally:
        conn.close()

if __name__ == '__main__':
    create_tables()
    migrate_to_multi_tenant()
    add_initial_salesperson('alsaied', 'smc789') # For now, we'll add directly. In the full app, we'll have a signup.

