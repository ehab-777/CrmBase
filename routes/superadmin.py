from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, abort
import sqlite3
from functools import wraps
from tenant_utils import get_db
from security import bcrypt

superadmin_bp = Blueprint('superadmin', __name__, url_prefix='/superadmin')


def require_superadmin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_superadmin'):
            return redirect(url_for('superadmin.login'))
        return f(*args, **kwargs)
    return decorated


@superadmin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('is_superadmin'):
        return redirect(url_for('superadmin.dashboard'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT id, name, username, email, password FROM superadmins WHERE username = ? OR email = ?",
                (username, username)
            ).fetchone()
            if not row:
                error = 'Invalid credentials'
            elif not bcrypt.check_password_hash(row['password'], password):
                error = 'Invalid credentials'
            else:
                session.clear()
                session['is_superadmin'] = True
                session['superadmin_id'] = row['id']
                session['superadmin_name'] = row['name'] or row['username']
                return redirect(url_for('superadmin.dashboard'))
        except sqlite3.Error:
            error = 'Database error'
        finally:
            conn.close()

    return render_template('superadmin/login.html', error=error)


@superadmin_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('superadmin.login'))


@superadmin_bp.route('/')
@require_superadmin
def dashboard():
    conn = get_db()
    try:
        total_tenants = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        active_subs = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE status = 'active'"
        ).fetchone()[0]
        trial_subs = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE status = 'trial'"
        ).fetchone()[0]
        expired_subs = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE status = 'expired'"
        ).fetchone()[0]
        total_users = conn.execute("SELECT COUNT(*) FROM sales_team").fetchone()[0]
        total_plans = conn.execute("SELECT COUNT(*) FROM plans WHERE is_active = 1").fetchone()[0]

        recent_tenants = conn.execute("""
            SELECT t.id, t.name, t.account_type, t.created_at,
                   p.name as plan_name, s.status as sub_status, s.end_date
            FROM tenants t
            LEFT JOIN subscriptions s ON s.tenant_id = t.id
            LEFT JOIN plans p ON p.id = s.plan_id
            ORDER BY t.created_at DESC
            LIMIT 5
        """).fetchall()

    finally:
        conn.close()

    stats = {
        'total_tenants': total_tenants,
        'active_subs': active_subs,
        'trial_subs': trial_subs,
        'expired_subs': expired_subs,
        'total_users': total_users,
        'total_plans': total_plans,
    }
    return render_template('superadmin/dashboard.html', stats=stats, recent_tenants=recent_tenants)


# ── Tenants ──────────────────────────────────────────────────────────────────

@superadmin_bp.route('/tenants')
@require_superadmin
def tenants():
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT t.id, t.name, t.db_key, t.account_type, t.created_at,
                   p.name  as plan_name,
                   p.id    as plan_id,
                   s.id    as sub_id,
                   s.status as sub_status,
                   s.end_date,
                   (SELECT COUNT(*) FROM sales_team st WHERE st.tenant_id = t.id) as user_count
            FROM tenants t
            LEFT JOIN subscriptions s ON s.tenant_id = t.id
            LEFT JOIN plans p ON p.id = s.plan_id
            ORDER BY t.created_at DESC
        """).fetchall()
        plans = conn.execute("SELECT id, name FROM plans WHERE is_active = 1 ORDER BY price_monthly").fetchall()
    finally:
        conn.close()

    return render_template('superadmin/tenants.html', tenants=rows, plans=plans)


@superadmin_bp.route('/tenants/save', methods=['POST'])
@require_superadmin
def save_tenant():
    tenant_id    = request.form.get('tenant_id')
    name         = request.form.get('name', '').strip()
    db_key       = request.form.get('db_key', '').strip()
    account_type = request.form.get('account_type', 'company')

    if not name or not db_key:
        return redirect(url_for('superadmin.tenants'))
    if account_type not in ('individual', 'company'):
        account_type = 'company'

    conn = get_db()
    try:
        if tenant_id:
            conn.execute(
                "UPDATE tenants SET name=?, db_key=?, account_type=? WHERE id=?",
                (name, db_key, account_type, tenant_id)
            )
        else:
            conn.execute(
                "INSERT INTO tenants (name, db_key, account_type) VALUES (?, ?, ?)",
                (name, db_key, account_type)
            )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()

    return redirect(url_for('superadmin.tenants'))


@superadmin_bp.route('/tenants/<int:tenant_id>/delete', methods=['POST'])
@require_superadmin
def delete_tenant(tenant_id):
    conn = get_db()
    try:
        user_count = conn.execute(
            "SELECT COUNT(*) FROM sales_team WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()[0]
        if user_count > 0:
            return jsonify({'success': False, 'message': f'Cannot delete: tenant has {user_count} user(s)'}), 400
        conn.execute("DELETE FROM subscriptions WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        conn.commit()
        return jsonify({'success': True})
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()


@superadmin_bp.route('/tenants/<int:tenant_id>/subscription', methods=['POST'])
@require_superadmin
def update_subscription(tenant_id):
    plan_id  = request.form.get('plan_id')
    status   = request.form.get('status', 'active')
    end_date = request.form.get('end_date')

    if status not in ('trial', 'active', 'expired', 'suspended'):
        status = 'active'

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM subscriptions WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE subscriptions
                SET plan_id = ?, status = ?, end_date = ?
                WHERE tenant_id = ?
            """, (plan_id, status, end_date or None, tenant_id))
        else:
            conn.execute("""
                INSERT INTO subscriptions (tenant_id, plan_id, status, start_date, end_date)
                VALUES (?, ?, ?, DATE('now'), ?)
            """, (tenant_id, plan_id, status, end_date or None))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()

    return redirect(url_for('superadmin.tenants'))


