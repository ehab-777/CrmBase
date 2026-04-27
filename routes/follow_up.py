from flask import Blueprint, render_template, request, redirect, url_for, session
from tenant_utils import get_db, get_current_tenant_id, require_tenant
from activity_logger import log_activity


def _get_config(conn, tenant_id, categories):
    result = {}
    for cat in categories:
        rows = conn.execute("""
            SELECT value, label_ar FROM config_options
            WHERE tenant_id = ? AND category = ? AND is_active = 1
            ORDER BY display_order, value
        """, (tenant_id, cat)).fetchall()
        result[cat] = rows
    return result


follow_up_bp = Blueprint('follow_up', __name__)


@follow_up_bp.route('/customers/<int:customer_id>/followup/add', methods=['GET', 'POST'])
@require_tenant
def add_followup(customer_id):
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        tenant_id = get_current_tenant_id()

        cursor.execute(
            "SELECT * FROM customers WHERE customer_id = ? AND tenant_id = ?",
            (customer_id, tenant_id)
        )
        customer = cursor.fetchone()
        if not customer:
            return redirect(url_for('customers.customer_list'))

        if request.method == 'POST':
            last_contact_method  = request.form.get('last_contact_method')
            last_contact_date    = request.form['last_contact_date']
            summary              = request.form.get('summary')
            notes                = request.form.get('notes', '')
            current_sales_stage  = request.form.get('current_sales_stage')
            potential_deal_value = request.form.get('deal_value')
            next_action          = request.form.get('next_action')
            next_action_due_date = request.form.get('next_action_date')

            company_id = None
            try:
                company_id = customer['company_id']
            except (IndexError, KeyError):
                pass

            actor = session.get('salesperson_name', '')
            details = f'Follow-up — Stage: {current_sales_stage or "—"}'

            cursor.execute("""
                INSERT INTO activities (
                    tenant_id, entity_type, entity_id, action,
                    actor_name, details,
                    activity_type, contact_date, summary, notes,
                    sales_stage, deal_value, next_action, next_action_due,
                    created_by, company_id, created_at
                ) VALUES (?, 'customer', ?, 'follow_up',
                          ?, ?,
                          ?, ?, ?, ?,
                          ?, ?, ?, ?,
                          ?, ?, datetime('now','localtime'))
            """, (
                tenant_id, customer_id,
                actor, details,
                last_contact_method, last_contact_date, summary, notes,
                current_sales_stage, potential_deal_value, next_action, next_action_due_date,
                session['salesperson_id'], company_id
            ))

            cursor.execute(
                "UPDATE customers SET current_stage = ? WHERE customer_id = ? AND tenant_id = ?",
                (current_sales_stage, customer_id, tenant_id)
            )

            if company_id:
                contact_name = customer['contact_person'] or customer['company_name'] or ''
                log_activity(conn, tenant_id, 'company', company_id, 'follow_up_added',
                             f'Follow-up for {contact_name} — Stage: {current_sales_stage or "—"}')

            conn.commit()
            return redirect(url_for('customers.customer_detail', customer_id=customer_id))

        config = _get_config(conn, tenant_id, ['contact_method', 'sales_stage', 'next_action'])
        return render_template('customers/add_followup.html', customer=customer, config=config)

    except Exception as e:
        print(f"Error in add_followup: {e}")
        return redirect(url_for('customers.customer_list'))
    finally:
        if conn:
            conn.close()


@follow_up_bp.route('/customers/<int:customer_id>/followup/<int:followup_id>/edit',
                    methods=['GET', 'POST'])
@require_tenant
def edit_followup(customer_id, followup_id):
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        tenant_id = get_current_tenant_id()

        cursor.execute(
            "SELECT * FROM customers WHERE customer_id = ? AND tenant_id = ?",
            (customer_id, tenant_id)
        )
        customer = cursor.fetchone()
        if not customer:
            return redirect(url_for('customers.customer_list'))

        cursor.execute("""
            SELECT * FROM activities
            WHERE id = ? AND entity_type = 'customer' AND entity_id = ?
              AND action = 'follow_up' AND tenant_id = ?
        """, (followup_id, customer_id, tenant_id))
        followup = cursor.fetchone()
        if not followup:
            return redirect(url_for('customers.customer_detail', customer_id=customer_id))

        if request.method == 'POST':
            last_contact_method  = request.form.get('last_contact_method')
            last_contact_date    = request.form['last_contact_date']
            summary              = request.form.get('summary')
            notes                = request.form.get('notes', '')
            current_sales_stage  = request.form.get('current_sales_stage')
            potential_deal_value = request.form.get('deal_value')
            next_action          = request.form.get('next_action')
            next_action_due_date = request.form.get('next_action_date')

            cursor.execute("""
                UPDATE activities SET
                    activity_type   = ?,
                    contact_date    = ?,
                    summary         = ?,
                    notes           = ?,
                    sales_stage     = ?,
                    deal_value      = ?,
                    next_action     = ?,
                    next_action_due = ?,
                    details         = ?,
                    updated_at      = datetime('now','localtime')
                WHERE id = ? AND entity_type = 'customer' AND entity_id = ?
                  AND action = 'follow_up' AND tenant_id = ?
            """, (
                last_contact_method, last_contact_date,
                summary, notes,
                current_sales_stage, potential_deal_value,
                next_action, next_action_due_date,
                f'Follow-up — Stage: {current_sales_stage or "—"}',
                followup_id, customer_id, tenant_id
            ))

            cursor.execute("""
                UPDATE customers SET current_stage = (
                    SELECT sales_stage FROM activities
                    WHERE entity_type = 'customer' AND entity_id = ? AND action = 'follow_up'
                      AND tenant_id = ?
                    ORDER BY created_at DESC, id DESC LIMIT 1
                ) WHERE customer_id = ? AND tenant_id = ?
            """, (customer_id, tenant_id, customer_id, tenant_id))

            log_activity(conn, tenant_id, 'customer', customer_id, 'updated',
                         f'Follow-up edited — Stage: {current_sales_stage or "—"}')
            conn.commit()
            return redirect(url_for('customers.customer_detail', customer_id=customer_id))

        config = _get_config(conn, tenant_id, ['contact_method', 'sales_stage', 'next_action'])
        return render_template('customers/edit_followup.html',
                               customer=customer, followup=followup, config=config)

    except Exception as e:
        print(f"Error in edit_followup: {e}")
        return redirect(url_for('customers.customer_detail', customer_id=customer_id))
    finally:
        if conn:
            conn.close()
