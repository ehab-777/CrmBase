from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from tenant_utils import get_db, get_current_tenant_id, require_tenant
from activity_logger import log_activity, get_activities

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

        # For kanban: all projects + status config (no pagination)
        all_projects = conn.execute("""
            SELECT p.*, c.name as company_name
            FROM projects p
            LEFT JOIN companies c ON c.id = p.company_id AND c.tenant_id = p.tenant_id
            WHERE p.tenant_id = ?
            ORDER BY p.created_at DESC
        """, [tenant_id]).fetchall()

        status_opts = conn.execute("""
            SELECT value, label_ar FROM config_options
            WHERE tenant_id = ? AND category = 'project_status' AND is_active = 1
            ORDER BY display_order, value
        """, [tenant_id]).fetchall()

    finally:
        conn.close()

    total_pages = (total + per_page - 1) // per_page
    return render_template('projects/project_list.html',
                           projects=rows,
                           all_projects=all_projects,
                           status_opts=status_opts,
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
            name = request.form.get('name', '').strip()
            cur = conn.execute("""
                INSERT INTO projects (name, company_id, status, value, description, start_date, end_date, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name,
                company_id,
                request.form.get('status', 'new'),
                request.form.get('value') or None,
                request.form.get('description', '').strip(),
                request.form.get('start_date') or None,
                request.form.get('end_date') or None,
                tenant_id
            ))
            log_activity(conn, tenant_id, 'project', cur.lastrowid, 'created',
                         f'Project "{name}" created')
            conn.commit()
            return redirect(url_for('projects.project_list'))

        prefill_company = request.args.get('company_id')
        config = _get_config(conn, tenant_id, ['project_status'])
    finally:
        conn.close()

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
            SELECT cu.customer_id, cu.contact_person, cu.phone_number, cu.company_name
            FROM project_contacts pc
            JOIN customers cu ON cu.customer_id = pc.customer_id
            WHERE pc.project_id = ?
        """, (project_id,)).fetchall()

        # All tenant contacts not yet linked — for the picker
        linked_ids = [c['customer_id'] for c in contacts]
        placeholder = ','.join('?' * len(linked_ids)) if linked_ids else 'NULL'
        all_contacts_q = f"""
            SELECT customer_id, contact_person, company_name, phone_number
            FROM customers
            WHERE tenant_id = ?
            {'AND customer_id NOT IN (' + placeholder + ')' if linked_ids else ''}
            ORDER BY contact_person
        """
        all_contacts = conn.execute(
            all_contacts_q, [tenant_id] + linked_ids
        ).fetchall()

        activities = get_activities(conn, tenant_id, 'project', project_id)

    finally:
        conn.close()

    return render_template('projects/project_detail.html',
                           project=project, contacts=contacts, all_contacts=all_contacts,
                           activities=activities)


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
            name = request.form.get('name', '').strip()
            conn.execute("""
                UPDATE projects SET name=?, company_id=?, status=?, value=?,
                    description=?, start_date=?, end_date=?
                WHERE id = ? AND tenant_id = ?
            """, (
                name,
                company_id,
                request.form.get('status', 'new'),
                request.form.get('value') or None,
                request.form.get('description', '').strip(),
                request.form.get('start_date') or None,
                request.form.get('end_date') or None,
                project_id, tenant_id
            ))
            log_activity(conn, tenant_id, 'project', project_id, 'updated',
                         f'Project updated: "{name}"')
            conn.commit()
            return redirect(url_for('projects.project_detail', project_id=project_id))

        config = _get_config(conn, tenant_id, ['project_status'])
    finally:
        conn.close()

    return render_template('projects/project_form.html', project=project,
                           companies=companies, prefill_company=None,
                           config=config)


@projects_bp.route('/<int:project_id>/contacts/add', methods=['POST'])
@require_tenant
def add_contact(project_id):
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 403
    tenant_id = get_current_tenant_id()
    customer_id = request.get_json().get('customer_id')
    if not customer_id:
        return jsonify({'error': 'Missing customer_id'}), 400
    conn = get_db()
    try:
        # verify project belongs to tenant
        p = conn.execute("SELECT id FROM projects WHERE id=? AND tenant_id=?", (project_id, tenant_id)).fetchone()
        if not p:
            return jsonify({'error': 'Not found'}), 404
        # verify customer belongs to tenant
        cu = conn.execute(
            "SELECT customer_id, contact_person, company_name, phone_number FROM customers WHERE customer_id=? AND tenant_id=?",
            (customer_id, tenant_id)
        ).fetchone()
        if not cu:
            return jsonify({'error': 'Contact not found'}), 404
        conn.execute("INSERT OR IGNORE INTO project_contacts (project_id, customer_id) VALUES (?,?)",
                     (project_id, customer_id))
        log_activity(conn, tenant_id, 'project', project_id, 'contact_linked',
                     f'{cu["contact_person"]} linked to project')
        conn.commit()
        return jsonify({'success': True, 'contact': dict(cu)})
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@projects_bp.route('/<int:project_id>/contacts/remove', methods=['POST'])
@require_tenant
def remove_contact(project_id):
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 403
    tenant_id = get_current_tenant_id()
    customer_id = request.get_json().get('customer_id')
    conn = get_db()
    try:
        conn.execute("DELETE FROM project_contacts WHERE project_id=? AND customer_id=?",
                     (project_id, customer_id))
        log_activity(conn, tenant_id, 'project', project_id, 'contact_unlinked',
                     'Contact removed from project')
        conn.commit()
        return jsonify({'success': True})
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@projects_bp.route('/<int:project_id>/status', methods=['POST'])
@require_tenant
def update_status(project_id):
    """Kanban drag-and-drop status update."""
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 403
    tenant_id = get_current_tenant_id()
    new_status = (request.get_json(force=True, silent=True) or {}).get('status', '').strip()
    if not new_status:
        return jsonify({'error': 'Missing status'}), 400
    conn = get_db()
    try:
        conn.execute(
            "UPDATE projects SET status=? WHERE id=? AND tenant_id=?",
            (new_status, project_id, tenant_id)
        )
        log_activity(conn, tenant_id, 'project', project_id, 'status_changed',
                     f'Status changed to "{new_status}"')
        conn.commit()
        return jsonify({'success': True})
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@projects_bp.route('/quick-add', methods=['POST'])
@require_tenant
def quick_add():
    if 'salesperson_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    data       = request.get_json(force=True, silent=True) or {}
    name       = (data.get('name') or '').strip()
    company_id = data.get('company_id') or None
    status     = (data.get('status') or 'New').strip()
    if not name:
        return jsonify({'error': 'Project name is required'}), 400
    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO projects (name, company_id, status, tenant_id) VALUES (?,?,?,?)",
            (name, company_id, status, tenant_id)
        )
        conn.commit()
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return jsonify({'project_id': pid, 'name': name}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


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
