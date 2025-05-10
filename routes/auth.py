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
            cursor.execute("SELECT id FROM tenants WHERE db_key = ?", (db_key,))
            tenant = cursor.fetchone()
            
            if not tenant:
                print(f"Tenant not found for db_key: {db_key}")  # Debug log
                return render_template('auth/login.html', error="Invalid database key")
            
            print(f"Found tenant ID: {tenant[0]}")  # Debug log
            
            # Check if user exists in any tenant with the given username
            cursor.execute("""
                SELECT salesperson_id, username, first_name, role, tenant_id, password 
                FROM sales_team 
                WHERE username = ?
            """, (username,))
            
            user = cursor.fetchone()
            
            if not user:
                print(f"User not found: {username}")  # Debug log
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
            
            # If we get here, credentials are correct
            session['salesperson_id'] = user['salesperson_id']
            session['salesperson_name'] = user['first_name']  # Still use first_name for display
            session['role'] = user['role']
            session['tenant_id'] = user['tenant_id']
            
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
        data = request.get_json()
        username = data.get('username')
        
        if not username:
            return jsonify({'error': 'Username is required'}), 400
            
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            # Query to get tenant information for the username
            cursor.execute('''
                SELECT t.id, t.name, t.db_key 
                FROM tenants t
                JOIN sales_team st ON t.id = st.tenant_id
                WHERE st.username = ?
            ''', (username,))
            
            tenant = cursor.fetchone()
            
            if tenant:
                return jsonify({
                    'tenant': {
                        'id': tenant[0],
                        'name': tenant[1],
                        'db_key': tenant[2]
                    }
                })
            else:
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