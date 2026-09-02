import sqlite3
import os

db_path = '/Users/ehababuelsoud/.gemini/antigravity-ide/scratch/CrmBase/crm_multi.db'

def migrate():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("Creating company_profiles table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS company_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            company_name TEXT,
            company_description TEXT,
            industry TEXT,
            websites TEXT,
            business_units TEXT,
            core_services TEXT,
            products TEXT,
            target_audience TEXT,
            target_industries TEXT,
            geographic_market TEXT,
            competitors TEXT,
            usps TEXT,
            vision TEXT,
            mission TEXT,
            business_goals TEXT,
            strategic_priorities TEXT,
            current_priorities TEXT,
            things_not_to_focus_on TEXT,
            decision_rules TEXT,
            ai_instructions TEXT,
            updated_at DATETIME DEFAULT (datetime('now')),
            UNIQUE(tenant_id)
        )
    """)
    print("Table company_profiles created successfully.")

    # Seed an empty row for existing tenants
    cursor.execute("SELECT id FROM tenants")
    tenants = cursor.fetchall()
    for (tenant_id,) in tenants:
        cursor.execute("SELECT COUNT(*) FROM company_profiles WHERE tenant_id = ?", (tenant_id,))
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.execute(
                "INSERT INTO company_profiles (tenant_id, company_name) VALUES (?, ?)", 
                (tenant_id, "اسم شركتك (يرجى التعديل)")
            )
            print(f"Seeded empty profile for tenant_id: {tenant_id}")
            
    conn.commit()
    conn.close()
    print("Migration complete!")

if __name__ == '__main__':
    migrate()
