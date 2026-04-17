"""
Products & Services — Phase 3
================================
Routes:
  GET  /products              → list (paginated, search, category filter)
  GET  /products/add          → add form
  POST /products/add          → create
  GET  /products/<id>/edit    → edit form
  POST /products/<id>/edit    → update
  POST /products/<id>/delete  → soft delete (is_active = 0)
  GET  /products/api/search   → JSON search for quotation builder
"""

import os
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, jsonify, flash, abort
)
from tenant_utils import get_db, get_current_tenant_id, require_tenant

products_bp = Blueprint('products', __name__, url_prefix='/products')

UNITS = ['unit', 'kg', 'g', 'liter', 'meter', 'm²', 'box', 'piece', 'set', 'hour', 'day', 'month']


def ensure_products_table():
    """Safe migration: create products table if it doesn't exist."""
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS products (
            product_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            category      TEXT,
            description   TEXT,
            selling_price REAL NOT NULL DEFAULT 0,
            min_price     REAL DEFAULT 0,
            cost          REAL DEFAULT 0,
            unit          TEXT DEFAULT 'unit',
            is_active     INTEGER DEFAULT 1,
            tenant_id     INTEGER NOT NULL,
            created_at    DATETIME DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        )
    ''')
    conn.commit()
    conn.close()


# ── List ──────────────────────────────────────────────────────────────────────

@products_bp.route('/')
@require_tenant
def product_list():
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    ensure_products_table()
    tenant_id = get_current_tenant_id()
    conn = get_db()
    cursor = conn.cursor()

    search   = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    page     = max(1, int(request.args.get('page', 1)))
    per_page = 20

    # Build query
    conditions = ['tenant_id = ?', 'is_active = 1']
    params     = [tenant_id]

    if search:
        conditions.append('(name LIKE ? OR description LIKE ? OR category LIKE ?)')
        params += [f'%{search}%', f'%{search}%', f'%{search}%']
    if category:
        conditions.append('category = ?')
        params.append(category)

    where = ' AND '.join(conditions)

    total = cursor.execute(
        f'SELECT COUNT(*) FROM products WHERE {where}', params
    ).fetchone()[0]

    products = cursor.execute(
        f'''SELECT * FROM products WHERE {where}
            ORDER BY name ASC LIMIT ? OFFSET ?''',
        params + [per_page, (page - 1) * per_page]
    ).fetchall()

    categories = cursor.execute(
        'SELECT DISTINCT category FROM products WHERE tenant_id = ? AND is_active = 1 AND category IS NOT NULL ORDER BY category',
        (tenant_id,)
    ).fetchall()

    conn.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template('products/product_list.html',
        products=products,
        categories=[c['category'] for c in categories],
        search=search,
        category=category,
        page=page,
        total_pages=total_pages,
        total=total,
        units=UNITS,
    )


# ── Add ───────────────────────────────────────────────────────────────────────

@products_bp.route('/add', methods=['GET', 'POST'])
@require_tenant
def add_product():
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))
    if session.get('role') not in ['admin', 'manager']:
        abort(403)

    ensure_products_table()
    tenant_id = get_current_tenant_id()
    conn = get_db()

    # Existing categories for datalist
    categories = [r['category'] for r in conn.execute(
        'SELECT DISTINCT category FROM products WHERE tenant_id = ? AND category IS NOT NULL ORDER BY category',
        (tenant_id,)
    ).fetchall()]

    if request.method == 'POST':
        data = _form_data()
        error = _validate(data)
        if error:
            conn.close()
            flash(error, 'error')
            return render_template('products/product_form.html',
                product=data, categories=categories, units=UNITS, action='add')

        conn.execute('''
            INSERT INTO products
                (name, category, description, selling_price, min_price, cost, unit, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (data['name'], data['category'], data['description'],
              data['selling_price'], data['min_price'], data['cost'],
              data['unit'], tenant_id))
        conn.commit()
        conn.close()
        flash('✅ Product added successfully', 'success')
        return redirect(url_for('products.product_list'))

    conn.close()
    return render_template('products/product_form.html',
        product={}, categories=categories, units=UNITS, action='add')


