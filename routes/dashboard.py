from flask import Blueprint, render_template, request, redirect, url_for, session
import sqlite3
from tenant_utils import get_db, get_current_tenant_id, require_tenant
from datetime import datetime

# Create a Blueprint for dashboard routes
dashboard_bp = Blueprint('dashboard', __name__, url_prefix='')

@dashboard_bp.route('/dashboard')
@require_tenant
def dashboard():
    if 'salesperson_id' in session:
        salesperson_id = session['salesperson_id']
        conn = get_db()
        cursor = conn.cursor()
        
        # Get total customers for the logged-in user
        cursor.execute("SELECT COUNT(*) FROM customers WHERE assigned_salesperson_id = ?", (salesperson_id,))
        total_customers = cursor.fetchone()[0]
        
        # Get active customers count and total potential value
        cursor.execute("""
            WITH latest_followup AS (
                SELECT 
                    customer_id,
                    current_sales_stage,
                    potential_deal_value,
                    created_at,
                    followup_id
                FROM sales_followup
                WHERE tenant_id = ?
                GROUP BY customer_id
                HAVING MAX(created_at) = created_at AND MAX(followup_id) = followup_id
            )
            SELECT 
                COUNT(DISTINCT CASE 
                    WHEN COALESCE(lf.current_sales_stage, 'عميل محتمل') IN ('عميل محتمل', 'تقديم عرض السعر', 'جاري التواصل', 'جاري التفاوض') 
                    THEN c.customer_id 
                END) as active_count,
                COUNT(DISTINCT CASE 
                    WHEN lf.current_sales_stage = 'تم التسليم' 
                    THEN c.customer_id 
                END) as won_count,
                COUNT(DISTINCT CASE 
                    WHEN lf.current_sales_stage = 'لم يتم البيع' 
                    THEN c.customer_id 
                END) as lost_count,
                COALESCE(SUM(CASE 
                    WHEN COALESCE(lf.current_sales_stage, 'عميل محتمل') IN ('عميل محتمل', 'تقديم عرض السعر', 'جاري التواصل', 'جاري التفاوض')
                    THEN COALESCE(lf.potential_deal_value, 0)
                    ELSE 0 
                END), 0) as active_value,
                COALESCE(SUM(CASE 
                    WHEN lf.current_sales_stage = 'تم التسليم'
                    THEN COALESCE(lf.potential_deal_value, 0)
                    ELSE 0 
                END), 0) as won_value,
                COALESCE(SUM(CASE 
                    WHEN lf.current_sales_stage = 'لم يتم البيع'
                    THEN COALESCE(lf.potential_deal_value, 0)
                    ELSE 0 
                END), 0) as lost_value
            FROM customers c
            LEFT JOIN latest_followup lf ON c.customer_id = lf.customer_id
            WHERE c.assigned_salesperson_id = ?
        """, (get_current_tenant_id(), salesperson_id))
        
        metrics = cursor.fetchone()
        status_counts = {
            'Active': {'count': metrics['active_count'], 'value': metrics['active_value']},
            'Close Won': {'count': metrics['won_count'], 'value': metrics['won_value']},
            'Close Lost': {'count': metrics['lost_count'], 'value': metrics['lost_value']}
        }
        total_potential_value = metrics['active_value']
        
        # Get customer names and their recent deal values
        cursor.execute("""
            WITH latest_followup AS (
                SELECT 
                    customer_id,
                    MAX(created_at) as max_date,
                    MAX(followup_id) as max_id
                FROM sales_followup
                GROUP BY customer_id
            )
            SELECT 
                c.customer_id,
                c.company_name,
                COALESCE(sf.potential_deal_value, 0) as deal_value
            FROM customers c
            LEFT JOIN sales_followup sf ON c.customer_id = sf.customer_id
            LEFT JOIN latest_followup lf ON sf.customer_id = lf.customer_id 
                AND sf.created_at = lf.max_date
                AND sf.followup_id = lf.max_id
            WHERE c.assigned_salesperson_id = ?
            AND sf.current_sales_stage IN ('عميل محتمل', 'تقديم عرض السعر', 'جاري التواصل', 'جاري التفاوض')
            ORDER BY COALESCE(sf.potential_deal_value, 0) DESC, c.company_name
        """, (salesperson_id,))
        open_leads = cursor.fetchall()
        
        # Get sales pipeline data
        cursor.execute("""
            WITH latest_followup AS (
                SELECT 
                    customer_id,
                    MAX(created_at) as max_date,
                    MAX(followup_id) as max_id
                FROM sales_followup
                GROUP BY customer_id
            )
            SELECT DISTINCT
                COALESCE(sf.current_sales_stage, 'عميل محتمل') as current_sales_stage,
                c.customer_id,
                c.company_name as company,
                sf.last_contact_date,
                sf.summary_last_contact as summary,
                sf.potential_deal_value as deal_value
            FROM customers c
            LEFT JOIN latest_followup lf ON c.customer_id = lf.customer_id
            LEFT JOIN sales_followup sf ON sf.customer_id = lf.customer_id 
                AND sf.created_at = lf.max_date
                AND sf.followup_id = lf.max_id
            WHERE c.assigned_salesperson_id = ?
            GROUP BY c.customer_id
            ORDER BY 
                CASE 
                    WHEN COALESCE(sf.current_sales_stage, 'عميل محتمل') = 'عميل محتمل' THEN 1
                    WHEN COALESCE(sf.current_sales_stage, 'عميل محتمل') = 'تقديم عرض السعر' THEN 2
                    WHEN COALESCE(sf.current_sales_stage, 'عميل محتمل') = 'جاري التواصل' THEN 3
                    WHEN COALESCE(sf.current_sales_stage, 'عميل محتمل') = 'جاري التفاوض' THEN 4
                    WHEN COALESCE(sf.current_sales_stage, 'عميل محتمل') = 'تم التسليم' THEN 5
                    WHEN COALESCE(sf.current_sales_stage, 'عميل محتمل') = 'لم يتم البيع' THEN 6
                    ELSE 7
                END,
                c.company_name
        """, (salesperson_id,))
        
        sales_pipeline = {}
        for row in cursor.fetchall():
            stage = row['current_sales_stage']
            if stage not in sales_pipeline:
                sales_pipeline[stage] = []
            sales_pipeline[stage].append({
                'customer_id': row['customer_id'],
                'company': row['company'],
                'last_contact_date': row['last_contact_date'],
                'summary': row['summary'],
                'deal_value': row['deal_value']
            })
        
        # Get recent follow-ups
        cursor.execute("""
            SELECT sf.*, c.company_name
            FROM sales_followup sf
            JOIN customers c ON sf.customer_id = c.customer_id
            WHERE c.assigned_salesperson_id = ?
            ORDER BY sf.last_contact_date DESC
            LIMIT 5
        """, (salesperson_id,))
        recent_followups = cursor.fetchall()
        
        # Get upcoming follow-ups categorized by time period
        today = datetime.now().strftime('%Y-%m-%d')
        tenant_id = get_current_tenant_id()
        cursor.execute("""
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
            ),
            upcoming_followups AS (
                SELECT 
                    sf.*,
                    c.company_name,
                    CASE 
                        WHEN sf.next_action_due_date = ? THEN 'today'
                        WHEN sf.next_action_due_date BETWEEN date(?, '+1 day') AND date(?, '+7 days') THEN 'this_week'
                        WHEN sf.next_action_due_date BETWEEN date(?, '+8 days') AND date(?, '+14 days') THEN 'next_week'
                        ELSE 'later'
                    END as time_period
                FROM sales_followup sf
                JOIN customers c ON sf.customer_id = c.customer_id
                LEFT JOIN latest_followup lf ON c.customer_id = lf.customer_id
                WHERE c.assigned_salesperson_id = ?
                AND sf.tenant_id = ?
                AND sf.next_action_due_date >= ?
                AND sf.next_action != 'إغلاق البيع'
                AND COALESCE(lf.current_sales_stage, 'عميل محتمل') NOT IN ('تم التسليم', 'لم يتم البيع')
                ORDER BY sf.next_action_due_date ASC
            )
            SELECT * FROM upcoming_followups
        """, (tenant_id, today, today, today, today, today, salesperson_id, tenant_id, today))
        
        followups = cursor.fetchall()
        
        # Categorize follow-ups
        followups_today = [f for f in followups if f['time_period'] == 'today']
        followups_this_week = [f for f in followups if f['time_period'] == 'this_week']
        followups_next_week = [f for f in followups if f['time_period'] == 'next_week']
        followups_later = [f for f in followups if f['time_period'] == 'later']
        
        conn.close()
        return render_template('dashboard/dashboard.html',
                             total_customers=total_customers,
                             status_counts=status_counts,
                             total_potential_value=total_potential_value,
                             open_leads=open_leads,
                             sales_pipeline=sales_pipeline,
                             followups_today=followups_today,
                             followups_this_week=followups_this_week,
                             followups_next_week=followups_next_week,
                             followups_later=followups_later,
                             salesperson_name=session.get('salesperson_name', 'User'))
    return redirect(url_for('auth.login'))

