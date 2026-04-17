"""
Quotations — Phase 4
======================
Routes:
  GET  /quotations/              → list (paginated, search, status filter)
  GET  /quotations/new           → builder (new)  ?customer_id=X to pre-fill
  POST /quotations/new           → create & save
  GET  /quotations/<id>          → view / detail
  GET  /quotations/<id>/edit     → builder (edit draft only)
  POST /quotations/<id>/edit     → update
  POST /quotations/<id>/status   → change status
  GET  /quotations/<id>/pdf      → download PDF (xhtml2pdf)
  POST /quotations/<id>/delete   → soft-delete (mark cancelled)
"""

import json
import io
from datetime import date, timedelta
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, abort, make_response
)
from tenant_utils import get_db, get_current_tenant_id, require_tenant

quotations_bp = Blueprint('quotations', __name__, url_prefix='/quotations')

STATUSES   = ['draft', 'sent', 'accepted', 'rejected', 'cancelled']
CURRENCIES = ['SAR', 'USD', 'EUR', 'AED', 'EGP', 'GBP']

STATUS_META = {
    'draft':     {'label': 'Draft',     'color': '#64748b', 'bg': '#f1f5f9'},
    'sent':      {'label': 'Sent',      'color': '#2563eb', 'bg': '#eff6ff'},
    'accepted':  {'label': 'Accepted',  'color': '#059669', 'bg': '#ecfdf5'},
    'rejected':  {'label': 'Rejected',  'color': '#dc2626', 'bg': '#fef2f2'},
    'cancelled': {'label': 'Cancelled', 'color': '#9ca3af', 'bg': '#f9fafb'},
}

# Next-status transitions (what buttons to show on detail page)
NEXT_STATUSES = {
    'draft':    ['sent', 'cancelled'],
    'sent':     ['accepted', 'rejected', 'cancelled'],
    'accepted': ['cancelled'],
    'rejected': ['draft'],
    'cancelled': [],
}


# ── DB bootstrap ──────────────────────────────────────────────────────────────

def ensure_tables():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS quotations (
            quotation_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            quotation_number TEXT,
            customer_id     INTEGER NOT NULL,
            salesperson_id  INTEGER NOT NULL,
            status          TEXT    DEFAULT 'draft',
            issue_date      TEXT    DEFAULT (date('now','localtime')),
            valid_until     TEXT,
            notes           TEXT,
            terms           TEXT,
            discount_type   TEXT    DEFAULT 'none',
            discount_value  REAL    DEFAULT 0,
            tax_percent     REAL    DEFAULT 0,
            subtotal        REAL    DEFAULT 0,
            discount_amount REAL    DEFAULT 0,
            tax_amount      REAL    DEFAULT 0,
            total           REAL    DEFAULT 0,
            currency        TEXT    DEFAULT 'SAR',
            tenant_id       INTEGER NOT NULL,
            created_at      DATETIME DEFAULT (datetime('now','localtime')),
            updated_at      DATETIME DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS quotation_items (
            item_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            quotation_id INTEGER NOT NULL,
            product_id   INTEGER,
            name         TEXT    NOT NULL,
            description  TEXT,
            quantity     REAL    NOT NULL DEFAULT 1,
            unit         TEXT    DEFAULT 'unit',
            unit_price   REAL    NOT NULL DEFAULT 0,
            discount_pct REAL    DEFAULT 0,
            line_total   REAL    NOT NULL DEFAULT 0,
            sort_order   INTEGER DEFAULT 0
        );
    ''')
    conn.commit()
    conn.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _customers(tenant_id, conn):
    return conn.execute(
        'SELECT customer_id, company_name FROM customers WHERE tenant_id = ? ORDER BY company_name',
        (tenant_id,)
    ).fetchall()


def _calc_totals(items, discount_type, discount_value, tax_percent):
    """Return (subtotal, discount_amount, tax_amount, total)."""
    subtotal = sum(
        float(i.get('quantity', 1) or 1)
        * float(i.get('unit_price', 0) or 0)
        * (1 - float(i.get('discount_pct', 0) or 0) / 100)
        for i in items
    )
    if discount_type == 'percent':
        disc = subtotal * discount_value / 100
    elif discount_type == 'fixed':
        disc = min(discount_value, subtotal)
    else:
        disc = 0.0

    taxable   = subtotal - disc
    tax_amt   = taxable * tax_percent / 100
    total     = taxable + tax_amt
    return subtotal, disc, tax_amt, total


def _insert_items(conn, quotation_id, items):
    for idx, item in enumerate(items):
        qty   = float(item.get('quantity',  1) or 1)
        price = float(item.get('unit_price', 0) or 0)
        disc  = float(item.get('discount_pct', 0) or 0)
        line_total = qty * price * (1 - disc / 100)
        conn.execute('''
            INSERT INTO quotation_items
                (quotation_id, product_id, name, description,
                 quantity, unit, unit_price, discount_pct, line_total, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            quotation_id,
            item.get('product_id') or None,
            item.get('name', ''),
            item.get('description', ''),
            qty,
            item.get('unit', 'unit'),
            price,
            disc,
            line_total,
            idx,
        ))


