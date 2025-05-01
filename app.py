from flask import Flask, render_template, request, redirect, url_for, session, g, abort, jsonify
import sqlite3
import hashlib
from datetime import datetime, date, timedelta, timezone

DATABASE_NAME = 'crm.db'

app = Flask(__name__)
app.secret_key = 'your_secret_key'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE_NAME)
        db.row_factory = sqlite3.Row
    return db

def close_db():
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.teardown_appcontext
def teardown_db(error):
    close_db()

def get_company_id():
    if 'company_id' in session:
        return session['company_id']
    return None

def require_company_id():
    company_id = get_company_id()
    if not company_id:
        abort(403, description="Company ID is required")
    return company_id

@app.route('/')
def index():
    if 'salesperson_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        first_name = request.form['first_name']
        password = request.form['password']
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            # First, get the user's company_id
            cursor.execute("""
                SELECT st.salesperson_id, st.password, st.salesperson_name, st.role, st.company_id, c.company_id as valid_company_id
                FROM sales_team st
                LEFT JOIN companies c ON st.company_id = c.company_id
                WHERE st.first_name = ?
            """, (first_name,))
            user = cursor.fetchone()
            
            if not user:
                return render_template('login.html', error='Invalid username or password')
            
            # Verify password
            if hashlib.sha256(password.encode()).hexdigest() != user['password']:
                return render_template('login.html', error='Invalid username or password')
            
            # Verify company exists
            if not user['valid_company_id']:
                return render_template('login.html', error='Your account is not associated with a valid company')
            
            # Set session variables
            session['salesperson_id'] = user['salesperson_id']
            session['salesperson_name'] = user['salesperson_name']
            session['role'] = user['role']
            session['company_id'] = user['company_id']
            
            if user['role'] == 'manager':
                print(f"Manager logged in. session['salesperson_name']: {session['salesperson_name']}")
                return redirect(url_for('manager_dashboard'))
            else:
                return redirect(url_for('dashboard'))
                
        except sqlite3.Error as e:
            print(f"Database error during login: {e}")
            return render_template('login.html', error='An error occurred during login')
        finally:
            conn.close()
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('salesperson_id', None)
    session.pop('salesperson_name', None)
    session.pop('role', None)
    session.pop('company_id', None)
    return redirect(url_for('login'))

from datetime import datetime, date, timedelta

# ... (rest of your imports and setup) ...


