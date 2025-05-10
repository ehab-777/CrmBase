from flask import Blueprint, render_template, request, redirect, url_for, session, abort, jsonify
import sqlite3
from datetime import datetime, date, timedelta, timezone
from tenant_utils import get_db, get_current_tenant_id, add_tenant_filter, require_tenant
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create a Blueprint for customer routes
customers_bp = Blueprint('customers', __name__, url_prefix='/customers')

@customers_bp.route('/list')
@require_tenant
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
            WITH latest_followup AS (
                SELECT 
                    customer_id,
                    current_sales_stage,
                    created_at,
                    followup_id
                FROM sales_followup
                WHERE tenant_id = ?
                GROUP BY customer_id
                HAVING MAX(created_at) = created_at AND MAX(followup_id) = followup_id
            )
            SELECT 
                c.*, 
                st.salesperson_name,
                COALESCE(lf.current_sales_stage, 'N/A') as current_sales_stage,
                (
                    SELECT sf.potential_deal_value
                    FROM sales_followup sf 
                    WHERE sf.customer_id = c.customer_id 
                    AND sf.tenant_id = c.tenant_id
                    ORDER BY sf.created_at DESC, sf.followup_id DESC 
                    LIMIT 1
                ) as potential_value,
                (
                    SELECT datetime(sf.created_at, 'localtime')
                    FROM sales_followup sf 
                    WHERE sf.customer_id = c.customer_id 
                    AND sf.tenant_id = c.tenant_id
                    AND sf.created_at IS NOT NULL
                    ORDER BY sf.created_at DESC, sf.followup_id DESC 
                    LIMIT 1
                ) as last_contact_date
            FROM customers c
            LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
            LEFT JOIN latest_followup lf ON c.customer_id = lf.customer_id
            WHERE c.tenant_id = ?
        '''
        params = [get_current_tenant_id(), get_current_tenant_id()]  # First for CTE, second for WHERE clause

        if user_role not in ['admin', 'manager']:
            query += " AND c.assigned_salesperson_id = ?"
            params.append(salesperson_id)

        stage_filter = request.args.get('stage')
        if stage_filter:
            if stage_filter == 'N/A':
                query += """
                    AND NOT EXISTS (
                        SELECT 1
                        FROM sales_followup sf
                        WHERE sf.customer_id = c.customer_id
                        AND sf.tenant_id = c.tenant_id
                        AND sf.current_sales_stage IS NOT NULL
                    )
                """
            else:
                query += """
                    AND EXISTS (
                        SELECT 1
                        FROM sales_followup sf
                        WHERE sf.customer_id = c.customer_id
                        AND sf.tenant_id = c.tenant_id
                        AND sf.current_sales_stage = ?
                        AND sf.created_at = (
                            SELECT MAX(created_at)
                            FROM sales_followup
                            WHERE customer_id = c.customer_id
                            AND tenant_id = c.tenant_id
                        )
                    )
                """
                params.append(stage_filter)

        if search_term:
            search_term_lower = f"%{search_term.lower()}%"
            query += """
                AND (LOWER(c.company_name) LIKE ? OR 
                     LOWER(c.contact_person) LIKE ? OR 
                     LOWER(c.phone_number) LIKE ? OR
                     LOWER(st.salesperson_name) LIKE ? OR
                     EXISTS (
                         SELECT 1
                         FROM sales_followup sf_search
                         WHERE sf_search.customer_id = c.customer_id
                           AND sf_search.tenant_id = c.tenant_id
                           AND LOWER(sf_search.current_sales_stage) LIKE ?
                     ))
            """
            params.extend([search_term_lower] * 5)

        if sort_by:
            sort_by_lower = sort_by.lower()
            allowed_columns = ['customer_id', 'company_name', 'contact_person', 'phone_number', 'date_added', 'last_contact_date', 'current_sales_stage', 'salesperson_name']
            if sort_by_lower in allowed_columns:
                if sort_by_lower == 'current_sales_stage':
                    query += f" ORDER BY COALESCE(lf.current_sales_stage, 'N/A') {order}"
                elif sort_by_lower == 'salesperson_name':
                    query += f" ORDER BY LOWER(st.salesperson_name) {order}"
                else:
                    query += f" ORDER BY LOWER(c.{sort_by_lower}) {order}"
            else:
                query += """
                    ORDER BY 
                        CASE 
                            WHEN last_contact_date IS NULL THEN '1970-01-01 00:00:00'
                            ELSE last_contact_date
                        END DESC,
                        c.customer_id DESC
                """

        # Add pagination
        query += " LIMIT ? OFFSET ?"
        params.extend([per_page, (page - 1) * per_page])

        # Execute the count query with only the necessary parameters
        count_params = [get_current_tenant_id(), get_current_tenant_id()]  # First for CTE, second for WHERE clause
        if user_role not in ['admin', 'manager']:
            count_params.append(salesperson_id)
        if stage_filter and stage_filter != 'N/A':
            count_params.append(stage_filter)
        if search_term:
            count_params.extend([search_term_lower] * 5)

        count_query = """
            WITH latest_followup AS (
                SELECT 
                    customer_id,
                    current_sales_stage,
                    created_at,
                    followup_id
                FROM sales_followup
                WHERE tenant_id = ?
                GROUP BY customer_id
                HAVING MAX(created_at) = created_at AND MAX(followup_id) = followup_id
            )
            SELECT COUNT(DISTINCT c.customer_id) 
            FROM customers c
            LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
            LEFT JOIN latest_followup lf ON c.customer_id = lf.customer_id
            WHERE c.tenant_id = ?
        """

        if user_role not in ['admin', 'manager']:
            count_query += " AND c.assigned_salesperson_id = ?"

        if stage_filter:
            if stage_filter == 'N/A':
                count_query += """
                    AND NOT EXISTS (
                        SELECT 1
                        FROM sales_followup sf
                        WHERE sf.customer_id = c.customer_id
                        AND sf.tenant_id = c.tenant_id
                        AND sf.current_sales_stage IS NOT NULL
                    )
                """
            else:
                count_query += """
                    AND EXISTS (
                        SELECT 1
                        FROM sales_followup sf
                        WHERE sf.customer_id = c.customer_id
                        AND sf.tenant_id = c.tenant_id
                        AND sf.current_sales_stage = ?
                        AND sf.created_at = (
                            SELECT MAX(created_at)
                            FROM sales_followup
                            WHERE customer_id = c.customer_id
                            AND tenant_id = c.tenant_id
                        )
                    )
                """

        if search_term:
            count_query += """
                AND (LOWER(c.company_name) LIKE ? OR 
                     LOWER(c.contact_person) LIKE ? OR 
                     LOWER(c.phone_number) LIKE ? OR
                     LOWER(st.salesperson_name) LIKE ? OR
                     EXISTS (
                         SELECT 1
                         FROM sales_followup sf_search
                         WHERE sf_search.customer_id = c.customer_id
                           AND sf_search.tenant_id = c.tenant_id
                           AND LOWER(sf_search.current_sales_stage) LIKE ?
                     ))
            """

        cursor.execute(count_query, count_params)
        total_customers = cursor.fetchone()[0]
        total_pages = (total_customers + per_page - 1) // per_page

        # Execute the main query
        cursor.execute(query, params)
        customers = cursor.fetchall()

        # Get all available sales stages
        cursor.execute("SELECT DISTINCT current_sales_stage FROM sales_followup WHERE current_sales_stage IS NOT NULL")
        sales_stages = [row['current_sales_stage'] for row in cursor.fetchall()]
        # Add 'N/A' to the list of sales stages if it's not already there
        if 'N/A' not in sales_stages:
            sales_stages.append('N/A')

        conn.close()
        return render_template('customers/customer_list.html', 
                             customers=customers, 
                             search_term=search_term,
                             sort_by=sort_by, 
                             order=order, 
                             page=page, 
                             total_pages=total_pages,
                             sales_stages=sales_stages,
                             current_stage=request.args.get('stage', ''))
    return redirect(url_for('auth.login'))

@customers_bp.route('/add', methods=['GET', 'POST'])
@require_tenant
def add_customer():
    if 'salesperson_id' in session:
        salesperson_id = session['salesperson_id']
        user_role = session.get('role')
        conn = get_db()
        cursor = conn.cursor()
        error = None

        # Fetch all salespeople for the dropdown (for managers and admins)
        base_query = "SELECT salesperson_id, first_name as salesperson_name FROM sales_team"
        query, params = add_tenant_filter(base_query)
        cursor.execute(query, params)
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

            if user_role in ['manager', 'admin']:
                assigned_salesperson_id = request.form.get('assigned_salesperson_id', salesperson_id)

            try:
                cursor.execute('''
                    INSERT INTO customers (
                        company_name, company_industry, contact_person,
                        contact_person_position, phone_number, email_address,
                        company_address, lead_source, initial_interest,
                        date_added, assigned_salesperson_id, tenant_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    company_name, company_industry, contact_person,
                    contact_person_position, phone_number, email_address,
                    company_address, lead_source, initial_interest,
                    date_added, assigned_salesperson_id, get_current_tenant_id()
                ))
                customer_id = cursor.lastrowid
                conn.commit()
                return redirect(url_for('customers.customer_detail', customer_id=customer_id))
            except sqlite3.Error as e:
                conn.rollback()
                error = f"Database error during add_customer: {e}"
                print(error)
                return render_template('customers/add_customer.html', error=error, salespeople=all_salespeople)

        return render_template('customers/add_customer.html', error=error, salespeople=all_salespeople)
    return redirect(url_for('auth.login'))

