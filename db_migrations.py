"""
Incremental schema migrations — safe to run on every startup.
Each block is idempotent: checks before altering, skips if already applied.
"""
import os
import sqlite3

DB_PATH = os.getenv('DATABASE_NAME', '/data/crm_multi.db')


def _col_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def _index_exists(cursor, index_name):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index_name,))
    return cursor.fetchone() is not None


def _table_exists(cursor, table):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cursor.fetchone() is not None


def run(conn):
    cur = conn.cursor()

    # ── M001: activities table (fixes silent log_activity failures) ──────────────
    if not _table_exists(cur, 'activities'):
        cur.executescript("""
            CREATE TABLE activities (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id   INTEGER NOT NULL,
                entity_type TEXT    NOT NULL,
                entity_id   INTEGER NOT NULL,
                action      TEXT    NOT NULL,
                actor_name  TEXT,
                details     TEXT,
                created_at  DATETIME DEFAULT (datetime('now','localtime'))
            );
            CREATE INDEX idx_activities_entity
                ON activities(tenant_id, entity_type, entity_id);
        """)
        print("✅ M001: activities table created")
    else:
        print("⏭  M001: activities table already exists")

    # ── M002: indexes on sales_followup ─────────────────────────────────────────
    if not _index_exists(cur, 'idx_sf_customer'):
        cur.execute("CREATE INDEX idx_sf_customer ON sales_followup(customer_id, tenant_id)")
        print("✅ M002a: idx_sf_customer created")
    if not _index_exists(cur, 'idx_sf_due_date'):
        cur.execute("""
            CREATE INDEX idx_sf_due_date
            ON sales_followup(next_action_due_date)
            WHERE next_action_due_date IS NOT NULL
        """)
        print("✅ M002b: idx_sf_due_date created")
    if not _index_exists(cur, 'idx_sf_salesperson'):
        cur.execute("CREATE INDEX idx_sf_salesperson ON sales_followup(assigned_salesperson_id, tenant_id)")
        print("✅ M002c: idx_sf_salesperson created")

    # ── M003: current_stage column on customers ──────────────────────────────────
    if not _col_exists(cur, 'customers', 'current_stage'):
        cur.execute("ALTER TABLE customers ADD COLUMN current_stage TEXT")
        cur.execute("""
            UPDATE customers
            SET current_stage = (
                SELECT current_sales_stage
                FROM sales_followup
                WHERE customer_id = customers.customer_id
                ORDER BY created_at DESC
                LIMIT 1
            )
        """)
        print("✅ M003: current_stage column added and backfilled")
    else:
        print("⏭  M003: current_stage already exists")

    # ── M004: extend sales_followup (company_id, project_id, updated_at) ───────
    if not _col_exists(cur, 'sales_followup', 'company_id'):
        cur.execute("ALTER TABLE sales_followup ADD COLUMN company_id INTEGER")
        if _col_exists(cur, 'customers', 'company_id'):
            cur.execute("""
                UPDATE sales_followup
                SET company_id = (
                    SELECT company_id FROM customers
                    WHERE customer_id = sales_followup.customer_id
                )
            """)
        print("✅ M004a: company_id added to sales_followup")

    if not _col_exists(cur, 'sales_followup', 'project_id'):
        cur.execute("ALTER TABLE sales_followup ADD COLUMN project_id INTEGER")
        print("✅ M004b: project_id added to sales_followup")

    if not _col_exists(cur, 'sales_followup', 'updated_at'):
        cur.execute("ALTER TABLE sales_followup ADD COLUMN updated_at DATETIME")
        print("✅ M004c: updated_at added to sales_followup")

    conn.commit()


if __name__ == '__main__':
    print(f"Running migrations on: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    try:
        run(conn)
        print("🎉 All migrations complete")
    finally:
        conn.close()