@app.route('/dashboard')
def dashboard():
    if 'salesperson_id' in session:
        salesperson_id = session['salesperson_id']
        company_id = require_company_id()
        salesperson_name = session.get('salesperson_name', 'Salesperson')
        conn = get_db()
        cursor = conn.cursor()

        # Fetch the salesperson's name
        cursor.execute("""
            SELECT first_name 
            FROM sales_team 
            WHERE salesperson_id = ? AND company_id = ?
        """, (salesperson_id, company_id))
        salesperson = cursor.fetchone()
        salesperson_name = salesperson['first_name'] if salesperson else 'Salesperson'

        # 1. Number of Open Leads Assigned (Only counting active sales stages)
        cursor.execute('''
            SELECT COUNT(DISTINCT c.customer_id)
            FROM customers c
            WHERE c.assigned_salesperson_id = ?
            AND c.company_id = ?
            AND (
                -- Check if there are any follow-ups
                EXISTS (
                    SELECT 1 
                    FROM sales_followup sf 
                    WHERE sf.customer_id = c.customer_id 
                    AND sf.company_id = c.company_id
                    AND sf.current_sales_stage IN ('عميل محتمل', 'جاري التواصل', 'تقديم عرض السعر', 'جاري التفاوض')
                    AND sf.followup_id = (
                        SELECT MAX(followup_id)
                        FROM sales_followup
                        WHERE customer_id = c.customer_id
                        AND company_id = c.company_id
                    )
                )
                OR
                -- Include customers with no follow-ups (considered as 'عميل محتمل')
                NOT EXISTS (
                    SELECT 1
                    FROM sales_followup sf
                    WHERE sf.customer_id = c.customer_id
                    AND sf.company_id = c.company_id
                )
            )
        ''', (salesperson_id, company_id))
        open_leads_count = cursor.fetchone()[0] or 0

        # 2. Upcoming Follow-ups (Categorized with Saturday as the first day of the week)
        today = date.today()  # 2025-04-27 (Sunday in Riyadh)

        # Calculate the start of the current week (Saturday)
        days_since_saturday = (today.weekday() - 5) % 7
        current_week_start = today - timedelta(days=days_since_saturday)

        # Calculate the start of next week (Saturday)
        next_week_start = current_week_start + timedelta(days=7)
        next_week_end = next_week_start + timedelta(days=6)  # Friday of next week

        cursor.execute('''
            SELECT 
                c.company_name, 
                sf.next_action, 
                sf.next_action_due_date, 
                c.customer_id, 
                sf.summary_last_contact
            FROM customers c
            JOIN (
                SELECT 
                    customer_id,
                    next_action,
                    next_action_due_date,
                    summary_last_contact,
                    ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY last_contact_date DESC, followup_id DESC) as rn
                FROM sales_followup
                WHERE next_action != 'إغلاق البيع'
            ) sf ON c.customer_id = sf.customer_id AND sf.rn = 1
            WHERE c.assigned_salesperson_id = ?
            AND sf.next_action_due_date >= ?
            ORDER BY sf.next_action_due_date
        ''', (salesperson_id, today.strftime('%Y-%m-%d')))
        all_upcoming_followups = cursor.fetchall()

        followups_today = []
        followups_this_week = []
        followups_next_week = []
        followups_later = []

        for followup in all_upcoming_followups:
            due_date = datetime.strptime(followup['next_action_due_date'], '%Y-%m-%d').date()
            if due_date == today:
                followups_today.append(followup)
            elif current_week_start <= due_date < next_week_start and due_date != today:
                followups_this_week.append(followup)
            elif next_week_start <= due_date <= next_week_end:
                followups_next_week.append(followup)
            elif due_date > next_week_end:
                followups_later.append(followup)

        # 3. Sales Pipeline Breakdown (Retrieving stage and customer_id from the LAST follow-up)
        cursor.execute('''
            SELECT 
                c.company_name,
                st.first_name as salesperson_name,
                sf.current_sales_stage,
                c.customer_id,
                sf.next_action,
                sf.next_action_due_date,
                sf.potential_deal_value,
                sf.summary_last_contact
            FROM customers c
            LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
            LEFT JOIN (
                SELECT 
                    customer_id,
                    current_sales_stage,
                    next_action,
                    next_action_due_date,
                    potential_deal_value,
                    summary_last_contact,
                    ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY last_contact_date DESC, followup_id DESC) as rn
                FROM sales_followup
            ) sf ON c.customer_id = sf.customer_id AND sf.rn = 1
            WHERE c.assigned_salesperson_id = ?
        ''', (salesperson_id,))
        pipeline_from_last_followup = cursor.fetchall()

        # Organize the pipeline data by stage
        pipeline_by_stage = {}
        for item in pipeline_from_last_followup:
            stage = item['current_sales_stage'] or 'عميل محتمل'
            company = item['company_name']
            customer_id = item['customer_id']
            salesperson = item['salesperson_name']
            next_action = item['next_action']
            next_action_date = item['next_action_due_date']
            deal_value = item['potential_deal_value']
            summary = item['summary_last_contact']
            
            if stage not in pipeline_by_stage:
                pipeline_by_stage[stage] = []
            pipeline_by_stage[stage].append({
                'company': company,
                'customer_id': customer_id,
                'salesperson': salesperson,
                'next_action': next_action,
                'next_action_date': next_action_date,
                'deal_value': deal_value,
                'summary': summary
            })

        conn.close()
        return render_template('dashboard.html', salesperson_name=salesperson_name,
                                   open_leads_count=open_leads_count,
                                   sales_pipeline=pipeline_by_stage,
                                   followups_today=followups_today,
                                   followups_this_week=followups_this_week,
                                   followups_next_week=followups_next_week,
                                   followups_later=followups_later)
    return redirect(url_for('login'))

import hashlib


