from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from tenant_utils import get_db, get_current_tenant_id
from app import bcrypt

# Create a Blueprint for sales team routes
sales_team_bp = Blueprint('sales_team', __name__)

@sales_team_bp.route('/salespeople/add', methods=['GET', 'POST'])
def add_salesperson():
    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email']
        phone = request.form['phone']
        role = request.form['role']
        password = request.form['password']
        tenant_id = get_current_tenant_id()
        
        # Hash the password using bcrypt
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO sales_team (first_name, last_name, email, phone, role, password, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (first_name, last_name, email, phone, role, hashed_password, tenant_id))
            
            conn.commit()
            conn.close()
            return redirect(url_for('sales_team.salespeople_list'))
            
        except sqlite3.Error as e:
            conn.close()
            return render_template('sales_team/add_salesperson.html', error=str(e))
    
    return render_template('sales_team/add_salesperson.html')

# ... rest of the file ... 