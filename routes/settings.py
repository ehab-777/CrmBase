from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from tenant_utils import get_db, get_current_tenant_id, require_tenant

# Create a Blueprint for settings routes
settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/settings/company_profile', methods=['GET', 'POST'])
@require_tenant
def company_profile():
    tenant_id = get_current_tenant_id()
    conn = get_db()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        try:
            # Gather all fields from the form
            fields = [
                'company_name', 'company_description', 'industry', 'websites', 
                'business_units', 'core_services', 'products', 'target_audience', 
                'target_industries', 'geographic_market', 'competitors', 'usps', 
                'vision', 'mission', 'business_goals', 'strategic_priorities', 
                'current_priorities', 'things_not_to_focus_on', 'decision_rules', 
                'ai_instructions'
            ]
            
            # Prepare update query dynamically
            set_clause = ', '.join([f"{f} = ?" for f in fields])
            values = [request.form.get(f, '') for f in fields]
            
            # Ensure the row exists
            cursor.execute("SELECT id FROM company_profiles WHERE tenant_id = ?", (tenant_id,))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO company_profiles (tenant_id) VALUES (?)",
                    (tenant_id,)
                )
                
            # Update the profile
            values.append(tenant_id)
            cursor.execute(f"UPDATE company_profiles SET {set_clause} WHERE tenant_id = ?", values)
            conn.commit()
            
            return redirect(url_for('settings.company_profile', success="Profile updated successfully"))
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
        finally:
            conn.close()
            
    # GET request
    try:
        cursor.execute("SELECT * FROM company_profiles WHERE tenant_id = ?", (tenant_id,))
        profile = cursor.fetchone()
        
        # If no profile exists, create a default empty one
        if not profile:
            cursor.execute("INSERT INTO company_profiles (tenant_id, company_name) VALUES (?, ?)", (tenant_id, ''))
            conn.commit()
            cursor.execute("SELECT * FROM company_profiles WHERE tenant_id = ?", (tenant_id,))
            profile = cursor.fetchone()
            
        # Convert sqlite3.Row to dict
        profile_dict = dict(profile) if profile else {}
        
        return render_template('settings/company_profile.html', profile=profile_dict, success=request.args.get('success'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return render_template('settings/company_profile.html', profile={}, error="Failed to load profile")
    finally:
        conn.close()


@settings_bp.route('/settings/tenants', methods=['GET', 'POST'])
@require_tenant
def manage_tenants():
    from flask import abort
    abort(403)
    if 'salesperson_id' in session and session.get('role') == 'admin':
        conn = get_db()
        cursor = conn.cursor()
        
        if request.method == 'POST':
            try:
                tenant_id = request.form.get('tenant_id')
                name = request.form['name']
                db_key = request.form['db_key']
                account_type = request.form.get('account_type', 'company')
                if account_type not in ('individual', 'company'):
                    account_type = 'company'

                if tenant_id:  # Update existing tenant
                    cursor.execute("""
                        UPDATE tenants
                        SET name = ?, db_key = ?, account_type = ?
                        WHERE id = ?
                    """, (name, db_key, account_type, tenant_id))
                else:  # Create new tenant
                    cursor.execute("""
                        INSERT INTO tenants (name, db_key, account_type)
                        VALUES (?, ?, ?)
                    """, (name, db_key, account_type))
                
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
            cursor.execute("SELECT id, name, db_key, account_type FROM tenants")
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


@settings_bp.route('/settings/tracks', methods=['GET', 'POST'])
@require_tenant
def manage_tracks():
    if 'salesperson_id' not in session or session.get('role') not in ['admin', 'manager']:
        return redirect(url_for('auth.login'))
        
    tenant_id = get_current_tenant_id()
    conn = get_db()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        action = request.form.get('action')
        track_id = request.form.get('track_id')
        name = request.form.get('name')
        
        try:
            if action == 'add' and name:
                cursor.execute("INSERT INTO business_tracks (name, tenant_id, is_active) VALUES (?, ?, 1)", (name, tenant_id))
            elif action == 'edit' and track_id and name:
                cursor.execute("UPDATE business_tracks SET name = ? WHERE id = ? AND tenant_id = ?", (name, track_id, tenant_id))
            elif action == 'toggle' and track_id:
                cursor.execute("UPDATE business_tracks SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ? AND tenant_id = ?", (track_id, tenant_id))
            conn.commit()
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            
        return redirect(url_for('settings.manage_tracks'))
        
    # GET request
    try:
        # Get all tracks
        cursor.execute("SELECT * FROM business_tracks WHERE tenant_id = ?", (tenant_id,))
        tracks = [dict(row) for row in cursor.fetchall()]
        
        # Get all subcategories
        cursor.execute("SELECT * FROM business_subcategories WHERE tenant_id = ?", (tenant_id,))
        all_subs = [dict(row) for row in cursor.fetchall()]
        
        # Group subcategories by track_id
        for track in tracks:
            track['subcategories'] = [sub for sub in all_subs if sub['track_id'] == track['id']]
            
        return render_template('settings/tracks.html', tracks=tracks)
    finally:
        conn.close()

@settings_bp.route('/settings/departments', methods=['GET', 'POST'])
@require_tenant
def manage_departments():
    if 'salesperson_id' not in session or session.get('role') not in ['admin', 'manager']:
        return redirect(url_for('auth.login'))
        
    tenant_id = get_current_tenant_id()
    conn = get_db()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        action = request.form.get('action')
        dept_id = request.form.get('dept_id')
        name = request.form.get('name')
        
        try:
            if action == 'add' and name:
                cursor.execute("INSERT INTO departments (name, tenant_id, is_active) VALUES (?, ?, 1)", (name, tenant_id))
            elif action == 'edit' and dept_id and name:
                cursor.execute("UPDATE departments SET name = ? WHERE id = ? AND tenant_id = ?", (name, dept_id, tenant_id))
            elif action == 'toggle' and dept_id:
                cursor.execute("UPDATE departments SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ? AND tenant_id = ?", (dept_id, tenant_id))
            conn.commit()
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            
        return redirect(url_for('settings.manage_departments'))
        
    # GET request
    try:
        cursor.execute("SELECT * FROM departments WHERE tenant_id = ?", (tenant_id,))
        departments = [dict(row) for row in cursor.fetchall()]
        return render_template('settings/departments.html', departments=departments)
    finally:
        conn.close()


@settings_bp.route('/settings/subcategories', methods=['POST'])
@require_tenant
def manage_subcategories():
    if 'salesperson_id' not in session or session.get('role') not in ['admin', 'manager']:
        return redirect(url_for('auth.login'))
        
    tenant_id = get_current_tenant_id()
    conn = get_db()
    cursor = conn.cursor()
    
    action = request.form.get('action')
    sub_id = request.form.get('sub_id')
    track_id = request.form.get('track_id')
    name = request.form.get('name')
    
    try:
        if action == 'add' and track_id and name:
            cursor.execute("INSERT INTO business_subcategories (track_id, name, tenant_id, is_active) VALUES (?, ?, ?, 1)", (track_id, name, tenant_id))
        elif action == 'edit' and sub_id and name:
            cursor.execute("UPDATE business_subcategories SET name = ? WHERE id = ? AND tenant_id = ?", (name, sub_id, tenant_id))
        elif action == 'toggle' and sub_id:
            cursor.execute("UPDATE business_subcategories SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ? AND tenant_id = ?", (sub_id, tenant_id))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('settings.manage_tracks'))