@app.route('/manager/dashboard')
def manager_dashboard():
    if 'role' in session and (session['role'] == 'manager' or session['role'] == 'admin'):
        manager_id = session['salesperson_id']
        manager_name = session.get('salesperson_name', 'Manager')
        conn = get_db()
        cursor = conn.cursor()

        page = request.args.get('page', 1, type=int)
        per_page = 7

        sort_by = request.args.get('sort_by', 'date_added')
        sort_order = request.args.get('sort_order', 'desc')

        order_by_clause = ''
        if sort_by == 'assigned_salesperson':
            order_by_clause = 'ORDER BY st.first_name'
        elif sort_by == 'date_added':
            order_by_clause = 'ORDER BY c.date_added'
        elif sort_by == 'last_contact':
            order_by_clause = 'ORDER BY last_contact_date'
        elif sort_by == 'sales_stage':
            order_by_clause = 'ORDER BY current_sales_stage'
        elif sort_by == 'next_followup_date':
            order_by_clause = 'ORDER BY next_followup_date'
        else:
            order_by_clause = 'ORDER BY c.date_added'

        if sort_order == 'asc':
            order_by_clause += ' ASC'
        else:
            order_by_clause += ' DESC'

        where_clause = []
        parameters = []

        salesperson_id_filter = request.args.get('salesperson_id')
        if salesperson_id_filter:
            where_clause.append("c.assigned_salesperson_id = ?")
            parameters.append(salesperson_id_filter)

        stage_filter = request.args.get('stage')
        if stage_filter:
            where_clause.append("""
                COALESCE(
                    (SELECT sf.current_sales_stage 
                     FROM sales_followup sf 
                     WHERE sf.customer_id = c.customer_id 
                     ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                     LIMIT 1),
                    'عميل محتمل'
                ) = ?
            """)
            parameters.append(stage_filter)

        search_term = request.args.get('search')
        if search_term:
            search_term = f"%{search_term}%"
            where_clause.append("""
                (LOWER(c.company_name) LIKE LOWER(?) OR
                LOWER(c.phone_number) LIKE LOWER(?) OR
                LOWER(c.contact_person) LIKE LOWER(?) OR
                LOWER(COALESCE(
                    (SELECT sf.current_sales_stage 
                     FROM sales_followup sf 
                     WHERE sf.customer_id = c.customer_id 
                     ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                     LIMIT 1),
                    'عميل محتمل'
                )) LIKE LOWER(?))
            """)
            parameters.extend([search_term, search_term, search_term, search_term])

        # --- Fetch data for the sales funnel chart ---
        sales_stage_query = '''
            SELECT 
                COALESCE(
                    (SELECT sf.current_sales_stage 
                     FROM sales_followup sf 
                     WHERE sf.customer_id = c.customer_id 
                     ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                     LIMIT 1),
                    'عميل محتمل'
                ) as current_sales_stage,
                COUNT(DISTINCT c.customer_id) AS count,
                GROUP_CONCAT(DISTINCT c.customer_id) AS customer_ids,
                GROUP_CONCAT(DISTINCT c.company_name) AS company_names,
                SUM(COALESCE(
                    (SELECT sf.potential_deal_value 
                     FROM sales_followup sf 
                     WHERE sf.customer_id = c.customer_id 
                     ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                     LIMIT 1),
                    0
                )) as stage_total_value
            FROM customers c
            LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
        '''
        if where_clause:
            sales_stage_query += " WHERE " + " AND ".join(where_clause)
        sales_stage_query += " GROUP BY current_sales_stage"

        cursor.execute(sales_stage_query, parameters)
        sales_stage_data = cursor.fetchall()

        total_customers_filtered = 0
        sales_stage_counts = {}
        sales_stage_details = {}

        # First, calculate the total number of customers
        for item in sales_stage_data:
            total_customers_filtered += item['count']

        # Then calculate percentages based on the total
        for item in sales_stage_data:
            stage = item['current_sales_stage']
            count = item['count']
            customer_ids = item['customer_ids'].split(',') if item['customer_ids'] else []
            company_names = item['company_names'].split(',') if item['company_names'] else []
            stage_value = item['stage_total_value'] or 0
            
            percentage = (count / total_customers_filtered * 100) if total_customers_filtered > 0 else 0
            
            sales_stage_counts[stage] = {
                'count': count,
                'percentage': f"{percentage:.2f}%",
                'total_value': stage_value
            }
            
            sales_stage_details[stage] = list(zip(customer_ids, company_names))

        # --- Fetch data for the sales pipeline ---
        pipeline_query = '''
            SELECT 
                c.company_name,
                c.contact_person,
                c.phone_number,
                st.first_name as salesperson_name,
                sf.current_sales_stage,
                c.customer_id,
                sf.next_action,
                sf.next_action_due_date,
                sf.potential_deal_value,
                sf.summary_last_contact,
                (SELECT COUNT(*) FROM sales_followup WHERE customer_id = c.customer_id) as followup_count,
                SUM(sf.potential_deal_value) OVER (PARTITION BY sf.current_sales_stage) as stage_total_value
            FROM customers c
            LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
            LEFT JOIN (
                SELECT 
                    customer_id,
                    current_sales_stage,
                    next_action,
                    next_action_due_date,
                    potential_deal_value,
                    summary_last_contact,
                    ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY last_contact_date DESC, followup_id DESC) as rn
                FROM sales_followup
            ) sf ON c.customer_id = sf.customer_id AND sf.rn = 1
            WHERE c.assigned_salesperson_id IS NOT NULL
        '''
        if where_clause:
            pipeline_query += " AND " + " AND ".join(where_clause)

        cursor.execute(pipeline_query, parameters)
        pipeline_data = cursor.fetchall()

        # Organize the pipeline data by stage
        pipeline_by_stage = {}
        for item in pipeline_data:
            stage = item['current_sales_stage'] or 'عميل محتمل'
            if stage not in pipeline_by_stage:
                pipeline_by_stage[stage] = {
                    'companies': [],
                    'total_value': item['stage_total_value'] or 0
                }
            pipeline_by_stage[stage]['companies'].append({
                'company': item['company_name'],
                'contact_person': item['contact_person'],
                'phone_number': item['phone_number'],
                'customer_id': item['customer_id'],
                'salesperson': item['salesperson_name'],
                'next_action': item['next_action'],
                'next_action_date': item['next_action_due_date'],
                'deal_value': item['potential_deal_value'],
                'summary': item['summary_last_contact'],
                'followup_count': item['followup_count'] or 0
            })

        # --- Calculate total pages for pagination ---
        sql_count_query = f'''SELECT COUNT(c.customer_id)
                               FROM customers c
                               LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id'''
        if where_clause:
            sql_count_query += " WHERE " + " AND ".join(where_clause)
        cursor.execute(sql_count_query, parameters)
        total_customers = cursor.fetchone()[0]
        total_pages = (total_customers + per_page - 1) // per_page

        # --- Fetch data for the customers table ---
        sql_query = f'''
            SELECT
                c.customer_id,
                st.first_name AS assigned_salesperson,
                c.company_name,
                c.company_industry,
                c.contact_person,
                c.contact_person_position,
                c.phone_number,
                c.date_added,
                (SELECT sf.last_contact_date FROM sales_followup sf WHERE sf.customer_id = c.customer_id ORDER BY sf.last_contact_date DESC, sf.followup_id DESC LIMIT 1) AS last_contact_date,
                COALESCE(
                    (SELECT sf.current_sales_stage 
                     FROM sales_followup sf 
                     WHERE sf.customer_id = c.customer_id 
                     ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                     LIMIT 1),
                    'عميل محتمل'
                ) AS current_sales_stage,
                (SELECT sf.next_action_due_date 
                 FROM sales_followup sf 
                 WHERE sf.customer_id = c.customer_id 
                 AND sf.next_action_due_date IS NOT NULL
                 AND sf.next_action != 'إغلاق البيع'
                 ORDER BY sf.followup_id DESC, sf.next_action_due_date DESC
                 LIMIT 1) AS next_followup_date
            FROM customers c
            LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
        '''
        if where_clause:
            sql_query += " WHERE " + " AND ".join(where_clause)
        sql_query += f" {order_by_clause} LIMIT ? OFFSET ?"

        offset = (page - 1) * per_page
        cursor.execute(sql_query, tuple(parameters) + (per_page, offset))
        customers = cursor.fetchall()

        cursor.execute("SELECT salesperson_id, first_name FROM sales_team")
        salespeople = cursor.fetchall()
        cursor.execute("SELECT DISTINCT current_sales_stage FROM sales_followup WHERE current_sales_stage IS NOT NULL")
        sales_stages = [row['current_sales_stage'] for row in cursor.fetchall()]
        # Add 'عميل محتمل' to the list of sales stages if it's not already there
        if 'عميل محتمل' not in sales_stages:
            sales_stages.append('عميل محتمل')

        conn.close()
        return render_template('manager_dashboard.html', 
                             salesperson_name=manager_name,
                             customers=customers, 
                             salespeople=salespeople, 
                             sales_stages=sales_stages,
                             sales_stage_counts=sales_stage_counts,
                             sales_stage_details=sales_stage_details,
                             pipeline_by_stage=pipeline_by_stage,
                             total_customers_filtered=total_customers_filtered,
                             page=page,
                             total_pages=total_pages,
                             sort_by=sort_by,
                             sort_order=sort_order)
    return redirect(url_for('login'))

