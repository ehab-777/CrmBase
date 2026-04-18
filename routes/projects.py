from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from tenant_utils import get_db, get_current_tenant_id, require_tenant

projects_bp = Blueprint('projects', __name__, url_prefix='/projects')


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


@projects_bp.route('/list')
@require_tenant
def project_list():
    if not _require_login():
        return redirect(url_for('auth.login'))

    tenant_id = get_current_tenant_id()
    search    = request.args.get('search', '').strip()
    status    = request.args.get('status', '').strip()
    page      = request.args.get('page', 1, type=int)
    per_page  = 12

    conn = get_db()
    try:
        base_where = "WHERE p.tenant_id = ?"
        params = [tenant_id]
        if search:
            base_where += " AND (p.name LIKE ? OR p.description LIKE ?)"
            params += [f'%{search}%', f'%{search}%']
        if status:
            base_where += " AND p.status = ?"
            params.append(status)

        total = conn.execute(
            f"SELECT COUNT(*) FROM projects p {base_where}", params
        ).fetchone()[0]

        rows = conn.execute(f"""
            SELECT p.*, c.name as company_name
            FROM projects p
            LEFT JOIN companies c ON c.id = p.company_id AND c.tenant_id = p.tenant_id
            {base_where}
            ORDER BY p.created_at DESC
            LIMIT ? OFFSET ?
        """, params + [per_page, (page - 1) * per_page]).fetchall()

        companies = conn.execute(
            "SELECT id, name FROM companies WHERE tenant_id = ? ORDER BY name", (tenant_id,)
        ).fetchall()

    finally:
        conn.close()

    total_pages = (total + per_page - 1) // per_page
    return render_template('projects/project_list.html',
                           projects=rows,
                           companies=companies,
                           search=search,
                           status_filter=status,
                           page=page,
                           total_pages=total_pages,
                           total=total)


@projects_bp.route('/add', methods=['GET', 'POST'])
@require_tenant
def add_project():
    if not _require_login():
        return redirect(url_for('auth.login'))

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        companies = conn.execute(
            "SELECT id, name FROM companies WHERE tenant_id = ? ORDER BY name", (tenant_id,)
        ).fetchall()

        if request.method == 'POST':
            company_id = request.form.get('company_id') or None
            conn.execute("""
                INSERT INTO projects (name, company_id, status, value, description, start_date, end_date, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                request.form.get('name', '').strip(),
                company_id,
                request.form.get('status', 'new'),
                request.form.get('value') or None,
                request.form.get('description', '').strip(),
                request.form.get('start_date') or None,
                request.form.get('end_date') or None,
                tenant_id
            ))
            conn.commit()
            return redirect(url_for('projects.project_list'))
    finally:
        conn.close()

    prefill_company = request.args.get('company_id')
    config = _get_config(conn, tenant_id, ['project_status'])
    return render_template('projects/project_form.html', project=None,
                           companies=companies, prefill_company=prefill_company,
                           config=config)


@projects_bp.route('/<int:project_id>')
@require_tenant
def project_detail(project_id):
    if not _require_login():
        return redirect(url_for('auth.login'))

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        project = conn.execute("""
            SELECT p.*, c.name as company_name, c.id as company_id
            FROM projects p
            LEFT JOIN companies c ON c.id = p.company_id
            WHERE p.id = ? AND p.tenant_id = ?
        """, (project_id, tenant_id)).fetchone()

        if not project:
            return redirect(url_for('projects.project_list'))

        contacts = conn.execute("""
            SELECT cu.customer_id, cu.first_name, cu.last_name, cu.phone
            FROM project_contacts pc
            JOIN customers cu ON cu.customer_id = pc.customer_id
            WHERE pc.project_id = ?
        """, (project_id,)).fetchall()

    finally:
        conn.close()

    return render_template('projects/project_detail.html',
                           project=project, contacts=contacts)


@projects_bp.route('/<int:project_id>/edit', methods=['GET', 'POST'])
@require_tenant
def edit_project(project_id):
    if not _require_login():
        return redirect(url_for('auth.login'))

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        project = conn.execute(
            "SELECT * FROM projects WHERE id = ? AND tenant_id = ?", (project_id, tenant_id)
        ).fetchone()
        if not project:
            return redirect(url_for('projects.project_list'))

        companies = conn.execute(
            "SELECT id, name FROM companies WHERE tenant_id = ? ORDER BY name", (tenant_id,)
        ).fetchall()

        if request.method == 'POST':
            company_id = request.form.get('company_id') or None
            conn.execute("""
                UPDATE projects SET name=?, company_id=?, status=?, value=?,
                    description=?, start_date=?, end_date=?
                WHERE id = ? AND tenant_id = ?
            """, (
                request.form.get('name', '').strip(),
                company_id,
                request.form.get('status', 'new'),
                request.form.get('value') or None,
                request.form.get('description', '').strip(),
                request.form.get('start_date') or None,
                request.form.get('end_date') or None,
                project_id, tenant_id
            ))
            conn.commit()
            return redirect(url_for('projects.project_detail', project_id=project_id))

    finally:
        conn.close()

    config = _get_config(conn, tenant_id, ['project_status'])
    return render_template('projects/project_form.html', project=project,
                           companies=companies, prefill_company=None,
                           config=config)


@projects_bp.route('/<int:project_id>/delete', methods=['POST'])
@require_tenant
def delete_project(project_id):
    if not _require_login():
        return redirect(url_for('auth.login'))

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        conn.execute("DELETE FROM project_contacts WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ? AND tenant_id = ?", (project_id, tenant_id))
        conn.commit()
        return jsonify({'success': True})
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()
