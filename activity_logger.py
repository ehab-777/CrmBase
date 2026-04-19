"""activity_logger.py — lightweight activity-event helper.

All functions accept an *open* sqlite3 connection and do NOT commit;
the caller is responsible for committing the transaction.
"""
from flask import session


def log_activity(conn, tenant_id, entity_type, entity_id, action, details=None):
    """Insert one activity row into the activities table.

    Uses the caller's already-open connection so the insert is part of
    the same transaction as the triggering change.  Never raises — any
    failure is silently swallowed so the main operation is never blocked.

    Args:
        conn        – open sqlite3 connection (row_factory = sqlite3.Row)
        tenant_id   – current tenant ID
        entity_type – 'customer' | 'company' | 'project'
        entity_id   – PK of the affected record
        action      – 'created' | 'updated' | 'status_changed' |
                      'follow_up_added' | 'contact_linked' | 'contact_unlinked'
        details     – optional human-readable description string
    """
    actor = session.get('salesperson_name') or 'System'
    try:
        conn.execute(
            """INSERT INTO activities
                   (tenant_id, entity_type, entity_id, action, actor_name, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tenant_id, entity_type, entity_id, action, actor, details)
        )
    except Exception:
        pass  # never break the main flow


def get_activities(conn, tenant_id, entity_type, entity_id, limit=40):
    """Return recent activities for a given entity as a list of plain dicts.

    Uses 'localtime' conversion so timestamps match the server timezone.
    Returns an empty list on any failure.
    """
    try:
        rows = conn.execute(
            """SELECT id, action, actor_name, details,
                      datetime(created_at, 'localtime') AS ts
               FROM   activities
               WHERE  tenant_id = ?
                 AND  entity_type = ?
                 AND  entity_id   = ?
               ORDER  BY created_at DESC
               LIMIT  ?""",
            (tenant_id, entity_type, entity_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
