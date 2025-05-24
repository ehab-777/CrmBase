import sqlite3
from functools import wraps
from flask import session, redirect, url_for, g
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Get database URI from environment
DB_URI = os.getenv("SQLALCHEMY_DATABASE_URI", "sqlite:///crm_multi.db")

def get_db():
    """Get a database connection."""
    # Extract file path from SQLite URI
    db_path = DB_URI.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_current_tenant_id():
    """Get the current tenant ID from the session."""
    return session.get('tenant_id')

def add_tenant_filter(query, params=None):
    """Add tenant_id filter to a query."""
    if params is None:
        params = []
    
    tenant_id = get_current_tenant_id()
    if tenant_id:
        if 'WHERE' in query.upper():
            query = query.replace('WHERE', 'WHERE tenant_id = ? AND', 1)
        elif 'ORDER BY' in query.upper():
            query = query.replace('ORDER BY', 'WHERE tenant_id = ? ORDER BY', 1)
        else:
            query = query + ' WHERE tenant_id = ?'
        
        params.insert(0, tenant_id)
    
    return query, params

def require_tenant(f):
    """Decorator to require a tenant ID in the session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'tenant_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def get_tenant_by_key(db_key):
    """Get tenant by database key."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, db_key FROM tenants WHERE db_key = ?", (db_key,))
    tenant = cursor.fetchone()
    conn.close()
    return tenant

def get_all_tenants():
    """Get all tenants."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, db_key FROM tenants")
    tenants = cursor.fetchall()
    conn.close()
    return tenants 