@app.route('/salespeople/add', methods=['GET', 'POST'])
def add_salesperson():
    if 'salesperson_id' in session and session.get('role') == 'admin': # Ensure only admins can access
        conn = None
        error = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            if request.method == 'POST':
                first_name = request.form['first_name']
                last_name = request.form['last_name']
                password = request.form['password']
                salesperson_name = request.form['salesperson_name']
                work_email = request.form['work_email']
                phone_number = request.form['phone_number']
                role = request.form.get('role', 'salesperson') # Default to 'salesperson' if not provided

                hashed_password = hashlib.sha256(password.encode()).hexdigest()

                cursor.execute('''
    INSERT INTO sales_team (first_name, last_name, password, salesperson_name, work_email, phone_number, role)
    VALUES (?, ?, ?, ?, ?, ?, ?)
''', (first_name, last_name, hashed_password, salesperson_name, work_email, phone_number, role))

                conn.commit()
                return redirect(url_for('salespeople_list')) # Redirect to the list of salespeople
            return render_template('add_salesperson.html', error=error)
        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            error = f"Database error during add_salesperson: {e}"
            print(error)
            return render_template('add_salesperson.html', error=error)
        finally:
            if conn:
                conn.close()
    return redirect(url_for('login')) # Redirect to login if not logged in or not admin