@dashboard_bp.route('/manager/dashboard')
@require_tenant
def manager_dashboard():
    try:
        if 'salesperson_id' in session and session.get('role') in ['admin', 'manager']:
            # Get and validate pagination parameters
            try:
                page = max(1, int(request.args.get('page', 1)))
                per_page = 4  # Number of items per page
            except ValueError:
                page = 1
                per_page = 4

            # Get and validate filter parameters
            salesperson_id = request.args.get('salesperson_id')
            if salesperson_id:
                try:
                    salesperson_id = int(salesperson_id)
                except ValueError:
                    salesperson_id = None

            stage = request.args.get('stage', '')
            search = request.args.get('search', '').strip()
            tenant_id = get_current_tenant_id()
            
            conn = get_db()
            cursor = conn.cursor()
            
            # Get all salespeople for the filter dropdown
            cursor.execute("""
                SELECT salesperson_id, first_name
                FROM sales_team
                WHERE tenant_id = ?
                ORDER BY first_name
            """, (tenant_id,))
            salespeople = cursor.fetchall()
            
            # Get all available sales stages
            cursor.execute("""
                SELECT DISTINCT current_sales_stage
                FROM sales_followup
                WHERE tenant_id = ?
                AND current_sales_stage IS NOT NULL
                ORDER BY current_sales_stage
            """, (tenant_id,))
            sales_stages = [row['current_sales_stage'] for row in cursor.fetchall()]
            
            # Build the base query with filters
            base_query = """
                SELECT 
                    c.*, 
                    st.first_name as assigned_salesperson,
                    COALESCE(
                        (SELECT sf.current_sales_stage 
                         FROM sales_followup sf 
                         WHERE sf.customer_id = c.customer_id 
                         AND sf.tenant_id = c.tenant_id
                         ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                         LIMIT 1),
                        'عميل محتمل'
                    ) as current_sales_stage,
                    COALESCE(
                        (SELECT sf.next_action_due_date
                         FROM sales_followup sf 
                         WHERE sf.customer_id = c.customer_id 
                         AND sf.tenant_id = c.tenant_id
                         ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                         LIMIT 1),
                        NULL
                    ) as next_followup_date
                FROM customers c
                LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
                WHERE c.tenant_id = ?
            """
            
            # Build where clause
            where_clause = []
            params = [tenant_id]
            
            # Re-enable salesperson and stage filters
            if salesperson_id and salesperson_id != '':
                where_clause.append("c.assigned_salesperson_id = ?")
                params.append(salesperson_id)
                
            if stage and stage != '':
                if stage == 'عميل محتمل':
                    where_clause.append("""
                        COALESCE(
                            (SELECT sf.current_sales_stage 
                             FROM sales_followup sf 
                             WHERE sf.customer_id = c.customer_id 
                             AND sf.tenant_id = c.tenant_id
                             ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                             LIMIT 1),
                            'عميل محتمل'
                        ) = ?
                    """)
                else:
                    where_clause.append("""
                        COALESCE(
                            (SELECT sf.current_sales_stage 
                             FROM sales_followup sf 
                             WHERE sf.customer_id = c.customer_id 
                             AND sf.tenant_id = c.tenant_id
                             ORDER BY sf.last_contact_date DESC, sf.followup_id DESC 
                             LIMIT 1),
                            'عميل محتمل'
                        ) = ?
                    """)
                params.append(stage)
                
            if search:
                search_term = f"%{search.lower()}%"
                where_clause.append("""
                    (LOWER(c.company_name) LIKE ? OR 
                     LOWER(c.contact_person) LIKE ? OR 
                     LOWER(c.phone_number) LIKE ? OR
                     LOWER(st.first_name) LIKE ? OR
                     EXISTS (
                         SELECT 1
                         FROM sales_followup sf_search
                         WHERE sf_search.customer_id = c.customer_id
                         AND sf_search.tenant_id = c.tenant_id
                         AND LOWER(sf_search.current_sales_stage) LIKE ?
                     ))
                """)
                params.extend([search_term, search_term, search_term, search_term, search_term])
            
            # Add where clause if needed
            if where_clause:
                base_query += " AND " + " AND ".join(where_clause)
            
            # Add ordering and pagination
            base_query += " ORDER BY c.date_added DESC LIMIT ? OFFSET ?"
            params.extend([per_page, (page - 1) * per_page])
            
            # Get total count for pagination
            count_query = "SELECT COUNT(*) FROM customers c LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id WHERE c.tenant_id = ?"
            if where_clause:
                count_query += " AND " + " AND ".join(where_clause)
            cursor.execute(count_query, params[:-2])  # Exclude LIMIT and OFFSET params
            total_customers = cursor.fetchone()[0]
            total_pages = (total_customers + per_page - 1) // per_page
            
            # Execute the main query
            cursor.execute(base_query, params)
            customers = cursor.fetchall()
            
            # Get sales stage counts with deal_value
            sales_stage_query = """
                WITH latest_followup AS (
                    SELECT 
                        customer_id,
                        MAX(last_contact_date) as max_date,
                        MAX(followup_id) as max_id
                    FROM sales_followup
                    WHERE tenant_id = ?
                    GROUP BY customer_id
                )
                SELECT 
                    COALESCE(sf.current_sales_stage, 'عميل محتمل') as current_sales_stage,
                    COUNT(*) as count,
                    COALESCE(SUM(sf.potential_deal_value), 0) as total_value
                FROM customers c
                LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
                LEFT JOIN latest_followup lf ON c.customer_id = lf.customer_id
                LEFT JOIN sales_followup sf ON sf.customer_id = lf.customer_id 
                    AND sf.last_contact_date = lf.max_date
                    AND sf.followup_id = lf.max_id
                WHERE c.tenant_id = ?
            """
            
            sales_stage_params = [tenant_id, tenant_id]
            
            # Re-enable salesperson and stage filters for sales stage query
            if salesperson_id:
                sales_stage_query += " AND c.assigned_salesperson_id = ?"
                sales_stage_params.append(salesperson_id)
                
            if stage and stage != '':
                sales_stage_query += " AND COALESCE(sf.current_sales_stage, 'عميل محتمل') = ?"
                sales_stage_params.append(stage)
                
            if search:
                search_term = f"%{search.lower()}%"
                sales_stage_query += """
                    AND (LOWER(c.company_name) LIKE ? OR 
                         LOWER(c.contact_person) LIKE ? OR 
                         LOWER(c.phone_number) LIKE ? OR
                         LOWER(st.first_name) LIKE ?)
                """
                sales_stage_params.extend([search_term, search_term, search_term, search_term])
            
            sales_stage_query += " GROUP BY COALESCE(sf.current_sales_stage, 'عميل محتمل')"
            
            cursor.execute(sales_stage_query, sales_stage_params)
            
            sales_stage_counts = {}
            for row in cursor.fetchall():
                sales_stage_counts[row['current_sales_stage']] = {
                    'count': int(row['count']),
                    'total_value': float(row['total_value']) if row['total_value'] is not None else 0.0
                }
            
            # Calculate percentages
            for stage in sales_stage_counts:
                if total_customers > 0:  # Avoid division by zero
                    percentage = (float(sales_stage_counts[stage]['count']) / float(total_customers)) * 100
                    sales_stage_counts[stage]['percentage'] = f"{percentage:.1f}%"
                else:
                    sales_stage_counts[stage]['percentage'] = "0.0%"
            
            # Get pipeline data by stage
            pipeline_query = """
                WITH latest_followup AS (
                    SELECT 
                        customer_id,
                        MAX(last_contact_date) as max_date,
                        MAX(followup_id) as max_id
                    FROM sales_followup
                    WHERE tenant_id = ?
                    GROUP BY customer_id
                ),
                base_customers AS (
                    SELECT 
                        c.customer_id,
                        c.company_name,
                        c.contact_person,
                        c.phone_number,
                        c.assigned_salesperson_id,
                        st.first_name as salesperson_name,
                        COALESCE(sf.current_sales_stage, 'عميل محتمل') as current_sales_stage,
                        sf.potential_deal_value,
                        sf.next_action,
                        sf.next_action_due_date,
                        sf.last_contact_date,
                        sf.summary_last_contact,
                        (
                            SELECT COUNT(*) 
                            FROM sales_followup sf2 
                            WHERE sf2.customer_id = c.customer_id
                            AND sf2.tenant_id = c.tenant_id
                        ) as followup_count,
                        (
                            SELECT COUNT(*) 
                            FROM sales_followup sf3 
                            WHERE sf3.customer_id = c.customer_id
                            AND sf3.tenant_id = c.tenant_id
                        ) as followup_transactions
                    FROM customers c
                    LEFT JOIN sales_team st ON c.assigned_salesperson_id = st.salesperson_id
                    LEFT JOIN latest_followup lf ON c.customer_id = lf.customer_id
                    LEFT JOIN sales_followup sf ON sf.customer_id = lf.customer_id 
                        AND sf.last_contact_date = lf.max_date
                        AND sf.followup_id = lf.max_id
                        AND sf.tenant_id = c.tenant_id
                    WHERE c.tenant_id = ?
                ),
                filtered_customers AS (
                    SELECT *
                    FROM base_customers
                    WHERE 1=1
            """
            
            pipeline_params = [tenant_id, tenant_id]
            
            # Apply salesperson filter only if a specific salesperson is selected
            if salesperson_id and salesperson_id != '':
                pipeline_query += " AND assigned_salesperson_id = ?"
                pipeline_params.append(salesperson_id)
            
            # Remove stage filter from pipeline query completely
            # Apply search filter
            if search:
                search_term = f"%{search.lower()}%"
                pipeline_query += """
                    AND (
                        LOWER(company_name) LIKE ? OR 
                        LOWER(contact_person) LIKE ? OR 
                        LOWER(phone_number) LIKE ? OR
                        LOWER(salesperson_name) LIKE ? OR
                        LOWER(current_sales_stage) LIKE ?
                    )
                """
                pipeline_params.extend([search_term, search_term, search_term, search_term, search_term])
            
            pipeline_query += """
                )
                SELECT 
                    current_sales_stage,
                    customer_id,
                    company_name as company,
                    contact_person,
                    phone_number,
                    salesperson_name as salesperson,
                    next_action,
                    next_action_due_date,
                    last_contact_date,
                    summary_last_contact as summary,
                    COALESCE(potential_deal_value, 0) as deal_value,
                    followup_count,
                    followup_transactions,
                    CASE 
                        WHEN current_sales_stage = ? THEN 0
                        ELSE 1
                    END as sort_order
                FROM filtered_customers
                WHERE 1=1
            """
            
            # Add the stage parameter for sorting
            pipeline_params.append(stage if stage else '')
            
            pipeline_query += " ORDER BY sort_order, current_sales_stage, company_name"
            
            try:
                cursor.execute(pipeline_query, pipeline_params)
            except Exception as e:
                print(f"Error executing pipeline query: {str(e)}")
                print(f"Query: {pipeline_query}")
                print(f"Params: {pipeline_params}")
                raise
            
            pipeline_by_stage = {}
            for row in cursor.fetchall():
                stage = row['current_sales_stage']
                if stage not in pipeline_by_stage:
                    pipeline_by_stage[stage] = {
                        'companies': [],
                        'total_value': 0.0  # Initialize as float
                    }
                
                # Handle NULL or empty deal_value
                deal_value = float(row['deal_value']) if row['deal_value'] is not None and row['deal_value'] != '' else 0.0
                
                pipeline_by_stage[stage]['companies'].append({
                    'customer_id': row['customer_id'],
                    'company': row['company'],
                    'contact_person': row['contact_person'],
                    'phone_number': row['phone_number'],
                    'salesperson': row['salesperson'],
                    'next_action': row['next_action'],
                    'next_action_date': row['next_action_due_date'],
                    'last_contact_date': row['last_contact_date'],
                    'summary': row['summary'],
                    'deal_value': deal_value,
                    'followup_count': row['followup_count']
                })
                
                # Update total value for the stage
                pipeline_by_stage[stage]['total_value'] += deal_value
            
            # Calculate total potential deal value
            total_value = sum(stage['total_value'] for stage in pipeline_by_stage.values())
            
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
        return redirect(url_for('auth.login'))
    except Exception as e:
        # Log the error
        print(f"Error in manager dashboard: {str(e)}")
        # Return a user-friendly error message
        return f"An error occurred while loading the dashboard. Please try again later. Error: {str(e)}", 500 

@dashboard_bp.route('/admin/dashboard')
@require_tenant
def admin_dashboard():
    from flask import session
    if session.get('role') != 'admin':
        return redirect(url_for('auth.login'))
    return render_template('dashboard/admin_dashboard.html') 