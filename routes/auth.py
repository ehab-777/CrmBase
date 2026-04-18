from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from tenant_utils import get_db, get_current_tenant_id
from dotenv import load_dotenv
import os
from security import csrf, bcrypt
import traceback

# Load environment variables
load_dotenv()

# Create a Blueprint for authentication routes
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db_key = request.form.get('db_key', 'default')

        conn = get_db()
        cursor = conn.cursor()

        try:
            # Get tenant by db_key
            cursor.execute("SELECT id, name, account_type FROM tenants WHERE db_key = ?", (db_key,))
            tenant = cursor.fetchone()

            if not tenant:
                return render_template('auth/login.html', error="Invalid database key")

            # Check sales_team table for user (by username or email)
            cursor.execute("""
                SELECT salesperson_id, username, first_name, role, tenant_id, password, preferred_lang
                FROM sales_team
                WHERE (username = ? OR work_email = ?) AND tenant_id = ?
            """, (username, username, tenant['id']))

            user = cursor.fetchone()

            if not user:
                return render_template('auth/login.html', error="Wrong username")

            # Verify password using bcrypt
            try:
                if not bcrypt.check_password_hash(user['password'], password):
                    return render_template('auth/login.html', error="Wrong password")
            except ValueError:
                return render_template('auth/login.html', error="Invalid password format")

            # Set session variables
            session['salesperson_id'] = user['salesperson_id']
            session['salesperson_name'] = user['first_name']
            session['role'] = user['role']
            session['tenant_id'] = user['tenant_id']
            session['lang'] = user['preferred_lang'] or 'en'
            session['account_type'] = tenant['account_type'] or 'company'

            # Redirect based on role
            if user['role'] in ['admin', 'manager']:
                return redirect(url_for('dashboard.manager_dashboard'))
            return redirect(url_for('dashboard.dashboard'))

        except sqlite3.Error as e:
            return render_template('auth/login.html', error="Database error occurred")
        finally:
            if conn:
                conn.close()

    return render_template('auth/login.html')

@auth_bp.route('/logout')
def logout():
    session.pop('salesperson_id', None)
    session.pop('salesperson_name', None)
    session.pop('role', None)
    session.pop('tenant_id', None)
    return redirect(url_for('auth.login'))

@auth_bp.route('/check_username', methods=['POST'])
def check_username():
    try:
        # Skip CSRF check for this endpoint since it's a pre-login check
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No data received'}), 400

        username = data.get('username')

        if not username:
            return jsonify({'error': 'Username is required'}), 400

        conn = get_db()
        cursor = conn.cursor()

        try:
            # Get all tenants and check each for the username
            cursor.execute('SELECT id, name, db_key FROM tenants')
            tenants = cursor.fetchall()

            for tenant in tenants:
                cursor.execute("""
                    SELECT salesperson_id, username, first_name, role
                    FROM sales_team 
                    WHERE username = ? AND tenant_id = ?
                """, (username, tenant['id']))

                user = cursor.fetchone()
                if user:
                    return jsonify({
                        'tenant': {
                            'id': tenant['id'],
                            'name': tenant['name'],
                            'db_key': tenant['db_key']
                        }
                    })

            return jsonify({'tenant': None})

        except sqlite3.Error as e:
            return jsonify({'error': 'Database error occurred'}), 500
        finally:
            conn.close()

    except Exception as e:
        return jsonify({'error': 'An error occurred while checking the username'}), 500

@auth_bp.route('/check_user/<username>', methods=['GET'])
def check_user(username):
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Check sales_team table
        cursor.execute("""
            SELECT s.salesperson_id, s.username, s.first_name, s.role, s.tenant_id, t.db_key
            FROM sales_team s
            JOIN tenants t ON s.tenant_id = t.id
            WHERE s.username = ?
        """, (username,))

        user = cursor.fetchone()

        if user:
            return jsonify({
                'exists': True,
                'user': {
                    'salesperson_id': user['salesperson_id'],
                    'username': user['username'],
                    'first_name': user['first_name'],
                    'role': user['role'],
                    'tenant_id': user['tenant_id'],
                    'db_key': user['db_key']
                }
            })
        else:
            return jsonify({
                'exists': False,
                'message': f'User {username} not found in sales_team table'
            })

    except sqlite3.Error as e:
        return jsonify({
            'error': 'Database error occurred',
            'details': str(e)
        }), 500
    finally:
        if conn:
            conn.close()

@auth_bp.route('/check_tenant_users/<int:tenant_id>', methods=['GET'])
def check_tenant_users(tenant_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Get tenant information
        cursor.execute("""
            SELECT id, name, db_key
            FROM tenants
            WHERE id = ?
        """, (tenant_id,))
        tenant = cursor.fetchone()

        if not tenant:
            return jsonify({
                'error': f'Tenant ID {tenant_id} not found'
            }), 404

        # Get all users in this tenant
        cursor.execute("""
            SELECT salesperson_id, username, first_name, role
            FROM sales_team
            WHERE tenant_id = ?
        """, (tenant_id,))

        users = cursor.fetchall()

        return jsonify({
            'tenant': {
                'id': tenant['id'],
                'name': tenant['name'],
                'db_key': tenant['db_key']
            },
            'users': [dict(user) for user in users]
        })

    except sqlite3.Error as e:
        return jsonify({
            'error': 'Database error occurred',
            'details': str(e)
        }), 500
    finally:
        if conn:
            conn.close()