def _parse_post():
    """Parse & validate common POST fields. Returns dict or raises ValueError."""
    customer_id = int(request.form.get('customer_id', 0) or 0)
    if not customer_id:
        raise ValueError('Customer is required')

    items = json.loads(request.form.get('items_json', '[]'))
    if not items:
        raise ValueError('Add at least one line item')

    discount_value = float(request.form.get('discount_value', 0) or 0)
    tax_percent    = float(request.form.get('tax_percent',    0) or 0)
    discount_type  = request.form.get('discount_type', 'none')

    return dict(
        customer_id    = customer_id,
        items          = items,
        issue_date     = request.form.get('issue_date')  or date.today().isoformat(),
        valid_until    = request.form.get('valid_until') or None,
        notes          = request.form.get('notes',  '').strip(),
        terms          = request.form.get('terms',  '').strip(),
        currency       = request.form.get('currency', 'SAR'),
        discount_type  = discount_type,
        discount_value = discount_value,
        tax_percent    = tax_percent,
    )


# ── List ──────────────────────────────────────────────────────────────────────

@quotations_bp.route('/')
@require_tenant
def quotation_list():
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    ensure_tables()
    tid  = get_current_tenant_id()
    conn = get_db()

    status_f = request.args.get('status', '').strip()
    search   = request.args.get('search', '').strip()
    page     = max(1, int(request.args.get('page', 1)))
    per_page = 25

    conds  = ['q.tenant_id = ?']
    params = [tid]

    if status_f:
        conds.append('q.status = ?')
        params.append(status_f)
    else:
        conds.append("q.status != 'cancelled'")

    if search:
        conds.append('(c.company_name LIKE ? OR q.quotation_number LIKE ?)')
        params += [f'%{search}%', f'%{search}%']

    where = ' AND '.join(conds)

    total = conn.execute(
        f'''SELECT COUNT(*) FROM quotations q
            JOIN customers c ON q.customer_id = c.customer_id
            WHERE {where}''', params
    ).fetchone()[0]

    rows = conn.execute(
        f'''SELECT q.*, c.company_name, sp.salesperson_name
            FROM quotations q
            JOIN customers c  ON q.customer_id   = c.customer_id
            JOIN sales_team sp ON q.salesperson_id = sp.salesperson_id
            WHERE {where}
            ORDER BY q.created_at DESC
            LIMIT ? OFFSET ?''',
        params + [per_page, (page - 1) * per_page]
    ).fetchall()

    conn.close()

    return render_template('quotations/quotation_list.html',
        quotations   = rows,
        status_filter= status_f,
        search       = search,
        page         = page,
        total_pages  = (total + per_page - 1) // per_page,
        total        = total,
        statuses     = STATUSES,
        status_meta  = STATUS_META,
    )


# ── New ───────────────────────────────────────────────────────────────────────

