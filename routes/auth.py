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
        
        print(f"Login attempt - Username: {username}, Database Key: {db_key}")  # Debug log
        
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            # Get tenant by db_key
            cursor.execute("SELECT id, name FROM tenants WHERE db_key = ?", (db_key,))
            tenant = cursor.fetchone()
            
            if not tenant:
                print(f"Tenant not found for db_key: {db_key}")  # Debug log
                return render_template('auth/login.html', error="Invalid database key")
            
            print(f"Found tenant: {tenant['name']} (ID: {tenant['id']})")  # Debug log
            
            # Check sales_team table for user
            cursor.execute("""
                SELECT salesperson_id, username, first_name, role, tenant_id, password 
                FROM sales_team 
                WHERE username = ? AND tenant_id = ?
            """, (username, tenant['id']))
            
            user = cursor.fetchone()
            
            if not user:
                print(f"User {username} not found in tenant {tenant['name']} (ID: {tenant['id']})")  # Debug log
                return render_template('auth/login.html', error="Wrong username")
            
            print(f"Found user: {user['username']}, Role: {user['role']}")  # Debug log
            
            # If user exists, check password using bcrypt
            try:
                if not bcrypt.check_password_hash(user['password'], password):
                    print("Password verification failed")  # Debug log
                    return render_template('auth/login.html', error="Wrong password")
            except ValueError as e:
                print(f"Password verification error: {e}")
                print(f"Stored password hash: {user['password']}")  # Debug log
                return render_template('auth/login.html', error="Invalid password format")
            
            # Set session variables
            session['salesperson_id'] = user['salesperson_id']
            session['salesperson_name'] = user['first_name']
            session['role'] = user['role']
            session['tenant_id'] = user['tenant_id']
            
            print(f"Login successful for user {username} in tenant {tenant['name']}")  # Debug log
            
            # Redirect based on role
            if user['role'] in ['admin', 'manager']:
                return redirect(url_for('dashboard.manager_dashboard'))
            return redirect(url_for('dashboard.dashboard'))
            
        except sqlite3.Error as e:
            print(f"Database error during login: {e}")
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
        print("Received check_username request")  # Debug log
        print("Request data:", request.get_data())  # Debug log
        print("Request headers:", request.headers)  # Debug log
        
        # Skip CSRF check for this endpoint since it's a pre-login check
        data = request.get_json()
        print("Parsed JSON data:", data)  # Debug log
        
        if not data:
            print("No JSON data received")  # Debug log
            return jsonify({'error': 'No data received'}), 400
            
        username = data.get('username')
        print("Username from request:", username)  # Debug log
        
        if not username:
            print("No username provided")  # Debug log
            return jsonify({'error': 'Username is required'}), 400
            
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            print(f"Checking username: {username} across all tenants")  # Debug log
            
            # First, get all tenants
            cursor.execute('SELECT id, name, db_key FROM tenants')
            tenants = cursor.fetchall()
            print(f"Found {len(tenants)} tenants")  # Debug log
            
            # Then check each tenant for the username
            for tenant in tenants:
                print(f"Checking tenant: {tenant['name']} (ID: {tenant['id']}, db_key: {tenant['db_key']})")  # Debug log
                
                cursor.execute("""
                    SELECT salesperson_id, username, first_name, role
                    FROM sales_team 
                    WHERE username = ? AND tenant_id = ?
                """, (username, tenant['id']))
                
                user = cursor.fetchone()
                if user:
                    print(f"Found user {username} in tenant: {tenant['name']} (ID: {tenant['id']}, db_key: {tenant['db_key']})")  # Debug log
                    return jsonify({
                        'tenant': {
                            'id': tenant['id'],
                            'name': tenant['name'],
                            'db_key': tenant['db_key']
                        }
                    })
            
            print(f"User {username} not found in any tenant")  # Debug log
            return jsonify({'tenant': None})
                
        except sqlite3.Error as e:
            print(f"Database error in check_username: {str(e)}")
            print(f"Error details: {traceback.format_exc()}")
            return jsonify({'error': 'Database error occurred'}), 500
        finally:
            conn.close()
            
    except Exception as e:
        print(f"Error checking username: {str(e)}")
        print(f"Error details: {traceback.format_exc()}")
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
        print(f"Database error in check_user: {e}")
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
        print(f"Database error in check_tenant_users: {e}")
        return jsonify({
            'error': 'Database error occurred',
            'details': str(e)
        }), 500
    finally:
        if conn:
            conn.close() 