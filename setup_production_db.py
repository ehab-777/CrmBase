"""
First-time database setup for production (Railway).
Creates all tables and a default admin account.
Run automatically by init.sh when DB is missing.
"""
import os
import sys
import sqlite3
from datetime import datetime

DB_PATH = os.getenv('DATABASE_NAME', '/data/crm_multi.db')

print(f"Setting up database at: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# ── Create tables ──────────────────────────────────────────────────────────────

cursor.executescript('''
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    db_key TEXT UNIQUE NOT NULL DEFAULT 'default',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sales_team (
    salesperson_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    password TEXT NOT NULL,
    salesperson_name TEXT NOT NULL,
    work_email TEXT NOT NULL,
    phone_number TEXT,
    role TEXT DEFAULT 'salesperson',
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    telegram_chat_id TEXT UNIQUE,
    telegram_link_token TEXT
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    contact_person TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    email_address TEXT,
    company_address TEXT,
    lead_source TEXT,
    initial_interest TEXT,
    company_industry TEXT,
    contact_person_position TEXT,
    assigned_salesperson_id INTEGER NOT NULL REFERENCES sales_team(salesperson_id),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    date_added DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sales_followup (
    followup_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    assigned_salesperson_id INTEGER NOT NULL REFERENCES sales_team(salesperson_id),
    last_contact_date DATETIME NOT NULL,
    last_contact_method TEXT,
    summary_last_contact TEXT,
    next_action TEXT,
    next_action_due_date DATETIME,
    current_sales_stage TEXT,
    potential_deal_value REAL,
    notes TEXT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER NOT NULL REFERENCES sales_team(salesperson_id)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quotations (
    quotation_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    quotation_number TEXT,
    customer_id     INTEGER NOT NULL,
    salesperson_id  INTEGER NOT NULL,
    status          TEXT    DEFAULT 'draft',
    issue_date      TEXT    DEFAULT (date('now','localtime')),
    valid_until     TEXT,
    notes           TEXT,
    terms           TEXT,
    discount_type   TEXT    DEFAULT 'none',
    discount_value  REAL    DEFAULT 0,
    tax_percent     REAL    DEFAULT 0,
    subtotal        REAL    DEFAULT 0,
    discount_amount REAL    DEFAULT 0,
    tax_amount      REAL    DEFAULT 0,
    total           REAL    DEFAULT 0,
    currency        TEXT    DEFAULT 'SAR',
    tenant_id       INTEGER NOT NULL,
    created_at      DATETIME DEFAULT (datetime('now','localtime')),
    updated_at      DATETIME DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS quotation_items (
    item_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    quotation_id INTEGER NOT NULL,
    product_id   INTEGER,
    name         TEXT    NOT NULL,
    description  TEXT,
    quantity     REAL    NOT NULL DEFAULT 1,
    unit         TEXT    DEFAULT 'unit',
    unit_price   REAL    NOT NULL DEFAULT 0,
    discount_pct REAL    DEFAULT 0,
    line_total   REAL    NOT NULL DEFAULT 0,
    sort_order   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    product_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    category      TEXT,
    description   TEXT,
    selling_price REAL NOT NULL DEFAULT 0,
    min_price     REAL DEFAULT 0,
    cost          REAL DEFAULT 0,
    unit          TEXT DEFAULT 'unit',
    is_active     INTEGER DEFAULT 1,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
    created_at    DATETIME DEFAULT (datetime('now','localtime'))
);
''')

conn.commit()
print("✅ Tables created")

# ── Seed default tenant ────────────────────────────────────────────────────────

cursor.execute("SELECT id FROM tenants WHERE db_key = 'default'")
if not cursor.fetchone():
    cursor.execute(
        "INSERT INTO tenants (name, db_key) VALUES (?, ?)",
        ('Default Organization', 'default')
    )
    conn.commit()
    print("✅ Default tenant created")

cursor.execute("SELECT id FROM tenants WHERE db_key = 'default'")
tenant_id = cursor.fetchone()[0]

# ── Seed default admin ─────────────────────────────────────────────────────────

cursor.execute("SELECT salesperson_id FROM sales_team WHERE username = 'admin'")
if not cursor.fetchone():
    # Hash password using bcrypt
    try:
        import bcrypt
        hashed = bcrypt.hashpw(b'admin123', bcrypt.gensalt()).decode('utf-8')
    except ImportError:
        from werkzeug.security import generate_password_hash
        hashed = generate_password_hash('admin123')

    cursor.execute('''
        INSERT INTO sales_team
            (username, first_name, last_name, password, salesperson_name,
             work_email, role, tenant_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', ('admin', 'Admin', 'User', hashed, 'Admin',
          'admin@crmbase.com', 'admin', tenant_id))
    conn.commit()
    print("✅ Default admin created  →  username: admin  /  password: admin123")
    print("⚠️  Change the admin password after first login!")
else:
    print("✅ Admin user already exists")

conn.close()
print("🎉 Database setup complete")
