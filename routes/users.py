from flask import Blueprint, render_template, request, redirect, url_for, session
import sqlite3
from tenant_utils import get_db, get_current_tenant_id, require_tenant
from security import bcrypt, csrf
from flask_wtf.csrf import CSRFError

# Create a Blueprint for user management routes
users_bp = Blueprint('users', __name__)

@users_bp.errorhandler(CSRFError)
def handle_csrf_error(e):
    return render_template('sales_team/add_salesperson.html', error="CSRF token validation failed. Please try again."), 400

@users_bp.route('/salespeople/add', methods=['GET', 'POST'])
@require_tenant
def add_salesperson():
    if 'salesperson_id' in session and session.get('role') == 'admin': # Ensure only admins can access
        conn = None
        error = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # Fetch all tenants for admin users
            cursor.execute("SELECT id, name FROM tenants ORDER BY name")
            tenants = cursor.fetchall()
            
            if request.method == 'POST':
                # CSRF token is automatically validated by Flask-WTF
                username = request.form['username']
                first_name = request.form['first_name']
                last_name = request.form['last_name']
                password = request.form['password']
                salesperson_name = request.form['salesperson_name']
                work_email = request.form['work_email']
                phone_number = request.form['phone_number']
                role = request.form.get('role', 'salesperson') # Default to 'salesperson' if not provided
                tenant_id = request.form.get('tenant_id', get_current_tenant_id())  # Get tenant_id from form or current tenant

                # Use bcrypt for password hashing
                hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

                cursor.execute('''
                    INSERT INTO sales_team (username, first_name, last_name, password, salesperson_name, work_email, phone_number, role, tenant_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (username, first_name, last_name, hashed_password, salesperson_name, work_email, phone_number, role, tenant_id))

                conn.commit()
                return redirect(url_for('users.salespeople_list')) # Redirect to the list of salespeople
            return render_template('sales_team/add_salesperson.html', error=error, tenants=tenants)
        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            error = f"Database error during add_salesperson: {e}"
            print(error)
            return render_template('sales_team/add_salesperson.html', error=error, tenants=tenants)
        finally:
            if conn:
                conn.close()
    return redirect(url_for('auth.login')) # Redirect to login if not logged in or not admin

@users_bp.route('/salespeople')
@require_tenant
def salespeople_list():
    if 'salesperson_id' in session and session.get('role') == 'admin': # Ensure only admins can access
        conn = get_db()
        cursor = conn.cursor()
        salespeople = []
        try:
            cursor.execute("""
                SELECT s.salesperson_id, s.first_name, s.last_name, s.salesperson_name, 
                       s.work_email, s.phone_number, s.role, t.name as tenant_name
                FROM sales_team s
                JOIN tenants t ON s.tenant_id = t.id
            """)
            salespeople = cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Database error during salespeople_list: {e}")
        finally:
            if conn:
                conn.close()
        return render_template('sales_team/salespeople_list.html', salespeople=salespeople)
    return redirect(url_for('auth.login'))

@users_bp.route('/salespeople/<int:salesperson_id>/data')
@require_tenant
def get_salesperson_data(salesperson_id):
    if 'salesperson_id' in session and session.get('role') == 'admin':
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT salesperson_id, first_name, last_name, salesperson_name, 
                       work_email, phone_number, role 
                FROM sales_team 
                WHERE salesperson_id = ?
            """, (salesperson_id,))
            salesperson = cursor.fetchone()
            if salesperson:
                return {
                    'salesperson_id': salesperson['salesperson_id'],
                    'first_name': salesperson['first_name'],
                    'last_name': salesperson['last_name'],
                    'salesperson_name': salesperson['salesperson_name'],
                    'work_email': salesperson['work_email'],
                    'phone_number': salesperson['phone_number'],
                    'role': salesperson['role']
                }
            return {'error': 'Salesperson not found'}, 404
        except sqlite3.Error as e:
            return {'error': str(e)}, 500
        finally:
            if conn:
                conn.close()
    return {'error': 'Unauthorized'}, 401

@users_bp.route('/salespeople/edit', methods=['POST'])
@require_tenant
def edit_salesperson():
    if 'salesperson_id' in session and session.get('role') == 'admin':
        conn = get_db()
        cursor = conn.cursor()
        try:
            salesperson_id = request.form['salesperson_id']
            first_name = request.form['first_name']
            last_name = request.form['last_name']
            salesperson_name = request.form['salesperson_name']
            work_email = request.form['work_email']
            phone_number = request.form['phone_number']
            role = request.form['role']

            cursor.execute("""
                UPDATE sales_team 
                SET first_name = ?, last_name = ?, salesperson_name = ?, 
                    work_email = ?, phone_number = ?, role = ?
                WHERE salesperson_id = ?
            """, (first_name, last_name, salesperson_name, work_email, 
                  phone_number, role, salesperson_id))
            conn.commit()
            return redirect(url_for('users.salespeople_list'))
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
            return render_template('sales_team/salespeople_list.html', error="Failed to update salesperson")
        finally:
            conn.close()
    return redirect(url_for('auth.login'))

@users_bp.route('/salespeople/change-password', methods=['POST'])
@require_tenant
def change_password():
    if 'salesperson_id' in session and session.get('role') == 'admin':
        conn = get_db()
        cursor = conn.cursor()
        try:
            salesperson_id = request.form['salesperson_id']
            new_password = request.form['new_password']
            hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')

            cursor.execute("""
                UPDATE sales_team 
                SET password = ?
                WHERE salesperson_id = ?
            """, (hashed_password, salesperson_id))
            conn.commit()
            return redirect(url_for('users.salespeople_list'))
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
            return render_template('sales_team/salespeople_list.html', error="Failed to update password")
        finally:
            conn.close()
    return redirect(url_for('auth.login')) 