@app.route('/salespeople')
def salespeople_list():
    if 'salesperson_id' in session and session.get('role') == 'admin': # Ensure only admins can access
        conn = get_db()
        cursor = conn.cursor()
        salespeople = []
        try:
            cursor.execute("SELECT salesperson_id, first_name, last_name, salesperson_name, work_email, phone_number, role FROM sales_team")
            salespeople = cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Database error during salespeople_list: {e}")
        finally:
            if conn:
                conn.close()
        return render_template('salespeople_list.html', salespeople=salespeople)
    return redirect(url_for('login'))

@app.route('/customers')
def customer_list():
    if 'salesperson_id' in session:
        salesperson_id = session['salesperson_id']
        user_role = session.get('role')  # Get the user's role
        conn = get_db()
        cursor = conn.cursor()
        search_term = request.args.get('search')
        sort_by = request.args.get('sort_by')
        order = request.args.get('order', 'asc')
        page = request.args.get('page', 1, type=int)
        per_page = 12

        query = '''
            SELECT 
                c.*, 
                st.salesperson_name,
                (
                    SELECT sf.current_sales_stage 
                    FROM sales_followup sf 
                    WHERE sf.customer_id = c.customer_id 
                    ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                    LIMIT 1
                ) as current_sales_stage,
                (
                    SELECT sf.potential_deal_value
                    FROM sales_followup sf 
                    WHERE sf.customer_id = c.customer_id 
                    ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                    LIMIT 1
                ) as potential_value
            FROM customers c
            LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
        '''
        where_clause = ""
        params = ()
        order_clause = ""

        if user_role not in ['admin', 'manager']:
            where_clause += "WHERE c.assigned_salesperson_id = ?"
            params = (salesperson_id,)

        stage_filter = request.args.get('stage')
        if stage_filter:
            if where_clause:
                where_clause += " AND "
            else:
                where_clause += "WHERE "
            where_clause += """
                COALESCE(
                    (SELECT sf.current_sales_stage 
                     FROM sales_followup sf 
                     WHERE sf.customer_id = c.customer_id 
                     ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                     LIMIT 1),
                    'N/A'
                ) = ?
            """
            params = params + (stage_filter,)

        if search_term:
            search_term_lower = f"%{search_term.lower()}%"
            if where_clause:
                where_clause += f"""
                    AND (LOWER(c.company_name) LIKE ?
                         OR LOWER(c.contact_person) LIKE ?
                         OR LOWER(c.phone_number) LIKE ?
                         OR LOWER(st.salesperson_name) LIKE ?
                         OR EXISTS (
                             SELECT 1
                             FROM sales_followup sf_search
                             WHERE sf_search.customer_id = c.customer_id
                               AND LOWER(sf_search.current_sales_stage) LIKE ?
                         ))
                """
                params = params + (search_term_lower,) * 4 + (search_term_lower,)
            else:
                where_clause += f"""
                    WHERE (LOWER(c.company_name) LIKE ?
                           OR LOWER(c.contact_person) LIKE ?
                           OR LOWER(c.phone_number) LIKE ?
                           OR LOWER(st.salesperson_name) LIKE ?
                           OR EXISTS (
                               SELECT 1
                               FROM sales_followup sf_search
                               WHERE sf_search.customer_id = c.customer_id
                                 AND LOWER(sf_search.current_sales_stage) LIKE ?
                           ))
                """
                params = (search_term_lower,) * 4 + (search_term_lower,)

        if sort_by:
            sort_by_lower = sort_by.lower()
            allowed_columns = ['customer_id', 'company_name', 'contact_person', 'phone_number', 'date_added', 'last_contact_date', 'current_sales_stage', 'salesperson_name']
            if sort_by_lower in allowed_columns:
                if sort_by_lower == 'current_sales_stage':
                    order_clause = f"ORDER BY (SELECT sf.current_sales_stage FROM sales_followup sf WHERE sf.customer_id = c.customer_id ORDER BY sf.last_contact_date DESC, sf.followup_id DESC LIMIT 1) {order}"
                elif sort_by_lower == 'salesperson_name':
                    order_clause = f"ORDER BY LOWER(st.salesperson_name) {order}"
                else:
                    order_clause = f"ORDER BY LOWER(c.{sort_by_lower}) {order}"

        count_query = f"SELECT COUNT(c.customer_id) FROM customers c LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id {where_clause}"
        cursor.execute(count_query, params)
        total_customers = cursor.fetchone()[0]
        total_pages = (total_customers + per_page - 1) // per_page

        query += f" {where_clause} {order_clause} LIMIT ? OFFSET ?"
        offset = (page - 1) * per_page
        cursor.execute(query, params + (per_page, offset))
        customers = cursor.fetchall()

        # Get all available sales stages
        cursor.execute("SELECT DISTINCT current_sales_stage FROM sales_followup WHERE current_sales_stage IS NOT NULL")
        sales_stages = [row['current_sales_stage'] for row in cursor.fetchall()]
        # Add 'N/A' to the list of sales stages if it's not already there
        if 'N/A' not in sales_stages:
            sales_stages.append('N/A')

        conn.close()
        return render_template('customer_list.html', 
                             customers=customers, 
                             search_term=search_term,
                             sort_by=sort_by, 
                             order=order, 
                             page=page, 
                             total_pages=total_pages,
                             sales_stages=sales_stages,
                             current_stage=request.args.get('stage', ''))
    return redirect(url_for('login'))

