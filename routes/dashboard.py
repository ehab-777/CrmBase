from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from tenant_utils import get_db, get_current_tenant_id, require_tenant
from datetime import datetime

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='')

_ACTIVE_STAGES = ('عميل محتمل', 'تقديم عرض السعر', 'جاري التواصل', 'جاري التفاوض')

# ── helpers ──────────────────────────────────────────────────────────────────

def _lfu(field):
    """Raw scalar subquery — latest follow_up activity field for the current customer row c."""
    return f"""(SELECT a.{field} FROM activities a
             WHERE a.entity_type='customer' AND a.entity_id=c.customer_id
               AND a.action='follow_up' AND a.tenant_id=c.tenant_id
             ORDER BY a.created_at DESC, a.id DESC LIMIT 1)"""


# ── salesperson dashboard ────────────────────────────────────────────────────

@dashboard_bp.route('/dashboard')
@require_tenant
def dashboard():
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    salesperson_id = session['salesperson_id']
    tenant_id      = get_current_tenant_id()
    conn = get_db()
    cursor = conn.cursor()

    # Total customers
    cursor.execute(
        "SELECT COUNT(*) FROM customers WHERE assigned_salesperson_id = ? AND tenant_id = ?",
        (salesperson_id, tenant_id)
    )
    total_customers = cursor.fetchone()[0]

    # Status counts + pipeline value
    active_in = ','.join('?' * len(_ACTIVE_STAGES))
    cursor.execute(f"""
        SELECT
            COUNT(DISTINCT CASE WHEN COALESCE(c.current_stage,'عميل محتمل') IN ({active_in})
                                THEN c.customer_id END) AS active_count,
            COUNT(DISTINCT CASE WHEN c.current_stage='تم التسليم'   THEN c.customer_id END) AS won_count,
            COUNT(DISTINCT CASE WHEN c.current_stage='لم يتم البيع' THEN c.customer_id END) AS lost_count,
            COALESCE(SUM(CASE WHEN COALESCE(c.current_stage,'عميل محتمل') IN ({active_in})
                THEN COALESCE({_lfu('deal_value')}, 0) ELSE 0 END), 0) AS active_value,
            COALESCE(SUM(CASE WHEN c.current_stage='تم التسليم'
                THEN COALESCE({_lfu('deal_value')}, 0) ELSE 0 END), 0) AS won_value,
            COALESCE(SUM(CASE WHEN c.current_stage='لم يتم البيع'
                THEN COALESCE({_lfu('deal_value')}, 0) ELSE 0 END), 0) AS lost_value
        FROM customers c
        WHERE c.assigned_salesperson_id = ? AND c.tenant_id = ?
    """, list(_ACTIVE_STAGES) * 2 + [salesperson_id, tenant_id])
    metrics = cursor.fetchone()
    status_counts = {
        'Active':     {'count': metrics['active_count'], 'value': metrics['active_value']},
        'Close Won':  {'count': metrics['won_count'],    'value': metrics['won_value']},
        'Close Lost': {'count': metrics['lost_count'],   'value': metrics['lost_value']},
    }
    total_potential_value = metrics['active_value']

    # Open leads — active stage customers sorted by deal value
    cursor.execute(f"""
        SELECT c.customer_id, c.company_name,
               COALESCE({_lfu('deal_value')}, 0) AS deal_value
        FROM customers c
        WHERE c.assigned_salesperson_id = ? AND c.tenant_id = ?
          AND COALESCE(c.current_stage,'عميل محتمل') IN ({active_in})
        ORDER BY deal_value DESC, c.company_name
    """, [salesperson_id, tenant_id] + list(_ACTIVE_STAGES))
    open_leads = cursor.fetchall()

    # Sales pipeline
    cursor.execute(f"""
        SELECT
            COALESCE(c.current_stage,'عميل محتمل') AS current_sales_stage,
            c.customer_id,
            c.company_name AS company,
            {_lfu('contact_date')} AS last_contact_date,
            {_lfu('summary')}      AS summary,
            {_lfu('deal_value')}   AS deal_value
        FROM customers c
        WHERE c.assigned_salesperson_id = ? AND c.tenant_id = ?
        ORDER BY
            CASE COALESCE(c.current_stage,'عميل محتمل')
                WHEN 'عميل محتمل'        THEN 1
                WHEN 'تقديم عرض السعر'   THEN 2
                WHEN 'جاري التواصل'      THEN 3
                WHEN 'جاري التفاوض'      THEN 4
                WHEN 'تم التسليم'        THEN 5
                WHEN 'لم يتم البيع'      THEN 6
                ELSE 7
            END, c.company_name
    """, (salesperson_id, tenant_id))
    sales_pipeline = {}
    for row in cursor.fetchall():
        stage = row['current_sales_stage']
        if stage not in sales_pipeline:
            sales_pipeline[stage] = []
        sales_pipeline[stage].append({
            'customer_id':       row['customer_id'],
            'company':           row['company'],
            'last_contact_date': row['last_contact_date'],
            'summary':           row['summary'],
            'deal_value':        row['deal_value'],
        })

    # Recent follow-ups
    cursor.execute("""
        SELECT a.entity_id AS customer_id, c.company_name,
               a.contact_date     AS last_contact_date,
               a.activity_type    AS last_contact_method,
               a.summary          AS summary_last_contact
        FROM activities a
        JOIN customers c ON a.entity_id = c.customer_id AND a.tenant_id = c.tenant_id
        WHERE a.action = 'follow_up' AND a.entity_type = 'customer'
          AND a.tenant_id = ?
          AND c.assigned_salesperson_id = ?
        ORDER BY a.contact_date DESC
        LIMIT 5
    """, (tenant_id, salesperson_id))
    recent_followups = cursor.fetchall()

    # Upcoming follow-ups
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute(f"""
        SELECT
            a.entity_id          AS customer_id,
            c.company_name,
            a.next_action,
            a.next_action_due    AS next_action_due_date,
            a.summary            AS summary_last_contact,
            a.deal_value         AS potential_deal_value,
            a.id                 AS activity_id,
            CASE
                WHEN date(a.next_action_due) = date(?)
                    THEN 'today'
                WHEN date(a.next_action_due) BETWEEN date(?,'+1 day') AND date(?,'+7 days')
                    THEN 'this_week'
                WHEN date(a.next_action_due) BETWEEN date(?,'+8 days') AND date(?,'+14 days')
                    THEN 'next_week'
                ELSE 'later'
            END AS time_period
        FROM activities a
        JOIN customers c ON a.entity_id = c.customer_id AND c.tenant_id = a.tenant_id
        WHERE a.action = 'follow_up' AND a.entity_type = 'customer'
          AND a.tenant_id = ?
          AND c.assigned_salesperson_id = ?
          AND a.next_action_due IS NOT NULL
          AND date(a.next_action_due) >= date(?)
          AND COALESCE(c.current_stage,'عميل محتمل') NOT IN ('تم التسليم','لم يتم البيع')
          AND COALESCE(a.next_action_done, 0) = 0
        ORDER BY a.next_action_due ASC
    """, (today, today, today, today, today, tenant_id, salesperson_id, today))
    followups = cursor.fetchall()

    conn.close()
    return render_template('dashboard/dashboard.html',
                           total_customers=total_customers,
                           status_counts=status_counts,
                           total_potential_value=total_potential_value,
                           open_leads=open_leads,
                           sales_pipeline=sales_pipeline,
                           recent_followups=recent_followups,
                           followups_today    =[f for f in followups if f['time_period'] == 'today'],
                           followups_this_week=[f for f in followups if f['time_period'] == 'this_week'],
                           followups_next_week=[f for f in followups if f['time_period'] == 'next_week'],
                           followups_later    =[f for f in followups if f['time_period'] == 'later'],
                           salesperson_name=session.get('salesperson_name', 'User'))