@quotations_bp.route('/new', methods=['GET', 'POST'])
@require_tenant
def new_quotation():
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    ensure_tables()
    tid  = get_current_tenant_id()
    conn = get_db()
    custs = _customers(tid, conn)

    if request.method == 'POST':
        try:
            d = _parse_post()
        except (ValueError, json.JSONDecodeError) as e:
            conn.close()
            flash(str(e), 'error')
            return redirect(url_for('quotations.new_quotation'))

        sub, disc, tax, total = _calc_totals(
            d['items'], d['discount_type'], d['discount_value'], d['tax_percent']
        )
        cur = conn.execute('''
            INSERT INTO quotations
                (customer_id, salesperson_id, status, issue_date, valid_until,
                 notes, terms, currency,
                 discount_type, discount_value, tax_percent,
                 subtotal, discount_amount, tax_amount, total, tenant_id)
            VALUES (?,?,\'draft\',?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (d['customer_id'], session['salesperson_id'],
              d['issue_date'], d['valid_until'],
              d['notes'], d['terms'], d['currency'],
              d['discount_type'], d['discount_value'], d['tax_percent'],
              sub, disc, tax, total, tid))

        qid = cur.lastrowid
        conn.execute(
            'UPDATE quotations SET quotation_number=? WHERE quotation_id=?',
            (f"QT-{date.today().year}-{qid:04d}", qid)
        )
        _insert_items(conn, qid, d['items'])
        conn.commit()
        conn.close()
        flash('✅ Quotation created', 'success')
        return redirect(url_for('quotations.quotation_detail', quotation_id=qid))

    conn.close()
    prefill = request.args.get('customer_id', '')
    return render_template('quotations/quotation_builder.html',
        action      = 'new',
        quotation   = {
            'customer_id':    prefill,
            'issue_date':     date.today().isoformat(),
            'valid_until':    (date.today() + timedelta(days=30)).isoformat(),
            'currency':       'SAR',
            'discount_type':  'none',
            'discount_value': 0,
            'tax_percent':    0,
            'notes':          '',
            'terms':          '',
        },
        items_json  = '[]',
        customers   = custs,
        currencies  = CURRENCIES,
        status_meta = STATUS_META,
    )


# ── Edit ──────────────────────────────────────────────────────────────────────

@quotations_bp.route('/<int:quotation_id>/edit', methods=['GET', 'POST'])
@require_tenant
def edit_quotation(quotation_id):
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    ensure_tables()
    tid  = get_current_tenant_id()
    conn = get_db()

    q = conn.execute(
        'SELECT * FROM quotations WHERE quotation_id=? AND tenant_id=?',
        (quotation_id, tid)
    ).fetchone()

    if not q:
        conn.close(); abort(404)

    if q['status'] != 'draft':
        conn.close()
        flash('Only draft quotations can be edited.', 'error')
        return redirect(url_for('quotations.quotation_detail', quotation_id=quotation_id))

    custs = _customers(tid, conn)

    if request.method == 'POST':
        try:
            d = _parse_post()
        except (ValueError, json.JSONDecodeError) as e:
            conn.close()
            flash(str(e), 'error')
            return redirect(url_for('quotations.edit_quotation', quotation_id=quotation_id))

        sub, disc, tax, total = _calc_totals(
            d['items'], d['discount_type'], d['discount_value'], d['tax_percent']
        )
        conn.execute('''
            UPDATE quotations SET
                customer_id=?, issue_date=?, valid_until=?,
                notes=?, terms=?, currency=?,
                discount_type=?, discount_value=?, tax_percent=?,
                subtotal=?, discount_amount=?, tax_amount=?, total=?,
                updated_at=datetime('now','localtime')
            WHERE quotation_id=? AND tenant_id=?
        ''', (d['customer_id'], d['issue_date'], d['valid_until'],
              d['notes'], d['terms'], d['currency'],
              d['discount_type'], d['discount_value'], d['tax_percent'],
              sub, disc, tax, total,
              quotation_id, tid))

        conn.execute('DELETE FROM quotation_items WHERE quotation_id=?', (quotation_id,))
        _insert_items(conn, quotation_id, d['items'])
        conn.commit()
        conn.close()
        flash('✅ Quotation updated', 'success')
        return redirect(url_for('quotations.quotation_detail', quotation_id=quotation_id))

    items = conn.execute(
        'SELECT * FROM quotation_items WHERE quotation_id=? ORDER BY sort_order',
        (quotation_id,)
    ).fetchall()
    conn.close()

    return render_template('quotations/quotation_builder.html',
        action      = 'edit',
        quotation   = dict(q),
        items_json  = json.dumps([dict(i) for i in items]),
        customers   = custs,
        currencies  = CURRENCIES,
        status_meta = STATUS_META,
    )


# ── Detail ────────────────────────────────────────────────────────────────────

@quotations_bp.route('/<int:quotation_id>')
@require_tenant
def quotation_detail(quotation_id):
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    ensure_tables()
    tid  = get_current_tenant_id()
    conn = get_db()

    q = conn.execute('''
        SELECT q.*,
               c.company_name, c.contact_person, c.phone_number,
               c.email_address, c.company_address,
               sp.salesperson_name, sp.work_email AS sp_email,
               sp.phone_number AS sp_phone
        FROM quotations q
        JOIN customers  c  ON q.customer_id   = c.customer_id
        JOIN sales_team sp ON q.salesperson_id = sp.salesperson_id
        WHERE q.quotation_id=? AND q.tenant_id=?
    ''', (quotation_id, tid)).fetchone()

    if not q:
        conn.close(); abort(404)

    items = conn.execute(
        'SELECT * FROM quotation_items WHERE quotation_id=? ORDER BY sort_order',
        (quotation_id,)
    ).fetchall()
    conn.close()

    q = dict(q)
    return render_template('quotations/quotation_detail.html',
        quotation    = q,
        items        = items,
        status_meta  = STATUS_META,
        next_statuses= NEXT_STATUSES.get(q['status'], []),
    )


# ── Status change ─────────────────────────────────────────────────────────────

@quotations_bp.route('/<int:quotation_id>/status', methods=['POST'])
@require_tenant
def change_status(quotation_id):
    if 'salesperson_id' not in session:
        abort(401)

    new_status = request.form.get('status', '')
    if new_status not in STATUSES:
        abort(400)

    ensure_tables()
    tid  = get_current_tenant_id()
    conn = get_db()
    conn.execute(
        "UPDATE quotations SET status=?, updated_at=datetime('now','localtime') WHERE quotation_id=? AND tenant_id=?",
        (new_status, quotation_id, tid)
    )
    conn.commit()
    conn.close()
    flash(f'Status → {new_status.title()}', 'success')
    return redirect(url_for('quotations.quotation_detail', quotation_id=quotation_id))


# ── PDF export ────────────────────────────────────────────────────────────────

@quotations_bp.route('/<int:quotation_id>/pdf')
@require_tenant
def export_pdf(quotation_id):
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    ensure_tables()
    tid  = get_current_tenant_id()
    conn = get_db()

    q = conn.execute('''
        SELECT q.*,
               c.company_name, c.contact_person, c.phone_number,
               c.email_address, c.company_address,
               sp.salesperson_name, sp.work_email AS sp_email,
               sp.phone_number AS sp_phone
        FROM quotations q
        JOIN customers  c  ON q.customer_id   = c.customer_id
        JOIN sales_team sp ON q.salesperson_id = sp.salesperson_id
        WHERE q.quotation_id=? AND q.tenant_id=?
    ''', (quotation_id, tid)).fetchone()

    if not q:
        conn.close(); abort(404)

    items = conn.execute(
        'SELECT * FROM quotation_items WHERE quotation_id=? ORDER BY sort_order',
        (quotation_id,)
    ).fetchall()
    conn.close()

    html = render_template('quotations/quotation_pdf.html',
        quotation = dict(q),
        items     = items,
    )

    try:
        from xhtml2pdf import pisa
        buf = io.BytesIO()
        status = pisa.CreatePDF(html.encode('utf-8'), dest=buf, encoding='utf-8')
        if status.err:
            flash('PDF generation error — check server logs.', 'error')
            return redirect(url_for('quotations.quotation_detail', quotation_id=quotation_id))

        resp = make_response(buf.getvalue())
        resp.headers['Content-Type'] = 'application/pdf'
        fname = f"quotation-{dict(q).get('quotation_number', quotation_id)}.pdf"
        resp.headers['Content-Disposition'] = f'attachment; filename="{fname}"'
        return resp

    except ImportError:
        flash('xhtml2pdf is not installed. Run: pip install xhtml2pdf', 'error')
        return redirect(url_for('quotations.quotation_detail', quotation_id=quotation_id))


# ── Delete (soft) ─────────────────────────────────────────────────────────────

@quotations_bp.route('/<int:quotation_id>/delete', methods=['POST'])
@require_tenant
def delete_quotation(quotation_id):
    if session.get('role') not in ['admin', 'manager']:
        abort(403)

    ensure_tables()
    tid  = get_current_tenant_id()
    conn = get_db()
    conn.execute(
        "UPDATE quotations SET status='cancelled', updated_at=datetime('now','localtime') WHERE quotation_id=? AND tenant_id=?",
        (quotation_id, tid)
    )
    conn.commit()
    conn.close()
    flash('Quotation cancelled', 'success')
    return redirect(url_for('quotations.quotation_list'))