@customers_bp.route('/<int:customer_id>')
@require_tenant
def customer_detail(customer_id):
    if 'salesperson_id' in session:
        conn = get_db()
        cursor = conn.cursor()
        customer = None
        followups = []
        is_admin = session.get('role') == 'admin'
        page = request.args.get('page', 1, type=int)
        per_page = 12
        total_pages = 1  # Initialize with default value

        try:
            # Get customer details
            cursor.execute("""
                SELECT c.*, st.salesperson_name,
                    COALESCE(
                        (SELECT sf.current_sales_stage 
                         FROM sales_followup sf 
                         WHERE sf.customer_id = c.customer_id 
                         AND sf.tenant_id = c.tenant_id
                         ORDER BY sf.created_at DESC, sf.followup_id DESC 
                         LIMIT 1),
                        'عميل محتمل'
                    ) as current_sales_stage,
                    CASE 
                        WHEN (
                            SELECT sf.current_sales_stage 
                            FROM sales_followup sf 
                            WHERE sf.customer_id = c.customer_id 
                            AND sf.tenant_id = c.tenant_id
                            ORDER BY sf.created_at DESC, sf.followup_id DESC 
                            LIMIT 1
                        ) IN ('عميل محتمل', 'تقديم عرض السعر', 'جاري التواصل', 'جاري التفاوض') THEN 'Active'
                        WHEN (
                            SELECT sf.current_sales_stage 
                            FROM sales_followup sf 
                            WHERE sf.customer_id = c.customer_id 
                            AND sf.tenant_id = c.tenant_id
                            ORDER BY sf.created_at DESC, sf.followup_id DESC 
                            LIMIT 1
                        ) = 'تم التسليم' THEN 'Close Won'
                        WHEN (
                            SELECT sf.current_sales_stage 
                            FROM sales_followup sf 
                            WHERE sf.customer_id = c.customer_id 
                            AND sf.tenant_id = c.tenant_id
                            ORDER BY sf.created_at DESC, sf.followup_id DESC 
                            LIMIT 1
                        ) = 'لم يتم البيع' THEN 'Close Lost'
                        ELSE 'Unknown'
                    END as status,
                    COALESCE(
                        (SELECT sf.potential_deal_value
                         FROM sales_followup sf 
                         WHERE sf.customer_id = c.customer_id 
                         AND sf.tenant_id = c.tenant_id
                         ORDER BY sf.created_at DESC, sf.followup_id DESC 
                         LIMIT 1),
                        0
                    ) as latest_potential_value,
                    COALESCE(
                        (SELECT sf.next_action
                         FROM sales_followup sf 
                         WHERE sf.customer_id = c.customer_id 
                         AND sf.tenant_id = c.tenant_id
                         ORDER BY sf.created_at ASC, sf.followup_id ASC 
                         LIMIT 1),
                        NULL
                    ) as next_action,
                    COALESCE(
                        (SELECT sf.next_action_due_date
                         FROM sales_followup sf 
                         WHERE sf.customer_id = c.customer_id 
                         AND sf.tenant_id = c.tenant_id
                         ORDER BY sf.created_at ASC, sf.followup_id ASC 
                         LIMIT 1),
                        NULL
                    ) as next_action_due_date
                FROM customers c
                LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
                WHERE c.customer_id = ? AND c.tenant_id = ?
            """, (customer_id, get_current_tenant_id()))
            customer = cursor.fetchone()

            if not customer:
                abort(404)

            # Get followups with pagination
            offset = (page - 1) * per_page
            cursor.execute("""
                SELECT sf.*, st.salesperson_name,
                       datetime(sf.created_at, 'localtime') as created_at
                FROM sales_followup sf
                LEFT JOIN sales_team st ON sf.created_by = st.salesperson_id
                WHERE sf.customer_id = ? AND sf.tenant_id = ?
                ORDER BY sf.created_at DESC, sf.followup_id DESC
                LIMIT ? OFFSET ?
            """, (customer_id, get_current_tenant_id(), per_page, offset))
            followups = cursor.fetchall()

            # Get total count for pagination
            cursor.execute("""
                SELECT COUNT(*) FROM sales_followup
                WHERE customer_id = ? AND tenant_id = ?
            """, (customer_id, get_current_tenant_id()))
            total_followups = cursor.fetchone()[0]
            total_pages = (total_followups + per_page - 1) // per_page

            conn.close()
            return render_template('customers/customer_detail.html',
                                customer=customer,
                                followups=followups,
                                page=page,
                                total_pages=total_pages,
                                is_admin=is_admin,
                                add_followup_url=url_for('follow_up.add_followup', customer_id=customer_id))

        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.close()
            return render_template('customers/customer_detail.html', 
                                customer=customer, 
                                followups=followups, 
                                is_admin=is_admin,
                                page=page,
                                total_pages=total_pages)
    return redirect(url_for('auth.login'))