# ── manager dashboard ────────────────────────────────────────────────────────

@dashboard_bp.route('/manager/dashboard')
@require_tenant
def manager_dashboard():
    try:
        if 'salesperson_id' not in session or session.get('role') not in ['admin', 'manager']:
            return redirect(url_for('auth.login'))

        try:
            page     = max(1, int(request.args.get('page', 1)))
            per_page = 4
        except ValueError:
            page = 1; per_page = 4

        salesperson_id = request.args.get('salesperson_id')
        if salesperson_id:
            try:
                salesperson_id = int(salesperson_id)
            except ValueError:
                salesperson_id = None

        stage      = request.args.get('stage', '')
        search     = request.args.get('search', '').strip()
        tenant_id  = get_current_tenant_id()
        conn       = get_db()
        cursor     = conn.cursor()

        # Salespeople dropdown
        cursor.execute(
            "SELECT salesperson_id, first_name FROM sales_team WHERE tenant_id = ? ORDER BY first_name",
            (tenant_id,)
        )
        salespeople = cursor.fetchall()

        # Stage dropdown
        cursor.execute("""
            SELECT DISTINCT current_stage AS current_sales_stage
            FROM customers
            WHERE tenant_id = ? AND current_stage IS NOT NULL
            ORDER BY current_stage
        """, (tenant_id,))
        sales_stages = [row['current_sales_stage'] for row in cursor.fetchall()]

        # Customer list query
        base_query = f"""
            SELECT c.*, st.first_name AS assigned_salesperson,
                COALESCE(c.current_stage,'عميل محتمل') AS current_sales_stage,
                (SELECT a.next_action_due FROM activities a
                 WHERE a.entity_type='customer' AND a.entity_id=c.customer_id
                   AND a.action='follow_up' AND a.tenant_id=c.tenant_id
                   AND a.next_action_due IS NOT NULL AND COALESCE(a.next_action_done,0)=0
                 ORDER BY a.next_action_due ASC LIMIT 1) AS next_followup_date,
                {_lfu('contact_date')} AS last_contact_date
            FROM customers c
            LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
            WHERE c.tenant_id = ?
        """
        where_clause = []
        params = [tenant_id]

        if salesperson_id:
            where_clause.append("c.assigned_salesperson_id = ?")
            params.append(salesperson_id)

        if stage:
            where_clause.append("COALESCE(c.current_stage,'عميل محتمل') = ?")
            params.append(stage)

        if search:
            search_term = f"%{search.lower()}%"
            where_clause.append("""
                (LOWER(c.company_name) LIKE ? OR LOWER(c.contact_person) LIKE ? OR
                 LOWER(c.phone_number) LIKE ? OR LOWER(st.first_name) LIKE ? OR
                 LOWER(COALESCE(c.current_stage,'')) LIKE ?)
            """)
            params.extend([search_term] * 5)

        if where_clause:
            base_query += " AND " + " AND ".join(where_clause)

        base_query += " ORDER BY c.date_added DESC LIMIT ? OFFSET ?"
        params.extend([per_page, (page - 1) * per_page])

        count_query = """
            SELECT COUNT(*) FROM customers c
            LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
            WHERE c.tenant_id = ?
        """
        if where_clause:
            count_query += " AND " + " AND ".join(where_clause)

        cursor.execute(count_query, params[:-2])
        total_customers = cursor.fetchone()[0]
        total_pages = (total_customers + per_page - 1) // per_page

        cursor.execute(base_query, params)
        customers = cursor.fetchall()

        # Sales stage counts
        sales_stage_query = f"""
            SELECT
                COALESCE(c.current_stage,'عميل محتمل') AS current_sales_stage,
                COUNT(*) AS count,
                COALESCE(SUM(COALESCE({_lfu('deal_value')}, 0)), 0) AS total_value
            FROM customers c
            LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
            WHERE c.tenant_id = ?
        """
        stage_params = [tenant_id]
        if salesperson_id:
            sales_stage_query += " AND c.assigned_salesperson_id = ?"
            stage_params.append(salesperson_id)
        if stage:
            sales_stage_query += " AND COALESCE(c.current_stage,'عميل محتمل') = ?"
            stage_params.append(stage)
        if search:
            search_term = f"%{search.lower()}%"
            sales_stage_query += """
                AND (LOWER(c.company_name) LIKE ? OR LOWER(c.contact_person) LIKE ? OR
                     LOWER(c.phone_number) LIKE ? OR LOWER(st.first_name) LIKE ?)
            """
            stage_params.extend([search_term] * 4)
        sales_stage_query += " GROUP BY COALESCE(c.current_stage,'عميل محتمل')"

        cursor.execute(sales_stage_query, stage_params)
        sales_stage_counts = {}
        for row in cursor.fetchall():
            sales_stage_counts[row['current_sales_stage']] = {
                'count':       int(row['count']),
                'total_value': float(row['total_value'] or 0),
            }
        for s in sales_stage_counts:
            pct = (sales_stage_counts[s]['count'] / total_customers * 100) if total_customers else 0
            sales_stage_counts[s]['percentage'] = f"{pct:.1f}%"

        # Pipeline query
        pipeline_query = f"""
            SELECT
                COALESCE(c.current_stage,'عميل محتمل') AS current_sales_stage,
                c.customer_id, c.company_name AS company,
                c.contact_person, c.phone_number,
                st.first_name AS salesperson_name,
                (SELECT a.next_action FROM activities a
                 WHERE a.entity_type='customer' AND a.entity_id=c.customer_id
                   AND a.action='follow_up' AND a.tenant_id=c.tenant_id
                 ORDER BY a.created_at DESC, a.id DESC LIMIT 1) AS next_action,
                (SELECT a.next_action_due FROM activities a
                 WHERE a.entity_type='customer' AND a.entity_id=c.customer_id
                   AND a.action='follow_up' AND a.tenant_id=c.tenant_id
                 ORDER BY a.created_at DESC, a.id DESC LIMIT 1) AS next_action_due_date,
                {_lfu('contact_date')} AS last_contact_date,
                {_lfu('summary')}      AS summary_last_contact,
                COALESCE({_lfu('deal_value')}, 0) AS potential_deal_value,
                (SELECT COUNT(*) FROM activities a
                 WHERE a.entity_type='customer' AND a.entity_id=c.customer_id
                   AND a.action='follow_up' AND a.tenant_id=c.tenant_id) AS followup_count
            FROM customers c
            LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
            WHERE c.tenant_id = ?
        """
        pipe_params  = [tenant_id]
        pipe_clauses = []

        if salesperson_id:
            pipe_clauses.append("c.assigned_salesperson_id = ?")
            pipe_params.append(salesperson_id)
        if search:
            search_term = f"%{search.lower()}%"
            pipe_clauses.append("""
                (LOWER(c.company_name) LIKE ? OR LOWER(c.contact_person) LIKE ? OR
                 LOWER(c.phone_number) LIKE ? OR LOWER(st.first_name) LIKE ? OR
                 LOWER(COALESCE(c.current_stage,'')) LIKE ?)
            """)
            pipe_params.extend([search_term] * 5)
        if pipe_clauses:
            pipeline_query += " AND " + " AND ".join(pipe_clauses)
        pipeline_query += " ORDER BY COALESCE(c.current_stage,'عميل محتمل'), c.company_name"

        cursor.execute(pipeline_query, pipe_params)
        pipeline_by_stage = {}
        for row in cursor.fetchall():
            row_stage  = row['current_sales_stage']
            deal_value = float(row['potential_deal_value']) if row['potential_deal_value'] else 0.0
            if row_stage not in pipeline_by_stage:
                pipeline_by_stage[row_stage] = {'companies': [], 'total_value': 0.0}
            pipeline_by_stage[row_stage]['companies'].append({
                'customer_id':       row['customer_id'],
                'company':           row['company'],
                'contact_person':    row['contact_person'],
                'phone_number':      row['phone_number'],
                'salesperson':       row['salesperson_name'],
                'next_action':       row['next_action'],
                'next_action_date':  row['next_action_due_date'],
                'last_contact_date': row['last_contact_date'],
                'summary':           row['summary_last_contact'],
                'deal_value':        deal_value,
                'followup_count':    row['followup_count'],
            })
            pipeline_by_stage[row_stage]['total_value'] += deal_value

        total_value = sum(s['total_value'] for s in pipeline_by_stage.values())

        conn.close()
        return render_template('dashboard/manager_dashboard.html',
                               customers=customers,
                               sales_stage_counts=sales_stage_counts,
                               total_value=total_value,
                               page=page,
                               total_pages=total_pages,
                               total_customers_filtered=total_customers,
                               salesperson_name=session.get('salesperson_name', 'Manager'),
                               pipeline_by_stage=pipeline_by_stage,
                               salespeople=salespeople,
                               sales_stages=sales_stages,
                               current_salesperson_id=salesperson_id,
                               current_stage=stage,
                               current_search=search)
    except Exception as e:
        print(f"Error in manager dashboard: {e}")
        return f"Dashboard error: {e}", 500


