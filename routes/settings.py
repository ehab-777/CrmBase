from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from tenant_utils import get_db, get_current_tenant_id, require_tenant

# Create a Blueprint for settings routes
settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/settings/tenants', methods=['GET', 'POST'])
@require_tenant
def manage_tenants():
    if 'salesperson_id' in session and session.get('role') == 'admin':
        conn = get_db()
        cursor = conn.cursor()
        
        if request.method == 'POST':
            try:
                tenant_id = request.form.get('tenant_id')
                name = request.form['name']
                db_key = request.form['db_key']
                
                if tenant_id:  # Update existing tenant
                    cursor.execute("""
                        UPDATE tenants 
                        SET name = ?, db_key = ?
                        WHERE id = ?
                    """, (name, db_key, tenant_id))
                else:  # Create new tenant
                    cursor.execute("""
                        INSERT INTO tenants (name, db_key)
                        VALUES (?, ?)
                    """, (name, db_key))
                
                conn.commit()
                return redirect(url_for('settings.manage_tenants'))
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                conn.rollback()
                return render_template('tenants/manage_tenants.html', error="Failed to update tenant")
            finally:
                conn.close()
        
        # GET request - show tenants list
        try:
            cursor.execute("SELECT id, name, db_key FROM tenants")
            tenants = cursor.fetchall()
            return render_template('tenants/manage_tenants.html', tenants=tenants)
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return render_template('tenants/manage_tenants.html', error="Failed to fetch tenants")
        finally:
            conn.close()
    
    return redirect(url_for('auth.login'))

@settings_bp.route('/settings/tenants/delete/<int:tenant_id>', methods=['POST'])
@require_tenant
def delete_tenant(tenant_id):
    if 'salesperson_id' in session and session.get('role') == 'admin':
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            # First check if there are any users in this tenant
            cursor.execute("SELECT COUNT(*) FROM sales_team WHERE tenant_id = ?", (tenant_id,))
            user_count = cursor.fetchone()[0]
            
            if user_count > 0:
                return jsonify({
                    'success': False,
                    'message': 'Cannot delete tenant with existing users'
                }), 400
            
            # Delete the tenant
            cursor.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
            conn.commit()
            
            return jsonify({
                'success': True,
                'message': 'Tenant deleted successfully'
            })
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
            return jsonify({
                'success': False,
                'message': 'Failed to delete tenant'
            }), 500
        finally:
            conn.close()
    
    return redirect(url_for('auth.login')) 