from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from tenant_utils import get_db, get_current_tenant_id, require_tenant

settings_config_bp = Blueprint('settings_config', __name__, url_prefix='/settings/config')

# All supported categories with metadata
CATEGORIES = [
    {'key': 'lead_source',    'name_en': 'Lead Sources',     'name_ar': 'مصادر الفرص',       'icon': 'target',    'module': 'customers'},
    {'key': 'city',           'name_en': 'Cities',            'name_ar': 'المدن',             'icon': 'map-pin',   'module': 'customers'},
    {'key': 'job_title',      'name_en': 'Job Titles',        'name_ar': 'المسميات الوظيفية', 'icon': 'briefcase', 'module': 'customers'},
    {'key': 'industry',       'name_en': 'Industries',        'name_ar': 'القطاعات',           'icon': 'building',  'module': 'companies'},
    {'key': 'contact_method', 'name_en': 'Contact Methods',   'name_ar': 'طرق التواصل',        'icon': 'phone',     'module': 'follow_up'},
    {'key': 'sales_stage',    'name_en': 'Sales Stages',      'name_ar': 'مراحل البيع',        'icon': 'trending',  'module': 'follow_up'},
    {'key': 'next_action',    'name_en': 'Next Actions',      'name_ar': 'الإجراءات التالية',  'icon': 'zap',       'module': 'follow_up'},
    {'key': 'activity_type',  'name_en': 'Activity Types',    'name_ar': 'أنواع الأنشطة',      'icon': 'activity',  'module': 'follow_up'},
    {'key': 'project_status', 'name_en': 'Project Statuses',  'name_ar': 'حالات المشاريع',     'icon': 'briefcase', 'module': 'projects'},
]

CATEGORY_KEYS = {c['key'] for c in CATEGORIES}

# Sections group categories by their usage context
SECTIONS = [
    {
        'key': 'customers', 'name_en': 'Contacts',   'name_ar': 'جهات الاتصال',
        'color': '#2563eb', 'bg': '#eff6ff',
        'cat_keys': ['lead_source', 'city', 'job_title'],
    },
    {
        'key': 'companies', 'name_en': 'Companies',   'name_ar': 'الشركات',
        'color': '#7c3aed', 'bg': '#f5f3ff',
        'cat_keys': ['industry'],
    },
    {
        'key': 'follow_up', 'name_en': 'Follow-ups',  'name_ar': 'المتابعات',
        'color': '#d97706', 'bg': '#fffbeb',
        'cat_keys': ['contact_method', 'sales_stage', 'next_action', 'activity_type'],
    },
    {
        'key': 'projects',  'name_en': 'Projects',    'name_ar': 'المشاريع',
        'color': '#16a34a', 'bg': '#f0fdf4',
        'cat_keys': ['project_status'],
    },
]


def _build_sections():
    cat_map = {c['key']: c for c in CATEGORIES}
    return [
        {**s, 'cats': [cat_map[k] for k in s['cat_keys'] if k in cat_map]}
        for s in SECTIONS
    ]


def _require_login():
    return 'salesperson_id' in session and session.get('role') in ['admin', 'manager']


# ── JSON API — used by all forms ──────────────────────────────────────────────

