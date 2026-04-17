"""
User Profile — self-service management
=======================================
Routes:
  GET  /profile          → view own profile
  POST /profile/edit     → update name / email / phone
  POST /profile/password → change own password
  POST /profile/lang     → change UI language (moved from fixed widget)

Admin-only:
  POST /profile/set-role/<int:uid>  → change another user's role
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from tenant_utils import get_db, get_current_tenant_id, require_tenant
from security import bcrypt

profile_bp = Blueprint('profile', __name__, url_prefix='/profile')

ROLES = ['salesperson', 'manager', 'admin']


def _current_user():
    """Return the logged-in user's row from sales_team."""
    conn = get_db()
    row = conn.execute(
        '''SELECT salesperson_id, first_name, last_name, salesperson_name,
                  work_email, phone_number, role, tenant_id,
                  telegram_chat_id
           FROM sales_team
           WHERE salesperson_id = ?''',
        (session['salesperson_id'],)
    ).fetchone()
    conn.close()
    return row


# ── View ──────────────────────────────────────────────────────────────────────

@profile_bp.route('/')
@require_tenant
def profile_page():
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    user = _current_user()

    # Admin: load all users in the tenant for role management
    team = []
    if session.get('role') == 'admin':
        conn = get_db()
        team = conn.execute(
            '''SELECT salesperson_id, salesperson_name, work_email, role
               FROM sales_team
               WHERE tenant_id = ?
               ORDER BY salesperson_name''',
            (get_current_tenant_id(),)
        ).fetchall()
        conn.close()

    return render_template('profile/profile.html', user=user, team=team, roles=ROLES)


# ── Edit profile ───────────────────────────────────────────────────────────────

@profile_bp.route('/edit', methods=['POST'])
@require_tenant
def edit_profile():
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    salesperson_name = request.form.get('salesperson_name', '').strip()
    work_email       = request.form.get('work_email', '').strip()
    phone_number     = request.form.get('phone_number', '').strip()
    first_name       = request.form.get('first_name', '').strip()
    last_name        = request.form.get('last_name', '').strip()

    if not salesperson_name:
        flash('Display name is required.', 'error')
        return redirect(url_for('profile.profile_page'))

    conn = get_db()
    conn.execute(
        '''UPDATE sales_team
           SET salesperson_name = ?, work_email = ?, phone_number = ?,
               first_name = ?, last_name = ?
           WHERE salesperson_id = ?''',
        (salesperson_name, work_email, phone_number,
         first_name, last_name, session['salesperson_id'])
    )
    conn.commit()
    conn.close()

    # Update session name so sidebar reflects change immediately
    session['salesperson_name'] = salesperson_name
    flash('Profile updated successfully.', 'success')
    return redirect(url_for('profile.profile_page'))


# ── Change password ────────────────────────────────────────────────────────────

@profile_bp.route('/password', methods=['POST'])
@require_tenant
def change_password():
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    current_pw  = request.form.get('current_password', '')
    new_pw      = request.form.get('new_password', '')
    confirm_pw  = request.form.get('confirm_password', '')

    if not current_pw or not new_pw or not confirm_pw:
        flash('All password fields are required.', 'error')
        return redirect(url_for('profile.profile_page'))

    if new_pw != confirm_pw:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('profile.profile_page'))

    if len(new_pw) < 8:
        flash('New password must be at least 8 characters.', 'error')
        return redirect(url_for('profile.profile_page'))

    conn = get_db()
    row = conn.execute(
        'SELECT password FROM sales_team WHERE salesperson_id = ?',
        (session['salesperson_id'],)
    ).fetchone()

    if not row or not bcrypt.check_password_hash(row['password'], current_pw):
        conn.close()
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('profile.profile_page'))

    hashed = bcrypt.generate_password_hash(new_pw).decode('utf-8')
    conn.execute(
        'UPDATE sales_team SET password = ? WHERE salesperson_id = ?',
        (hashed, session['salesperson_id'])
    )
    conn.commit()
    conn.close()
    flash('Password changed successfully.', 'success')
    return redirect(url_for('profile.profile_page'))


# ── Admin: change another user's role ─────────────────────────────────────────

@profile_bp.route('/set-role/<int:uid>', methods=['POST'])
@require_tenant
def set_role(uid):
    if 'salesperson_id' not in session or session.get('role') != 'admin':
        flash('Admin access required.', 'error')
        return redirect(url_for('profile.profile_page'))

    new_role = request.form.get('role', '')
    if new_role not in ROLES:
        flash('Invalid role.', 'error')
        return redirect(url_for('profile.profile_page'))

    conn = get_db()
    # Ensure target user belongs to same tenant
    target = conn.execute(
        'SELECT tenant_id FROM sales_team WHERE salesperson_id = ?', (uid,)
    ).fetchone()

    if not target or target['tenant_id'] != get_current_tenant_id():
        conn.close()
        flash('User not found in your tenant.', 'error')
        return redirect(url_for('profile.profile_page'))

    conn.execute(
        'UPDATE sales_team SET role = ? WHERE salesperson_id = ?',
        (new_role, uid)
    )
    conn.commit()
    conn.close()

    # If admin changed their own role, update session
    if uid == session['salesperson_id']:
        session['role'] = new_role

    flash('Role updated successfully.', 'success')
    return redirect(url_for('profile.profile_page'))
