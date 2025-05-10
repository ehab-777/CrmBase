from flask import Blueprint, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime
from tenant_utils import get_db, get_current_tenant_id, require_tenant

# Create a Blueprint for follow-up routes
follow_up_bp = Blueprint('follow_up', __name__)

@follow_up_bp.route('/customers/<int:customer_id>/followup/add', methods=['GET', 'POST'])
@require_tenant
def add_followup(customer_id):
    if 'salesperson_id' in session:
        conn = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # First verify the customer exists
            cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,))
            customer = cursor.fetchone()
            if not customer:
                return redirect(url_for('customers.customer_list'))
                
            if request.method == 'POST':
                last_contact_date = request.form['last_contact_date']
                last_contact_method = request.form.get('last_contact_method')
                summary_last_contact = request.form.get('summary')
                next_action = request.form.get('next_action')
                next_action_due_date = request.form.get('next_action_date')
                current_sales_stage = request.form.get('current_sales_stage')
                potential_deal_value = request.form.get('deal_value')
                notes = request.form.get('summary', '')  # Use summary as notes if no separate notes field
                assigned_salesperson_id = session['salesperson_id']
                tenant_id = get_current_tenant_id()

                cursor.execute('''
                    INSERT INTO sales_followup (
                        customer_id, assigned_salesperson_id, last_contact_date,
                        last_contact_method, summary_last_contact, next_action,
                        next_action_due_date, current_sales_stage, potential_deal_value,
                        notes, tenant_id, created_at, created_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'), ?)
                ''', (
                    customer_id, assigned_salesperson_id, last_contact_date,
                    last_contact_method, summary_last_contact, next_action,
                    next_action_due_date, current_sales_stage, potential_deal_value,
                    notes, tenant_id, session['salesperson_id']
                ))
                conn.commit()
                return redirect(url_for('customers.customer_detail', customer_id=customer_id))
                    
            return render_template('customers/add_followup.html', customer=customer)
            
        except Exception as e:
            print(f"Error: {e}")
            return redirect(url_for('customers.customer_list'))
        finally:
            if conn:
                conn.close()
    return redirect(url_for('auth.login')) 