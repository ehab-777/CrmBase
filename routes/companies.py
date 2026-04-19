from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from tenant_utils import get_db, get_current_tenant_id, require_tenant
from activity_logger import log_activity, get_activities

companies_bp = Blueprint('companies', __name__, url_prefix='/companies')


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


def _require_login():
    return 'salesperson_id' in session


@companies_bp.route('/list')
@require_tenant
def company_list():
    if not _require_login():
        return redirect(url_for('auth.login'))

    tenant_id  = get_current_tenant_id()
    search     = request.args.get('search', '').strip()
    page       = request.args.get('page', 1, type=int)
    per_page   = 12

    conn = get_db()
    try:
        base_where = "WHERE c.tenant_id = ?"
        params = [tenant_id]
        if search:
            base_where += " AND (c.name LIKE ? OR c.industry LIKE ? OR c.email LIKE ?)"
            params += [f'%{search}%', f'%{search}%', f'%{search}%']

        total = conn.execute(
            f"SELECT COUNT(*) FROM companies c {base_where}", params
        ).fetchone()[0]

        rows = conn.execute(f"""
            SELECT c.*,
                   COUNT(DISTINCT cu.customer_id) as contact_count,
                   COUNT(DISTINCT p.id)            as project_count
            FROM companies c
            LEFT JOIN customers  cu ON cu.company_id = c.id AND cu.tenant_id = c.tenant_id
            LEFT JOIN projects   p  ON p.company_id  = c.id AND p.tenant_id  = c.tenant_id
            {base_where}
            GROUP BY c.id
            ORDER BY c.created_at DESC
            LIMIT ? OFFSET ?
        """, params + [per_page, (page - 1) * per_page]).fetchall()

    finally:
        conn.close()

    total_pages = (total + per_page - 1) // per_page
    return render_template('companies/company_list.html',
                           companies=rows,
                           search=search,
                           page=page,
                           total_pages=total_pages,
                           total=total)


@companies_bp.route('/add', methods=['GET', 'POST'])
@require_tenant
def add_company():
    if not _require_login():
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        tenant_id = get_current_tenant_id()
        conn = get_db()
        try:
            name = request.form.get('name', '').strip()
            cur = conn.execute("""
                INSERT INTO companies (name, industry, city, phone, email, address, website, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name,
                request.form.get('industry', '').strip(),
                request.form.get('city', '').strip(),
                request.form.get('phone', '').strip(),
                request.form.get('email', '').strip(),
                request.form.get('address', '').strip(),
                request.form.get('website', '').strip(),
                tenant_id
            ))
            new_company_id = cur.lastrowid
            log_activity(conn, tenant_id, 'company', new_company_id, 'created',
                         f'Company "{name}" created')
            # Auto-link any existing customers whose company_name matches
            conn.execute(
                """UPDATE customers
                   SET company_id = ?
                   WHERE LOWER(company_name) = LOWER(?) AND tenant_id = ?
                     AND (company_id IS NULL OR company_id = 0)""",
                (new_company_id, name, tenant_id)
            )
            conn.commit()
        finally:
            conn.close()
        return redirect(url_for('companies.company_list'))

    conn2 = get_db()
    try:
        config = _get_config(conn2, get_current_tenant_id(), ['industry', 'city'])
    finally:
        conn2.close()
    return render_template('companies/company_form.html', company=None, config=config)


@companies_bp.route('/<int:company_id>')
@require_tenant
def company_detail(company_id):
    if not _require_login():
        return redirect(url_for('auth.login'))

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        company = conn.execute(
            "SELECT * FROM companies WHERE id = ? AND tenant_id = ?", (company_id, tenant_id)
        ).fetchone()
        if not company:
            return redirect(url_for('companies.company_list'))

        contacts = conn.execute("""
            SELECT cu.*, COALESCE(sf.current_sales_stage, 'N/A') as stage
            FROM customers cu
            LEFT JOIN (
                SELECT customer_id, current_sales_stage
                FROM sales_followup
                WHERE tenant_id = ?
                GROUP BY customer_id HAVING MAX(created_at)
            ) sf ON sf.customer_id = cu.customer_id
            WHERE cu.company_id = ? AND cu.tenant_id = ?
        """, (tenant_id, company_id, tenant_id)).fetchall()

        projects = conn.execute(
            "SELECT * FROM projects WHERE company_id = ? AND tenant_id = ? ORDER BY created_at DESC",
            (company_id, tenant_id)
        ).fetchall()

        activities = get_activities(conn, tenant_id, 'company', company_id)

    finally:
        conn.close()

    return render_template('companies/company_detail.html',
                           company=company, contacts=contacts, projects=projects,
                           activities=activities)


@companies_bp.route('/<int:company_id>/edit', methods=['GET', 'POST'])
@require_tenant
def edit_company(company_id):
    if not _require_login():
        return redirect(url_for('auth.login'))

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        company = conn.execute(
            "SELECT * FROM companies WHERE id = ? AND tenant_id = ?", (company_id, tenant_id)
        ).fetchone()
        if not company:
            return redirect(url_for('companies.company_list'))

        if request.method == 'POST':
            conn.execute("""
                UPDATE companies SET name=?, industry=?, city=?, phone=?, email=?, address=?, website=?
                WHERE id = ? AND tenant_id = ?
            """, (
                request.form.get('name', '').strip(),
                request.form.get('industry', '').strip(),
                request.form.get('city', '').strip(),
                request.form.get('phone', '').strip(),
                request.form.get('email', '').strip(),
                request.form.get('address', '').strip(),
                request.form.get('website', '').strip(),
                company_id, tenant_id
            ))
            log_activity(conn, tenant_id, 'company', company_id, 'updated',
                         'Company info updated')
            conn.commit()
            return redirect(url_for('companies.company_detail', company_id=company_id))

    finally:
        conn.close()

    config = _get_config(conn, get_current_tenant_id(), ['industry', 'city'])
    return render_template('companies/company_form.html', company=company, config=config)


@companies_bp.route('/quick-add', methods=['POST'])
@require_tenant
def quick_add():
    if 'salesperson_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    data      = request.get_json(force=True, silent=True) or {}
    name      = (data.get('name') or '').strip()
    industry  = (data.get('industry') or '').strip()
    phone     = (data.get('phone') or '').strip()
    if not name:
        return jsonify({'error': 'Company name is required'}), 400
    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO companies (name, industry, phone, tenant_id) VALUES (?,?,?,?)",
            (name, industry, phone, tenant_id)
        )
        conn.commit()
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return jsonify({'company_id': cid, 'name': name}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@companies_bp.route('/<int:company_id>/delete', methods=['POST'])
@require_tenant
def delete_company(company_id):
    if not _require_login():
        return redirect(url_for('auth.login'))

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        conn.execute("UPDATE customers SET company_id = NULL WHERE company_id = ? AND tenant_id = ?",
                     (company_id, tenant_id))
        conn.execute("DELETE FROM companies WHERE id = ? AND tenant_id = ?", (company_id, tenant_id))
        conn.commit()
        return jsonify({'success': True})
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()
