"""
Run once to create the initial superadmin account.
Usage:  python create_superadmin.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from tenant_utils import get_db
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt()

NAME     = "Ehab"
USERNAME = "superadmin@crmbase.com"   # used to log in
EMAIL    = "superadmin@crmbase.com"
PASSWORD = "pass123"

hashed = bcrypt.generate_password_hash(PASSWORD).decode('utf-8')

conn = get_db()
try:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS superadmins (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            username   TEXT    UNIQUE NOT NULL,
            email      TEXT    UNIQUE NOT NULL,
            password   TEXT    NOT NULL,
            created_at DATETIME DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO superadmins (name, username, email, password) VALUES (?, ?, ?, ?)",
        (NAME, USERNAME, EMAIL, hashed)
    )
    conn.commit()
    print(f"✓ Superadmin '{NAME}' ({EMAIL}) created successfully.")
    print(f"  Login at: /superadmin/login")
    print(f"  Username: {USERNAME}")
    print(f"  Password: {PASSWORD}")
except Exception as e:
    print(f"✗ Error: {e}")
finally:
    conn.close()