@app.route('/customers/add', methods=['GET', 'POST'])
def add_customer():
    if 'salesperson_id' in session:
        salesperson_id = session['salesperson_id'] # Get the logged-in user's ID
        user_role = session.get('role')
        company_id = require_company_id()  # Get the company_id from session
        conn = get_db()
        cursor = conn.cursor()
        error = None

        # Fetch all salespeople for the dropdown (for managers and admins)
        cursor.execute("SELECT salesperson_id, salesperson_name, first_name FROM sales_team WHERE company_id = ?", (company_id,))
        all_salespeople = cursor.fetchall()

        if request.method == 'POST':
            company_name = request.form['company_name']
            company_industry = request.form['company_industry']
            contact_person = request.form['contact_person']
            contact_person_position = request.form['contact_person_position']
            phone_number = request.form['phone_number']
            email_address = request.form.get('email_address')
            company_address = request.form.get('company_address')
            lead_source = request.form.get('lead_source')
            initial_interest = request.form.get('initial_interest')
            date_added = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            assigned_salesperson_id = salesperson_id # Default to the creator

            if user_role == 'manager' or user_role == 'admin':
                assigned_salesperson_id = request.form.get('assigned_salesperson_id')

            try:
                cursor.execute('''
                    INSERT INTO customers (
                        company_name, company_industry, contact_person,
                        contact_person_position, phone_number, email_address,
                        company_address, lead_source, initial_interest,
                        date_added, assigned_salesperson_id, company_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    company_name, company_industry, contact_person,
                    contact_person_position, phone_number, email_address,
                    company_address, lead_source, initial_interest,
                    date_added, assigned_salesperson_id, company_id
                ))
                customer_id = cursor.lastrowid
                conn.commit()
                return redirect(url_for('customer_detail', customer_id=customer_id))
            except sqlite3.Error as e:
                conn.rollback()
                error = f"Database error during add_customer: {e}"
                print(error)
                return render_template('add_customer.html', error=error, salespeople=all_salespeople)

        return render_template('add_customer.html', error=error, salespeople=all_salespeople)
    return redirect(url_for('login'))

@app.route('/customer/<int:customer_id>')
def customer_detail(customer_id):
    if 'salesperson_id' in session:
        company_id = require_company_id()
        conn = get_db()
        cursor = conn.cursor()
        customer = None
        followups = []
        is_admin = session.get('role') == 'admin'
        page = request.args.get('page', 1, type=int)
        per_page = 12
        total_pages = 0
        error = None

        try:
            # Get customer details with company_id check
            cursor.execute("""
                SELECT c.*, st.salesperson_name,
                    (SELECT sf.current_sales_stage 
                     FROM sales_followup sf 
                     WHERE sf.customer_id = c.customer_id 
                     AND sf.company_id = c.company_id
                     ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                     LIMIT 1) as current_sales_stage,
                    (SELECT sf.potential_deal_value
                     FROM sales_followup sf 
                     WHERE sf.customer_id = c.customer_id 
                     AND sf.company_id = c.company_id
                     ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                     LIMIT 1) as latest_potential_value
                FROM customers c
                LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
                WHERE c.customer_id = ? AND c.company_id = ?
            """, (customer_id, company_id))
            customer = cursor.fetchone()

            if not customer:
                error = "Customer not found or you don't have access to this customer."
            else:
                # Get total count of follow-ups for pagination
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM sales_followup 
                    WHERE customer_id = ? AND company_id = ?
                """, (customer_id, company_id))
                total_followups = cursor.fetchone()[0]
                total_pages = (total_followups + per_page - 1) // per_page

                # Get paginated follow-ups, sorted by last_contact_date DESC
                offset = (page - 1) * per_page
                cursor.execute("""
                    SELECT 
                        followup_id,
                        customer_id,
                        assigned_salesperson_id,
                        last_contact_date,
                        last_contact_method,
                        summary_last_contact,
                        next_action,
                        next_action_due_date,
                        current_sales_stage,
                        potential_deal_value,
                        notes,
                        created_at
                    FROM sales_followup 
                    WHERE customer_id = ? 
                    AND company_id = ?
                    ORDER BY last_contact_date DESC, followup_id DESC 
                    LIMIT ? OFFSET ?
                """, (customer_id, company_id, per_page, offset))
                followups = cursor.fetchall()

        except sqlite3.Error as e:
            print(f"Database error: {e}")
            error = "An error occurred while retrieving customer data."
        finally:
            conn.close()

        return render_template('customer_detail.html', 
                            customer=customer, 
                            followups=followups, 
                            is_admin=is_admin,
                            page=page,
                            total_pages=total_pages,
                            error=error)
    return redirect(url_for('login'))

@app.route('/admin/customers/<int:customer_id>/assign', methods=['GET', 'POST'])
@app.route('/manager/customers/<int:customer_id>/assign', methods=['GET', 'POST']) # Add manager route
def assign_customer(customer_id):
    if 'salesperson_id' in session and session.get('role') in ('admin', 'manager'):
        conn = get_db()
        cursor = conn.cursor()

        try:
            # Fetch the customer's details
            cursor.execute("SELECT customer_id, company_name FROM customers WHERE customer_id = ?", (customer_id,))
            customer = cursor.fetchone()
            if not customer:
                abort(404)

            if request.method == 'POST':
                new_salesperson_id = request.form.get('salesperson_id')
                cursor.execute("UPDATE customers SET assigned_salesperson_id = ? WHERE customer_id = ?", (new_salesperson_id, customer_id))
                conn.commit()
                return redirect(url_for('customer_detail', customer_id=customer_id))

            # Fetch the list of salespeople based on user role
            if session['role'] == 'admin' or session['role'] == 'manager':
                cursor.execute("SELECT salesperson_id, salesperson_name FROM sales_team")
                salespeople = cursor.fetchall()
            else:
                abort(403) # Should not happen if the initial role check passed

            # Fetch the currently assigned salesperson
            cursor.execute("SELECT assigned_salesperson_id FROM customers WHERE customer_id = ?", (customer_id,))
            assigned_salesperson = cursor.fetchone()
            current_assigned_id = assigned_salesperson['assigned_salesperson_id'] if assigned_salesperson else None

            return render_template('assign_customer.html', customer=customer, salespeople=salespeople, current_assigned_id=current_assigned_id)

        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
            abort(500)
        finally:
            conn.close()
    else:
        abort(403)
    return redirect(url_for('login'))

@app.route('/admin/customers/<int:customer_id>/assign', methods=['POST'])
def assign_customer_submit(customer_id):
    if 'salesperson_id' in session and session.get('role') == 'admin':
        new_salesperson_id = request.form.get('salesperson_id')
        conn = get_db()
        cursor = conn.cursor()

        try:
            cursor.execute("UPDATE customers SET assigned_salesperson_id = ? WHERE customer_id = ?", (new_salesperson_id, customer_id))
            conn.commit()
            return redirect(url_for('customer_detail', customer_id=customer_id))
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
            abort(500)
        finally:
            conn.close()
    else:
        abort(403)
    return redirect(url_for('login'))

@app.route('/customers/edit/<int:customer_id>', methods=['GET', 'POST'])
def edit_customer(customer_id):
    if 'salesperson_id' in session:
        conn = get_db()
        cursor = conn.cursor()

        if request.method == 'POST':
            company_name = request.form['company_name']
            contact_person = request.form['contact_person']
            phone_number = request.form['phone_number']
            email_address = request.form['email_address']
            company_address = request.form['company_address']
            lead_source = request.form['lead_source']
            initial_interest = request.form['initial_interest']
            company_industry = request.form.get('company_industry')
            contact_person_position = request.form.get('contact_person_position')

            cursor.execute('''
                UPDATE customers SET company_name=?, contact_person=?, phone_number=?, email_address=?,
                company_address=?, lead_source=?, initial_interest=?, company_industry=?, contact_person_position=?
                WHERE customer_id=?
            ''', (company_name, contact_person, phone_number, email_address, company_address, lead_source, initial_interest, company_industry, contact_person_position, customer_id))
            conn.commit()
            conn.close()
            return redirect(url_for('customer_detail', customer_id=customer_id))
        else:
            cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,))
            customer = cursor.fetchone()
            conn.close()
            if customer:
                return render_template('edit_customer.html', customer=customer)
            return render_template('edit_customer.html', customer=None)
    return redirect(url_for('login'))

@app.route('/customers/<int:customer_id>/followup/add', methods=['GET', 'POST'])
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
                return render_template('customer_detail.html', customer=None, followups=[])
                
            if request.method == 'POST':
                last_contact_date = request.form['last_contact_date']
                last_contact_method = request.form.get('last_contact_method')
                summary_last_contact = request.form.get('summary_last_contact')
                next_action = request.form.get('next_action')
                next_action_due_date = request.form.get('next_action_due_date')
                current_sales_stage = request.form.get('current_sales_stage')
                potential_deal_value = request.form.get('potential_deal_value')
                notes = request.form['notes']
                assigned_salesperson_id = session['salesperson_id']

                try:
                    # Get current time in local timezone
                    local_time = datetime.now(timezone(timedelta(hours=3)))  # Riyadh timezone (UTC+3)
                    created_at = local_time.strftime('%Y-%m-%d %H:%M:%S')

                    # Insert into sales_followup
                    cursor.execute('''
                        INSERT INTO sales_followup (
                            customer_id, last_contact_date, last_contact_method, 
                            summary_last_contact, next_action, next_action_due_date, 
                            current_sales_stage, potential_deal_value, notes, 
                            assigned_salesperson_id, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        customer_id, last_contact_date, last_contact_method,
                        summary_last_contact, next_action, next_action_due_date,
                        current_sales_stage, potential_deal_value, notes,
                        assigned_salesperson_id, created_at
                    ))
                    
                    # Update last_contact_date in customers table
                    cursor.execute("""
                        UPDATE customers 
                        SET last_contact_date = ?
                        WHERE customer_id = ?
                    """, (last_contact_date, customer_id))
                    
                    conn.commit()
                    return redirect(url_for('customer_detail', customer_id=customer_id))
                    
                except sqlite3.Error as e:
                    conn.rollback()
                    print(f"Database error: {e}")
                    return render_template('add_followup.html', 
                                         customer=customer, 
                                         error="An error occurred while saving the follow-up. Please try again.")
                    
            return render_template('add_followup.html', customer=customer)
            
        except Exception as e:
            print(f"Error: {e}")
            return render_template('add_followup.html', 
                                 customer=None, 
                                 error="An error occurred. Please try again.")
        finally:
            if conn:
                conn.close()
    return redirect(url_for('login'))

