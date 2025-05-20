#!/usr/bin/env python3

import os
import sqlite3

def verify_database():
    # ✅ Step 1: Check if the mounted disk path exists
    db_path = os.getenv("SQLALCHEMY_DATABASE_URI", "sqlite:////data/crm_multi.db").replace("sqlite:///", "")
    
    # Log the path for visibility
    print(f"📁 Checking if path exists: {db_path}")
    
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"❌ Database file does not exist at {db_path}. Check if the Render disk is mounted at /data.")
    
    # ✅ Step 2: Check file size
    size = os.path.getsize(db_path)
    print(f"📦 Database size: {size} bytes")
    
    if size == 0:
        raise ValueError("⚠️ Database file exists but is empty. This may indicate a mounting issue or reinitialization.")
    
    # ✅ Step 3: Confirm table existence (e.g., tenants)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) FROM tenants")
        count = cursor.fetchone()[0]
        print(f"✅ Found {count} rows in tenants table.")
    except sqlite3.OperationalError as e:
        raise RuntimeError(f"❌ Could not find 'tenants' table. Error: {str(e)}")
    finally:
        conn.close()
    
    print("✅ Render disk and database check passed.")

if __name__ == "__main__":
    verify_database() 