@superadmin_bp.route('/tenants/<int:tenant_id>/toggle', methods=['POST'])
@require_superadmin
def toggle_tenant(tenant_id):
    """Suspend or reactivate a tenant's subscription."""
    conn = get_db()
    try:
        sub = conn.execute(
            "SELECT id, status FROM subscriptions WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        if not sub:
            return jsonify({'success': False, 'message': 'No subscription found'}), 404
        new_status = 'active' if sub['status'] == 'suspended' else 'suspended'
        conn.execute("UPDATE subscriptions SET status = ? WHERE tenant_id = ?", (new_status, tenant_id))
        conn.commit()
        return jsonify({'success': True, 'status': new_status})
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()


# ── Plans ─────────────────────────────────────────────────────────────────────

@superadmin_bp.route('/plans')
@require_superadmin
def plans():
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT p.*,
                   (SELECT COUNT(*) FROM subscriptions s WHERE s.plan_id = p.id AND s.status = 'active') as active_count
            FROM plans p ORDER BY p.price_monthly
        """).fetchall()
    finally:
        conn.close()
    return render_template('superadmin/plans.html', plans=rows)


@superadmin_bp.route('/plans/save', methods=['POST'])
@require_superadmin
def save_plan():
    plan_id       = request.form.get('plan_id')
    name          = request.form.get('name', '').strip()
    price_monthly = request.form.get('price_monthly', 0)
    max_users     = request.form.get('max_users', -1)
    max_customers = request.form.get('max_customers', -1)
    is_active     = 1 if request.form.get('is_active') else 0

    if not name:
        return redirect(url_for('superadmin.plans'))

    conn = get_db()
    try:
        if plan_id:
            conn.execute("""
                UPDATE plans SET name=?, price_monthly=?, max_users=?, max_customers=?, is_active=?
                WHERE id=?
            """, (name, price_monthly, max_users, max_customers, is_active, plan_id))
        else:
            conn.execute("""
                INSERT INTO plans (name, price_monthly, max_users, max_customers, is_active)
                VALUES (?, ?, ?, ?, ?)
            """, (name, price_monthly, max_users, max_customers, is_active))
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
    finally:
        conn.close()

    return redirect(url_for('superadmin.plans'))


@superadmin_bp.route('/plans/<int:plan_id>/delete', methods=['POST'])
@require_superadmin
def delete_plan(plan_id):
    conn = get_db()
    try:
        in_use = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE plan_id = ?", (plan_id,)
        ).fetchone()[0]
        if in_use:
            return jsonify({'success': False, 'message': 'Plan is assigned to tenants'}), 400
        conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        conn.commit()
        return jsonify({'success': True})
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()