# ── Edit ──────────────────────────────────────────────────────────────────────

@products_bp.route('/<int:product_id>/edit', methods=['GET', 'POST'])
@require_tenant
def edit_product(product_id):
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))
    if session.get('role') not in ['admin', 'manager']:
        abort(403)

    ensure_products_table()
    tenant_id = get_current_tenant_id()
    conn = get_db()

    product = conn.execute(
        'SELECT * FROM products WHERE product_id = ? AND tenant_id = ?',
        (product_id, tenant_id)
    ).fetchone()

    if not product:
        conn.close()
        abort(404)

    categories = [r['category'] for r in conn.execute(
        'SELECT DISTINCT category FROM products WHERE tenant_id = ? AND category IS NOT NULL ORDER BY category',
        (tenant_id,)
    ).fetchall()]

    if request.method == 'POST':
        data = _form_data()
        error = _validate(data)
        if error:
            conn.close()
            flash(error, 'error')
            return render_template('products/product_form.html',
                product={**dict(product), **data},
                categories=categories, units=UNITS, action='edit',
                product_id=product_id)

        conn.execute('''
            UPDATE products SET
                name=?, category=?, description=?,
                selling_price=?, min_price=?, cost=?, unit=?
            WHERE product_id = ? AND tenant_id = ?
        ''', (data['name'], data['category'], data['description'],
              data['selling_price'], data['min_price'], data['cost'],
              data['unit'], product_id, tenant_id))
        conn.commit()
        conn.close()
        flash('✅ Product updated successfully', 'success')
        return redirect(url_for('products.product_list'))

    conn.close()
    return render_template('products/product_form.html',
        product=dict(product), categories=categories,
        units=UNITS, action='edit', product_id=product_id)


# ── Delete (soft) ─────────────────────────────────────────────────────────────

@products_bp.route('/<int:product_id>/delete', methods=['POST'])
@require_tenant
def delete_product(product_id):
    if session.get('role') not in ['admin', 'manager']:
        abort(403)
    ensure_products_table()
    conn = get_db()
    conn.execute(
        'UPDATE products SET is_active = 0 WHERE product_id = ? AND tenant_id = ?',
        (product_id, get_current_tenant_id())
    )
    conn.commit()
    conn.close()
    flash('Product removed', 'success')
    return redirect(url_for('products.product_list'))


# ── JSON search (for quotation builder) ───────────────────────────────────────

@products_bp.route('/api/search')
@require_tenant
def api_search():
    if 'salesperson_id' not in session:
        return jsonify([]), 401

    ensure_products_table()
    q         = request.args.get('q', '').strip()
    tenant_id = get_current_tenant_id()
    conn      = get_db()

    if q:
        rows = conn.execute(
            '''SELECT product_id, name, category, selling_price, min_price, unit
               FROM products
               WHERE tenant_id = ? AND is_active = 1
                 AND (name LIKE ? OR category LIKE ?)
               ORDER BY name LIMIT 20''',
            (tenant_id, f'%{q}%', f'%{q}%')
        ).fetchall()
    else:
        rows = conn.execute(
            '''SELECT product_id, name, category, selling_price, min_price, unit
               FROM products
               WHERE tenant_id = ? AND is_active = 1
               ORDER BY name LIMIT 50''',
            (tenant_id,)
        ).fetchall()

    conn.close()
    return jsonify([dict(r) for r in rows])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _form_data():
    def floatval(key):
        try: return float(request.form.get(key, 0) or 0)
        except: return 0.0
    return {
        'name':          request.form.get('name', '').strip(),
        'category':      request.form.get('category', '').strip(),
        'description':   request.form.get('description', '').strip(),
        'selling_price': floatval('selling_price'),
        'min_price':     floatval('min_price'),
        'cost':          floatval('cost'),
        'unit':          request.form.get('unit', 'unit').strip(),
    }

def _validate(data):
    if not data['name']:
        return 'Product name is required'
    if data['selling_price'] < 0:
        return 'Selling price cannot be negative'
    if data['min_price'] > data['selling_price'] and data['selling_price'] > 0:
        return 'Minimum price cannot exceed selling price'
    return None