@app.route('/salespeople/<int:salesperson_id>/data')
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
                return jsonify(dict(salesperson))
            return jsonify({'error': 'Salesperson not found'}), 404
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return jsonify({'error': 'Database error'}), 500
        finally:
            conn.close()
    return jsonify({'error': 'Unauthorized'}), 403

@app.route('/salespeople/edit', methods=['POST'])
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
            return redirect(url_for('salespeople_list'))
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
            return render_template('salespeople_list.html', error="Failed to update salesperson")
        finally:
            conn.close()
    return redirect(url_for('login'))

@app.route('/salespeople/change-password', methods=['POST'])
def change_password():
    if 'salesperson_id' in session and session.get('role') == 'admin':
        conn = get_db()
        cursor = conn.cursor()
        try:
            salesperson_id = request.form['salesperson_id']
            new_password = request.form['new_password']
            hashed_password = hashlib.sha256(new_password.encode()).hexdigest()

            cursor.execute("""
                UPDATE sales_team 
                SET password = ?
                WHERE salesperson_id = ?
            """, (hashed_password, salesperson_id))
            conn.commit()
            return redirect(url_for('salespeople_list'))
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
            return render_template('salespeople_list.html', error="Failed to update password")
        finally:
            conn.close()
    return redirect(url_for('login'))