# ── admin dashboard ──────────────────────────────────────────────────────────

@dashboard_bp.route('/admin/dashboard')
@require_tenant
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('auth.login'))
    return render_template('dashboard/admin_dashboard.html')


# ── mark follow-up action complete ───────────────────────────────────────────

@dashboard_bp.route('/followup/<int:activity_id>/complete', methods=['POST'])
@require_tenant
def complete_followup(activity_id):
    if 'salesperson_id' not in session:
        return jsonify({'success': False}), 401

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        conn.execute("""
            UPDATE activities
            SET next_action_done = 1,
                updated_at = datetime('now','localtime')
            WHERE id = ? AND tenant_id = ?
              AND action = 'follow_up' AND entity_type = 'customer'
        """, (activity_id, tenant_id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

# ── ai os dashboard ──────────────────────────────────────────────────────────

@dashboard_bp.route('/ai_os_dashboard')
@require_tenant
def ai_os_dashboard():
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    salesperson_id = session['salesperson_id']
    tenant_id      = get_current_tenant_id()
    conn = get_db()
    cursor = conn.cursor()

    # Fetch main tracks and their stats
    cursor.execute("""
        SELECT t.id, t.name, t.description,
               COUNT(DISTINCT c.customer_id) as lead_count,
               COALESCE(SUM(c_act.deal_value), 0) as total_value
        FROM business_tracks t
        LEFT JOIN business_subcategories s ON s.track_id = t.id
        LEFT JOIN customers c ON c.subcategory_id = s.id AND c.tenant_id = t.tenant_id
        LEFT JOIN (
            SELECT entity_id, MAX(deal_value) as deal_value
            FROM activities
            WHERE entity_type = 'customer' AND action = 'follow_up'
            GROUP BY entity_id
        ) c_act ON c_act.entity_id = c.customer_id
        WHERE t.tenant_id = ? AND t.is_active = 1
        GROUP BY t.id, t.name, t.description
    """, (tenant_id,))
    tracks_data = cursor.fetchall()

    tracks = []
    for track in tracks_data:
        # Fetch subcategories for this track
        cursor.execute("""
            SELECT s.id, s.name,
                   COUNT(DISTINCT c.customer_id) as lead_count,
                   COALESCE(SUM(c_act.deal_value), 0) as total_value
            FROM business_subcategories s
            LEFT JOIN customers c ON c.subcategory_id = s.id AND c.tenant_id = s.tenant_id
            LEFT JOIN (
                SELECT entity_id, MAX(deal_value) as deal_value
                FROM activities
                WHERE entity_type = 'customer' AND action = 'follow_up'
                GROUP BY entity_id
            ) c_act ON c_act.entity_id = c.customer_id
            WHERE s.track_id = ? AND s.tenant_id = ? AND s.is_active = 1
            GROUP BY s.id, s.name
        """, (track['id'], tenant_id))
        subcategories = cursor.fetchall()

        tracks.append({
            'id': track['id'],
            'name': track['name'],
            'description': track['description'],
            'lead_count': track['lead_count'],
            'total_value': track['total_value'],
            'subcategories': subcategories
        })

    # Fetch Departments
    cursor.execute("SELECT id, name FROM departments WHERE tenant_id = ? AND is_active = 1 ORDER BY id", (tenant_id,))
    departments = cursor.fetchall()

    # Fetch Tasks
    cursor.execute("""
        SELECT t.id, t.title, t.description, t.status, t.due_date, 
               s.name as subcategory_name, tr.name as track_name, tr.id as track_id, s.id as subcategory_id,
               d.name as department_name, d.id as department_id
        FROM tasks t
        LEFT JOIN business_subcategories s ON t.subcategory_id = s.id
        LEFT JOIN business_tracks tr ON s.track_id = tr.id
        LEFT JOIN departments d ON t.department_id = d.id
        WHERE t.tenant_id = ? AND t.assigned_to = ?
        ORDER BY t.due_date ASC
    """, (tenant_id, salesperson_id))
    tasks_data = cursor.fetchall()
    
    from datetime import datetime, date
    
    today = date.today()
    
    def group_tasks(task_list):
        # We want to preserve order: Overdue, Today, Tomorrow, Upcoming, No Date
        groups = {
            'Overdue': [],
            'Today': [],
            'Tomorrow': [],
            'Upcoming': [],
            'No Date': []
        }
        for t in task_list:
            if not t['due_date']:
                groups['No Date'].append(t)
            else:
                try:
                    t_date = datetime.strptime(t['due_date'][:10], '%Y-%m-%d').date()
                    if t_date < today:
                        groups['Overdue'].append(t)
                    elif t_date == today:
                        groups['Today'].append(t)
                    elif (t_date - today).days == 1:
                        groups['Tomorrow'].append(t)
                    else:
                        groups['Upcoming'].append(t)
                except:
                    groups['No Date'].append(t)
        return groups

    tasks = {
        'pending': group_tasks([t for t in tasks_data if t['status'] == 'pending']),
        'in_progress': group_tasks([t for t in tasks_data if t['status'] == 'in-progress']),
        'done': group_tasks([t for t in tasks_data if t['status'] == 'done'])
    }
    
    # Also pass a flat count for the headers
    task_counts = {
        'pending': sum(len(g) for g in tasks['pending'].values()),
        'in_progress': sum(len(g) for g in tasks['in_progress'].values()),
        'done': sum(len(g) for g in tasks['done'].values())
    }

    conn.close()
    return render_template('dashboard/ai_os_dashboard.html', tracks=tracks, tasks=tasks, task_counts=task_counts, departments=departments)


# ── AI OS Tasks API ─────────────────────────────────────────────────────────

from flask import request

@dashboard_bp.route('/api/tasks/update', methods=['POST'])
@require_tenant
def api_update_task():
    if 'salesperson_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    data = request.json
    task_id = data.get('task_id')
    
    if not task_id:
        return jsonify({'success': False, 'error': 'Missing task_id'}), 400
        
    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        updates = []
        params = []
        
        if 'status' in data and data['status']:
            updates.append("status = ?")
            params.append(data['status'])
            
        if 'due_date' in data:
            updates.append("due_date = ?")
            params.append(data['due_date'] if data['due_date'] else None)
            
        if 'subcategory_id' in data:
            updates.append("subcategory_id = ?")
            try:
                sub_id = int(data['subcategory_id']) if data['subcategory_id'] else None
                params.append(sub_id)
            except ValueError:
                params.append(None)
                
        if 'department_id' in data:
            updates.append("department_id = ?")
            try:
                dept_id = int(data['department_id']) if data['department_id'] else None
                params.append(dept_id)
            except ValueError:
                params.append(None)
                
        if not updates:
            return jsonify({'success': True})
            
        sql = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ? AND tenant_id = ?"
        params.extend([task_id, tenant_id])
        
        conn.execute(sql, tuple(params))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@dashboard_bp.route('/api/tasks/create', methods=['POST'])
@require_tenant
def api_create_task():
    if 'salesperson_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
    data = request.json
    title = data.get('title')
    description = data.get('description', '')
    status = data.get('status', 'pending')
    subcategory_id = data.get('subcategory_id')
    department_id = data.get('department_id')
    due_date = data.get('due_date')
    
    if not title:
        return jsonify({'success': False, 'error': 'Title is required'}), 400
        
    tenant_id = get_current_tenant_id()
    salesperson_id = session['salesperson_id']
    
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tasks (title, description, status, due_date, subcategory_id, department_id, assigned_to, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, description, status, due_date, subcategory_id, department_id, salesperson_id, tenant_id))
        conn.commit()
        
        new_task_id = cursor.lastrowid
        
        # Fetch the created task details to return to frontend
        cursor.execute("""
            SELECT t.id, t.title, t.description, t.status, t.due_date, 
                   s.name as subcategory_name, tr.name as track_name, tr.id as track_id,
                   d.name as department_name, d.id as department_id
            FROM tasks t
            LEFT JOIN business_subcategories s ON t.subcategory_id = s.id
            LEFT JOIN business_tracks tr ON s.track_id = tr.id
            LEFT JOIN departments d ON t.department_id = d.id
            WHERE t.id = ?
        """, (new_task_id,))
        new_task = cursor.fetchone()
        
        return jsonify({
            'success': True, 
            'task': dict(new_task) if new_task else None
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()
