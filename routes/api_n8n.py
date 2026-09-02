import os
import sqlite3
from flask import Blueprint, request, jsonify, current_app
from tenant_utils import get_db

api_n8n_bp = Blueprint('api_n8n', __name__)

def require_n8n_auth():
    """Middleware to check X-N8N-API-KEY header."""
    auth_header = request.headers.get('X-N8N-API-KEY')
    expected_key = os.environ.get('N8N_API_KEY')
    
    if not expected_key:
        return False, jsonify({"error": "N8N_API_KEY not configured on server."}), 500
        
    if not auth_header or auth_header != expected_key:
        return False, jsonify({"error": "Unauthorized. Invalid API Key."}), 401
        
    return True, None, None

@api_n8n_bp.before_request
def before_request():
    # Only authenticate routes in this blueprint
    is_valid, err_resp, status_code = require_n8n_auth()
    if not is_valid:
        return err_resp, status_code

# ── Tasks API ────────────────────────────────────────────────────────────────

@api_n8n_bp.route('/tasks', methods=['POST'])
def add_task():
    """
    Creates a new Kanban task.
    Required JSON: title, tenant_id, salesperson_id
    Optional JSON: description, status (default: pending), due_date, subcategory_id
    """
    data = request.json or {}
    
    title = data.get('title')
    tenant_id = data.get('tenant_id', 1)
    salesperson_id = data.get('salesperson_id', 1)
    
    if not title:
        return jsonify({"error": "Missing required field: title"}), 400
        
    description = data.get('description', '')
    status = data.get('status', 'pending')
    due_date = data.get('due_date')
    subcategory_id = data.get('subcategory_id')
    department_id = data.get('department_id')
    
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tasks (title, description, status, due_date, subcategory_id, department_id, assigned_to, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, description, status, due_date, subcategory_id, department_id, salesperson_id, tenant_id))
        conn.commit()
        return jsonify({"success": True, "task_id": cursor.lastrowid}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@api_n8n_bp.route('/tasks', methods=['GET'])
def list_tasks():
    """
    Lists tasks for a specific salesperson. Useful for daily briefings.
    Query Params: tenant_id, salesperson_id, status
    """
    tenant_id = request.args.get('tenant_id', 1)
    salesperson_id = request.args.get('salesperson_id', 1)
    status = request.args.get('status')
    
    query = """
        SELECT t.id, t.title, t.description, t.status, t.due_date, s.name as subcategory_name, tr.name as track_name
        FROM tasks t
        LEFT JOIN business_subcategories s ON t.subcategory_id = s.id
        LEFT JOIN business_tracks tr ON s.track_id = tr.id
        WHERE t.tenant_id = ? AND t.assigned_to = ?
    """
    params = [tenant_id, salesperson_id]
    
    if status:
        query += " AND t.status = ?"
        params.append(status)
        
    query += " ORDER BY t.due_date ASC"
    
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        tasks = [dict(row) for row in cursor.fetchall()]
        return jsonify({"success": True, "tasks": tasks}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# ── Customers API ─────────────────────────────────────────────────────────────

@api_n8n_bp.route('/customers', methods=['POST'])
def add_customer():
    """
    Creates a new customer/lead.
    Required JSON: name, tenant_id, salesperson_id
    Optional JSON: phone, email, current_stage, subcategory_id, details
    """
    data = request.json or {}
    
    name = data.get('name')
    tenant_id = data.get('tenant_id', 1)
    salesperson_id = data.get('salesperson_id', 1)
    
    if not name:
        return jsonify({"error": "Missing required field: name"}), 400
        
    phone = data.get('phone', '')
    email = data.get('email', '')
    stage = data.get('current_stage', 'lead')
    subcategory_id = data.get('subcategory_id')
    details = data.get('details', '')
    
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO customers (company_name, contact_person, phone_number, email_address, current_stage, subcategory_id, assigned_salesperson_id, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, name, phone, email, stage, subcategory_id, salesperson_id, tenant_id))
        
        customer_id = cursor.lastrowid
        
        # Add initial activity note if details provided
        if details:
            cursor.execute("""
                INSERT INTO activities (tenant_id, entity_type, entity_id, action, actor_name, details, created_by)
                VALUES (?, 'customer', ?, 'note', 'n8n AI', ?, ?)
            """, (tenant_id, customer_id, details, salesperson_id))
            
        conn.commit()
        return jsonify({"success": True, "customer_id": customer_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@api_n8n_bp.route('/customers', methods=['GET'])
def list_customers():
    """
    Lists customers/leads.
    Query Params: tenant_id, salesperson_id, search
    """
    tenant_id = request.args.get('tenant_id', 1)
    salesperson_id = request.args.get('salesperson_id', 1)
    search = request.args.get('search', '')
    
    query = """
        SELECT c.customer_id, c.company_name as name, c.phone_number as phone, c.current_stage, s.name as subcategory_name
        FROM customers c
        LEFT JOIN business_subcategories s ON c.subcategory_id = s.id
        WHERE c.tenant_id = ? AND c.assigned_salesperson_id = ?
    """
    params = [tenant_id, salesperson_id]
    
    if search:
        query += " AND (c.company_name LIKE ? OR c.contact_person LIKE ? OR c.phone_number LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        customers = [dict(row) for row in cursor.fetchall()]
        return jsonify({"success": True, "customers": customers}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# ── Tracks & Subcategories API (Helper for AI to know what tracks exist) ──────

@api_n8n_bp.route('/tracks', methods=['GET'])
def list_tracks():
    """
    Lists all active business tracks and subcategories so the AI knows the IDs.
    """
    tenant_id = request.args.get('tenant_id', 1)
    
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name FROM business_tracks WHERE tenant_id = ? AND is_active = 1
        """, (tenant_id,))
        tracks = [dict(row) for row in cursor.fetchall()]
        
        for track in tracks:
            cursor.execute("""
                SELECT id, name FROM business_subcategories WHERE track_id = ? AND tenant_id = ? AND is_active = 1
            """, (track['id'], tenant_id))
            track['subcategories'] = [dict(row) for row in cursor.fetchall()]
            
        return jsonify({"success": True, "tracks": tracks}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# ── Universal Search API (The "Eyes" of the AI OS) ────────────────────────────

@api_n8n_bp.route('/search', methods=['GET'])
def universal_search():
    """
    A single powerful endpoint for the AI to understand the current state of the CRM.
    If 'q' is provided, it searches tasks and customers for that query.
    If 'q' is empty, it returns a general snapshot (recent tasks, recent customers, all tracks).
    """
    tenant_id = request.args.get('tenant_id', 1)
    salesperson_id = request.args.get('salesperson_id', 1)
    search_query = request.args.get('q', '').strip()
    
    conn = get_db()
    try:
        cursor = conn.cursor()
        
        # 1. Fetch Tracks Taxonomy (always useful for AI context)
        cursor.execute("SELECT id, name FROM business_tracks WHERE tenant_id = ? AND is_active = 1", (tenant_id,))
        tracks = [dict(row) for row in cursor.fetchall()]
        for track in tracks:
            cursor.execute("SELECT id, name FROM business_subcategories WHERE track_id = ? AND is_active = 1", (track['id'],))
            track['subcategories'] = [dict(row) for row in cursor.fetchall()]
            
        # 1b. Fetch Departments Taxonomy
        cursor.execute("SELECT id, name FROM departments WHERE tenant_id = ? AND is_active = 1", (tenant_id,))
        departments = [dict(row) for row in cursor.fetchall()]
            
        # 2. Fetch Tasks
        task_sql = """
            SELECT t.id, t.title, t.description, t.status, t.due_date, s.name as subcategory_name, d.name as department_name
            FROM tasks t 
            LEFT JOIN business_subcategories s ON t.subcategory_id = s.id 
            LEFT JOIN departments d ON t.department_id = d.id
            WHERE t.tenant_id = ? AND t.assigned_to = ?
        """
        task_params = [tenant_id, salesperson_id]
        
        if search_query:
            task_sql += " AND (t.title LIKE ? OR t.description LIKE ?)"
            task_params.extend([f"%{search_query}%", f"%{search_query}%"])
        else:
            # If no query, just get active or recent tasks
            task_sql += " AND t.status != 'completed' ORDER BY t.created_at DESC LIMIT 10"
            
        cursor.execute(task_sql, task_params)
        tasks = [dict(row) for row in cursor.fetchall()]
        
        # 3. Fetch Customers
        customer_sql = """
            SELECT c.customer_id, c.company_name, c.contact_person, c.phone_number, c.current_stage 
            FROM customers c 
            WHERE c.tenant_id = ? AND c.assigned_salesperson_id = ?
        """
        customer_params = [tenant_id, salesperson_id]
        
        if search_query:
            customer_sql += " AND (c.company_name LIKE ? OR c.contact_person LIKE ? OR c.phone_number LIKE ?)"
            customer_params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])
        else:
            customer_sql += " ORDER BY c.date_added DESC LIMIT 10"
            
        cursor.execute(customer_sql, customer_params)
        customers = [dict(row) for row in cursor.fetchall()]
        
        # 4. Dynamic Company Profile (The Brain's Core Knowledge)
        cursor.execute("SELECT * FROM company_profiles WHERE tenant_id = ?", (tenant_id,))
        profile_row = cursor.fetchone()
        
        company_profile = {}
        if profile_row:
            company_profile = dict(profile_row)
            # Remove internal DB IDs to keep context clean for AI
            company_profile.pop('id', None)
            company_profile.pop('tenant_id', None)
            company_profile.pop('updated_at', None)
        else:
            company_profile = {"info": "لم يتم إعداد ملف الشركة بعد. يرجى إعداده من لوحة التحكم."}
        
        return jsonify({
            "success": True,
            "data": {
                "company_profile": company_profile,
                "tracks_taxonomy": tracks,
                "departments_taxonomy": departments,
                "tasks": tasks,
                "customers": customers,
                "context": "Search results" if search_query else "General CRM Snapshot"
            }
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