@customers_bp.route('/edit/<int:customer_id>', methods=['GET', 'POST'])
@require_tenant
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

            # Always keep the original creator as assigned_salesperson_id
            cursor.execute("SELECT assigned_salesperson_id FROM customers WHERE customer_id = ?", (customer_id,))
            assigned_salesperson_id = cursor.fetchone()['assigned_salesperson_id']

            cursor.execute('''
                UPDATE customers SET company_name=?, contact_person=?, phone_number=?, email_address=?,
                company_address=?, lead_source=?, initial_interest=?, company_industry=?, contact_person_position=?, assigned_salesperson_id=?
                WHERE customer_id=?
            ''', (company_name, contact_person, phone_number, email_address, company_address, lead_source, initial_interest, company_industry, contact_person_position, assigned_salesperson_id, customer_id))
            conn.commit()
            conn.close()
            return redirect(url_for('customers.customer_detail', customer_id=customer_id))
        else:
            cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,))
            customer = cursor.fetchone()
            conn.close()
            if customer:
                return render_template('customers/edit_customer.html', customer=customer)
            return render_template('customers/edit_customer.html', customer=None)
    return redirect(url_for('auth.login'))

@customers_bp.route('/assign/<int:customer_id>', methods=['GET', 'POST'])
@require_tenant
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
                return redirect(url_for('customers.customer_detail', customer_id=customer_id))

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

            return render_template('customers/assign_customer.html', customer=customer, salespeople=salespeople, current_assigned_id=current_assigned_id)

        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
            abort(500)
        finally:
            conn.close()
    else:
        abort(403)
    return redirect(url_for('auth.login'))

@customers_bp.route('/assign/submit', methods=['POST'])
@require_tenant
def assign_customer_submit():
    if 'salesperson_id' in session and session.get('role') == 'admin':
        new_salesperson_id = request.form.get('salesperson_id')
        conn = get_db()
        cursor = conn.cursor()

        try:
            cursor.execute("UPDATE customers SET assigned_salesperson_id = ? WHERE customer_id = ?", (new_salesperson_id, request.form.get('customer_id')))
            conn.commit()
            return redirect(url_for('customers.customer_detail', customer_id=request.form.get('customer_id')))
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
            abort(500)
        finally:
            conn.close()
    else:
        abort(403)
    return redirect(url_for('auth.login')) 