@settings_config_bp.route('/api/<category>')
@require_tenant
def api_options(category):
    if category not in CATEGORY_KEYS:
        return jsonify([]), 400

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, value, label_ar
            FROM config_options
            WHERE tenant_id = ? AND category = ? AND is_active = 1
            ORDER BY display_order, value
        """, (tenant_id, category)).fetchall()
        return jsonify([{'id': r['id'], 'value': r['value'], 'label_ar': r['label_ar']} for r in rows])
    finally:
        conn.close()


# ── Management UI ─────────────────────────────────────────────────────────────

@settings_config_bp.route('/')
@require_tenant
def config_home():
    if not _require_login():
        return redirect(url_for('auth.login'))
    return redirect(url_for('settings_config.config_category', category='lead_source'))


@settings_config_bp.route('/<category>')
@require_tenant
def config_category(category):
    if not _require_login():
        return redirect(url_for('auth.login'))
    if category not in CATEGORY_KEYS:
        return redirect(url_for('settings_config.config_category', category='lead_source'))

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        options = conn.execute("""
            SELECT id, value, label_ar, display_order, is_active, is_system
            FROM config_options
            WHERE tenant_id = ? AND category = ?
            ORDER BY display_order, value
        """, (tenant_id, category)).fetchall()
    finally:
        conn.close()

    active_cat = next(c for c in CATEGORIES if c['key'] == category)
    sections = _build_sections()
    active_section = next(
        (s for s in sections if any(c['key'] == category for c in s['cats'])), None
    )
    return render_template('settings/config.html',
                           categories=CATEGORIES,
                           sections=sections,
                           active_section=active_section,
                           active_cat=active_cat,
                           options=options)


@settings_config_bp.route('/<category>/add', methods=['POST'])
@require_tenant
def add_option(category):
    if not _require_login():
        return redirect(url_for('auth.login'))
    if category not in CATEGORY_KEYS:
        return redirect(url_for('settings_config.config_category', category='lead_source'))

    tenant_id = get_current_tenant_id()
    value    = request.form.get('value', '').strip()
    label_ar = request.form.get('label_ar', '').strip()

    if not value:
        return redirect(url_for('settings_config.config_category', category=category))

    conn = get_db()
    try:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(display_order), -1) FROM config_options WHERE tenant_id = ? AND category = ?",
            (tenant_id, category)
        ).fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO config_options (tenant_id, category, value, label_ar, display_order) VALUES (?, ?, ?, ?, ?)",
            (tenant_id, category, value, label_ar, max_order + 1)
        )
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for('settings_config.config_category', category=category))


@settings_config_bp.route('/<category>/<int:option_id>/edit', methods=['POST'])
@require_tenant
def edit_option(category, option_id):
    if not _require_login():
        return redirect(url_for('auth.login'))

    tenant_id = get_current_tenant_id()
    value    = request.form.get('value', '').strip()
    label_ar = request.form.get('label_ar', '').strip()

    if not value:
        return redirect(url_for('settings_config.config_category', category=category))

    conn = get_db()
    try:
        conn.execute("""
            UPDATE config_options SET value = ?, label_ar = ?
            WHERE id = ? AND tenant_id = ? AND is_system = 0
        """, (value, label_ar, option_id, tenant_id))
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for('settings_config.config_category', category=category))


@settings_config_bp.route('/<category>/<int:option_id>/toggle', methods=['POST'])
@require_tenant
def toggle_option(option_id, category):
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 403

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        conn.execute("""
            UPDATE config_options SET is_active = 1 - is_active
            WHERE id = ? AND tenant_id = ?
        """, (option_id, tenant_id))
        conn.commit()
        new_state = conn.execute(
            "SELECT is_active FROM config_options WHERE id = ?", (option_id,)
        ).fetchone()['is_active']
        return jsonify({'success': True, 'is_active': new_state})
    finally:
        conn.close()


@settings_config_bp.route('/<category>/<int:option_id>/delete', methods=['POST'])
@require_tenant
def delete_option(category, option_id):
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 403

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT is_system FROM config_options WHERE id = ? AND tenant_id = ?",
            (option_id, tenant_id)
        ).fetchone()
        if not row:
            return jsonify({'success': False, 'message': 'Not found'}), 404
        if row['is_system']:
            return jsonify({'success': False, 'message': 'Cannot delete system option'}), 400

        conn.execute("DELETE FROM config_options WHERE id = ? AND tenant_id = ?", (option_id, tenant_id))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@settings_config_bp.route('/<category>/reorder', methods=['POST'])
@require_tenant
def reorder_options(category):
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 403

    tenant_id = get_current_tenant_id()
    order = request.get_json()  # list of ids in new order
    if not isinstance(order, list):
        return jsonify({'error': 'Invalid data'}), 400

    conn = get_db()
    try:
        for idx, opt_id in enumerate(order):
            conn.execute(
                "UPDATE config_options SET display_order = ? WHERE id = ? AND tenant_id = ?",
                (idx, opt_id, tenant_id)
            )
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()