@app.route('/create-account', methods=['GET', 'POST'])
def create_account():
    if request.method == 'POST':
        first_name = request.form['first_name']
        password = request.form['password']
        salesperson_name = request.form.get('salesperson_name', first_name)
        role = request.form.get('role', 'salesperson')
        
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            # Check if user already exists
            cursor.execute("SELECT first_name FROM sales_team WHERE first_name = ?", (first_name,))
            if cursor.fetchone():
                return render_template('create_account.html', error='Username already exists')
            
            # Get the first company_id
            cursor.execute("SELECT company_id FROM companies LIMIT 1")
            company = cursor.fetchone()
            if not company:
                return render_template('create_account.html', error='No company exists')
            
            # Create new user
            hashed_password = hashlib.sha256(password.encode()).hexdigest()
            cursor.execute("""
                INSERT INTO sales_team (first_name, password, salesperson_name, role, company_id)
                VALUES (?, ?, ?, ?, ?)
            """, (first_name, hashed_password, salesperson_name, role, company['company_id']))
            
            conn.commit()
            return redirect(url_for('login'))
            
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return render_template('create_account.html', error='An error occurred while creating your account')
        finally:
            conn.close()
            
    return render_template('create_account.html')

if __name__ == '__main__':
    app.run(host='172.0.0.1', debug=True)