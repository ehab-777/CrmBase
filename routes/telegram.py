"""
Telegram Bot – Phase 1 + 2
============================
Features:
  • Webhook endpoint receives Telegram updates
  • /start  → returns a 6-digit link code to connect the web account
  • /link <code> → links Telegram account to CRM account
  • Voice notes → transcribed via faster-whisper (Arabic + English)
  • Text messages → parsed into CRM follow-up records

Setup (one-time, run from CLI):
  python -c "from routes.telegram import set_webhook; set_webhook()"
"""

import os
import tempfile
import secrets
import string
import json
import requests
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, flash
from tenant_utils import get_db, require_tenant
from security import csrf

# ─── Whisper model (lazy-loaded on first voice message) ───────────────────────

_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        model_size = os.getenv('WHISPER_MODEL', 'base')
        cache_dir = os.getenv('WHISPER_CACHE', '/data/whisper_models')
        os.makedirs(cache_dir, exist_ok=True)
        _whisper_model = WhisperModel(
            model_size,
            device='cpu',
            compute_type='int8',
            download_root=cache_dir,
        )
    return _whisper_model


def transcribe_voice(file_bytes: bytes) -> str | None:
    """Save voice bytes to a temp OGG file and transcribe with faster-whisper."""
    try:
        model = get_whisper_model()
        with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            segments, info = model.transcribe(
                tmp_path,
                language=None,          # auto-detect AR / EN
                beam_size=5,
                vad_filter=True,
            )
            text = ' '.join(seg.text.strip() for seg in segments).strip()
            return text or None
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        print(f'[whisper] transcription error: {e}')
        return None

telegram_bp = Blueprint('telegram', __name__, url_prefix='/telegram')

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_API = f'https://api.telegram.org/bot{BOT_TOKEN}'

# ─── Helpers ──────────────────────────────────────────────────────────────────

def send_message(chat_id, text, parse_mode='HTML'):
    if not BOT_TOKEN:
        return
    requests.post(f'{TELEGRAM_API}/sendMessage', json={
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
    }, timeout=10)


def generate_link_token():
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(6))


def get_salesperson_by_chat_id(conn, chat_id):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM sales_team WHERE telegram_chat_id = ?",
        (str(chat_id),)
    )
    return cursor.fetchone()


def get_salesperson_by_token(conn, token):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM sales_team WHERE telegram_link_token = ?",
        (token.upper().strip(),)
    )
    return cursor.fetchone()


def ensure_telegram_columns(conn):
    """Add telegram columns to sales_team if they don't exist (safe migration)."""
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE sales_team ADD COLUMN telegram_chat_id TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE sales_team ADD COLUMN telegram_link_token TEXT")
    except Exception:
        pass
    conn.commit()

# ─── Simple NLP parser ────────────────────────────────────────────────────────

STAGE_KEYWORDS = {
    'عميل محتمل':       ['عميل محتمل', 'جديد', 'اتصل', 'اتصلت'],
    'جاري التواصل':     ['جاري التواصل', 'تواصلنا', 'تواصلت', 'تحدثت', 'كلمته'],
    'تقديم عرض السعر': ['عرض سعر', 'عرض', 'قدمت عرض', 'ارسلت عرض'],
    'جاري التفاوض':     ['تفاوض', 'تفاوضنا', 'يفاوض', 'موافق'],
    'تم التسليم':       ['تسليم', 'تم التسليم', 'سلمنا', 'انتهى', 'اكتمل'],
    'لم يتم البيع':     ['رفض', 'لم يوافق', 'فشل', 'خسرنا'],
}

ACTION_KEYWORDS = {
    'متابعة اتصال':          ['اتصل', 'اتصال', 'تابع'],
    'انتظار رد العميل':      ['انتظار', 'ينتظر', 'رد'],
    'إرسال عرض سعر':         ['ارسل عرض', 'عرض سعر'],
    'دعوة لزيارة المعرض':    ['زيارة', 'يزور', 'معرض'],
    'متابعة التمويل / الدفع': ['دفع', 'تمويل', 'فاتورة'],
    'إغلاق البيع':            ['اغلق', 'اغلاق', 'انهى'],
}


def parse_message_text(text, salesperson_id, tenant_id):
    """
    Very lightweight Arabic NLP:
    Returns a dict with fields to insert into sales_followup,
    or None if we can't extract enough meaningful data.
    """
    text_lower = text.lower()

    # Detect sales stage
    stage = None
    for s, keywords in STAGE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            stage = s
            break

    # Detect next action
    action = None
    for a, keywords in ACTION_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            action = a
            break

    # Try to find a customer name – look for longest company_name match
    conn = get_db_for_tenant(tenant_id)
    if not conn:
        return None

    cursor = conn.cursor()
    cursor.execute(
        "SELECT customer_id, company_name FROM customers WHERE tenant_id = ? AND assigned_salesperson_id = ?",
        (tenant_id, salesperson_id)
    )
    customers = cursor.fetchall()
    conn.close()

    matched_customer = None
    best_len = 0
    for c in customers:
        name = c['company_name']
        if name.lower() in text_lower and len(name) > best_len:
            matched_customer = c
            best_len = len(name)

    return {
        'customer': matched_customer,
        'stage': stage,
        'action': action,
        'summary': text,
    }


# ─── New customer parser ──────────────────────────────────────────────────────

# Keywords that signal "create new customer"
NEW_CUSTOMER_TRIGGERS = [
    'عميل جديد', 'زبون جديد', 'اضف عميل', 'أضف عميل',
    'سجل عميل', 'عميل جديده', 'new customer', 'add customer',
]

import re

def detect_new_customer_intent(text):
    """Return True if the message is about creating a new customer."""
    t = text.lower()
    return any(trigger in t for trigger in NEW_CUSTOMER_TRIGGERS)


def parse_new_customer(text):
    """
    Extract company_name, contact_person, phone_number from a free-form message.
    Expected (flexible) format:
      عميل جديد: [شركة] <name>، [المسؤول] <person>، <phone>
    Returns dict or None if can't extract minimum fields.
    """
    # Remove trigger words so they don't confuse extraction
    clean = text
    for trigger in NEW_CUSTOMER_TRIGGERS:
        clean = re.sub(trigger, '', clean, flags=re.IGNORECASE)
    clean = clean.strip(' :،,\n')

    # Extract phone number (Saudi/Gulf formats)
    phone_match = re.search(r'(\+?[\d\s\-]{9,15})', clean)
    phone = re.sub(r'[\s\-]', '', phone_match.group(1)) if phone_match else None
    if phone_match:
        clean = clean[:phone_match.start()] + clean[phone_match.end():]

    # Split remaining text by common separators
    parts = re.split(r'[،,،\n]+', clean)
    parts = [p.strip() for p in parts if p.strip()]

    company_name = None
    contact_person = None

    for part in parts:
        # Strip label words
        val = re.sub(r'^(شركة|مؤسسة|مجموعة|اسم الشركة|company)\s*:?\s*', '', part, flags=re.IGNORECASE).strip()
        if not val:
            continue
        p_lower = part.lower()
        if any(kw in p_lower for kw in ['مسؤول', 'المسؤول', 'الشخص', 'contact', 'اسم المسؤول']):
            contact_person = re.sub(r'^(المسؤول|مسؤول|الشخص|contact)\s*:?\s*', '', part, flags=re.IGNORECASE).strip()
        elif company_name is None:
            company_name = val
        elif contact_person is None:
            contact_person = val

    if not company_name:
        return None

    return {
        'company_name': company_name,
        'contact_person': contact_person or 'غير محدد',
        'phone_number': phone or 'غير محدد',
    }


def create_customer_from_telegram(text, salesperson_id, tenant_id):
    """
    Parse text, create customer record, return (customer_id, company_name) or (None, error_msg).
    """
    data = parse_new_customer(text)
    if not data:
        return None, 'لم أتمكن من استخراج بيانات العميل'

    conn = get_db_for_tenant(tenant_id)
    if not conn:
        return None, 'خطأ في قاعدة البيانات'

    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO customers
                (company_name, contact_person, phone_number,
                 assigned_salesperson_id, tenant_id, date_added)
            VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))
        ''', (data['company_name'], data['contact_person'], data['phone_number'],
              salesperson_id, tenant_id))
        conn.commit()
        customer_id = cursor.lastrowid
        conn.close()
        return customer_id, data['company_name']
    except Exception as e:
        conn.close()
        return None, f'خطأ: {e}'


# ─── Quotation conversation state (in-memory, keyed by chat_id) ───────────────
# Structure per chat_id:
# {
#   'step': 'select_customer' | 'add_items' | 'discount' | 'notes',
#   'tenant_id': int,
#   'salesperson_id': int,
#   'customer_id': int,
#   'customer_name': str,
#   'items': [{'name', 'quantity', 'unit_price', 'discount_pct'}],
#   'discount_type': 'none'|'percent'|'fixed',
#   'discount_value': float,
#   'notes': str,
#   'customers': [{'customer_id', 'company_name'}],   # for selection step
# }
_QUOTATION_STATE: dict = {}

QUOTATION_TRIGGERS = [
    'عرض سعر', 'عرض اسعار', 'عرض أسعار', 'انشاء عرض', 'إنشاء عرض',
    'اضف عرض', 'أضف عرض', 'new quotation', 'quote', '/quote',
    'عرض جديد', 'اريد عرض', 'أريد عرض',
]

DONE_KEYWORDS   = ['انتهيت', 'خلاص', 'كفاية', 'done', '/done', 'انهيت', 'اكمل', 'أكمل']
CANCEL_KEYWORDS = ['الغ', 'إلغاء', 'cancel', '/cancel', 'الغاء', 'وقف', 'خروج']
SKIP_KEYWORDS   = ['لا', 'تخطى', 'skip', 'بدون', 'بدون خصم', 'لا خصم', 'لا يوجد']


def detect_quotation_intent(text):
    t = text.lower().strip()
    return any(trigger in t for trigger in QUOTATION_TRIGGERS)


def parse_item_line(text):
    """
    Parse a line like:
      كرسي مكتب × 5 × 200
      كرسي × 5 × 200 (5%)
      Chair 3 150
    Returns dict or None.
    """
    # Try separator-based parsing first (× , x , -)
    separators = r'[×xX\-\|,،]'
    parts = [p.strip() for p in re.split(separators, text) if p.strip()]

    # Fallback: last 1-2 tokens are numbers, rest is name
    if len(parts) < 2:
        tokens = text.strip().split()
        nums = []
        name_tokens = []
        for tok in reversed(tokens):
            clean = re.sub(r'[^\d.]', '', tok)
            if clean and len(nums) < 2:
                nums.insert(0, clean)
            else:
                name_tokens.insert(0, tok)
        if len(nums) >= 1 and name_tokens:
            parts = [' '.join(name_tokens)] + nums

    if len(parts) < 2:
        return None

    name = parts[0].strip()
    if not name:
        return None

    # Extract optional discount like "(10%)"
    disc_pct = 0.0
    disc_match = re.search(r'\((\d+(?:\.\d+)?)\s*%\)', text)
    if disc_match:
        disc_pct = float(disc_match.group(1))
        name = re.sub(r'\(\d+(?:\.\d+)?%\)', '', name).strip()

    try:
        if len(parts) >= 3:
            qty   = float(re.sub(r'[^\d.]', '', parts[1]) or 1)
            price = float(re.sub(r'[^\d.]', '', parts[2]) or 0)
        else:
            qty   = 1.0
            price = float(re.sub(r'[^\d.]', '', parts[1]) or 0)
    except ValueError:
        return None

    if price == 0:
        return None

    return {
        'name': name,
        'quantity': qty,
        'unit_price': price,
        'discount_pct': disc_pct,
        'line_total': qty * price * (1 - disc_pct / 100),
    }


def parse_discount_input(text):
    """Return (discount_type, discount_value) or ('none', 0)."""
    text = text.strip()
    if any(kw in text.lower() for kw in SKIP_KEYWORDS):
        return 'none', 0.0
    pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', text)
    if pct_match:
        return 'percent', float(pct_match.group(1))
    num_match = re.search(r'(\d+(?:\.\d+)?)', text)
    if num_match:
        return 'fixed', float(num_match.group(1))
    return 'none', 0.0


def _items_summary(items):
    lines = []
    for i, it in enumerate(items, 1):
        disc = f' (-{it["discount_pct"]}%)' if it['discount_pct'] else ''
        lines.append(
            f'{i}. {it["name"]} — {it["quantity"]:g} × {it["unit_price"]:,.0f}{disc} = {it["line_total"]:,.0f}'
        )
    return '\n'.join(lines)


def _calc_totals_bot(items, discount_type, discount_value):
    subtotal = sum(i['line_total'] for i in items)
    if discount_type == 'percent':
        disc_amt = subtotal * discount_value / 100
    elif discount_type == 'fixed':
        disc_amt = min(discount_value, subtotal)
    else:
        disc_amt = 0.0
    total = subtotal - disc_amt
    return subtotal, disc_amt, total


def create_quotation_from_state(state):
    """
    Insert a quotation + items into the DB.
    Returns (quotation_number, quotation_id) or raises.
    """
    conn = get_db_for_tenant(state['tenant_id'])
    if not conn:
        raise RuntimeError('DB error')

    items = state['items']
    disc_type  = state.get('discount_type', 'none')
    disc_value = state.get('discount_value', 0.0)
    subtotal, disc_amt, total = _calc_totals_bot(items, disc_type, disc_value)
    notes = state.get('notes', '')

    from datetime import date as _date
    cursor = conn.cursor()

    # Insert quotation
    cursor.execute('''
        INSERT INTO quotations
            (customer_id, salesperson_id, status, issue_date,
             discount_type, discount_value, tax_percent,
             subtotal, discount_amount, tax_amount, total,
             currency, notes, tenant_id)
        VALUES (?, ?, 'draft', ?, ?, ?, 0, ?, ?, 0, ?, 'SAR', ?, ?)
    ''', (
        state['customer_id'], state['salesperson_id'],
        _date.today().isoformat(),
        disc_type, disc_value,
        subtotal, disc_amt, total,
        notes, state['tenant_id'],
    ))
    qid = cursor.lastrowid

    # Set quotation number
    year = _date.today().year
    q_number = f'QT-{year}-{qid:04d}'
    cursor.execute('UPDATE quotations SET quotation_number = ? WHERE quotation_id = ?',
                   (q_number, qid))

    # Insert items
    for idx, item in enumerate(items):
        cursor.execute('''
            INSERT INTO quotation_items
                (quotation_id, name, quantity, unit_price,
                 discount_pct, line_total, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (qid, item['name'], item['quantity'], item['unit_price'],
              item['discount_pct'], item['line_total'], idx))

    conn.commit()
    conn.close()
    return q_number, qid


def handle_quotation_flow(chat_id, text, salesperson_id, tenant_id):
    """
    Drive the multi-step quotation creation conversation.
    Returns the reply string to send back.
    """
    state = _QUOTATION_STATE.get(chat_id)

    # ── Cancel at any point ──
    if any(kw in text.lower() for kw in CANCEL_KEYWORDS):
        _QUOTATION_STATE.pop(chat_id, None)
        return '❌ تم إلغاء إنشاء عرض السعر.'

    # ── Step 0: Start — list customers ──
    if state is None:
        conn = get_db_for_tenant(tenant_id)
        if not conn:
            return '⚠️ خطأ في قاعدة البيانات.'
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT customer_id, company_name FROM customers
               WHERE tenant_id = ? AND assigned_salesperson_id = ?
               ORDER BY company_name LIMIT 20''',
            (tenant_id, salesperson_id)
        )
        customers = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not customers:
            return '⚠️ لا يوجد عملاء مسجلون باسمك. أضف عميلاً أولاً.'

        _QUOTATION_STATE[chat_id] = {
            'step': 'select_customer',
            'tenant_id': tenant_id,
            'salesperson_id': salesperson_id,
            'customers': customers,
            'items': [],
            'discount_type': 'none',
            'discount_value': 0.0,
            'notes': '',
        }
        lines = '\n'.join(f'{i+1}. {c["company_name"]}' for i, c in enumerate(customers))
        return (
            '📄 <b>إنشاء عرض سعر جديد</b>\n\n'
            'اختر العميل بإرسال الرقم أو اسم الشركة:\n\n' + lines +
            '\n\nأرسل /cancel للإلغاء.'
        )

    step = state['step']

    # ── Step 1: Customer selection ──
    if step == 'select_customer':
        customers = state['customers']
        chosen = None

        # Try numeric index
        num_match = re.fullmatch(r'\d+', text.strip())
        if num_match:
            idx = int(text.strip()) - 1
            if 0 <= idx < len(customers):
                chosen = customers[idx]

        # Try name match
        if not chosen:
            t = text.strip().lower()
            for c in customers:
                if t in c['company_name'].lower() or c['company_name'].lower() in t:
                    chosen = c
                    break

        if not chosen:
            return '❓ لم أجد هذا العميل. أرسل رقم العميل من القائمة أو جزءاً من اسمه.'

        state['customer_id']   = chosen['customer_id']
        state['customer_name'] = chosen['company_name']
        state['step']          = 'add_items'

        return (
            f'✅ العميل: <b>{chosen["company_name"]}</b>\n\n'
            '📦 أرسل المنتجات/الخدمات بهذا الشكل:\n'
            '<code>اسم المنتج × الكمية × السعر</code>\n\n'
            'مثال:\n'
            '<code>كرسي مكتب × 5 × 200</code>\n'
            '<code>طاولة × 2 × 750</code>\n\n'
            'عند الانتهاء أرسل: <b>انتهيت</b>'
        )

    # ── Step 2: Add items ──
    if step == 'add_items':
        if any(kw in text.lower() for kw in DONE_KEYWORDS):
            if not state['items']:
                return '⚠️ لم تضف أي منتجات بعد. أرسل منتجاً واحداً على الأقل.'
            state['step'] = 'discount'
            summary = _items_summary(state['items'])
            subtotal = sum(i['line_total'] for i in state['items'])
            return (
                f'📋 <b>الطلبيات حتى الآن:</b>\n{summary}\n\n'
                f'💰 الإجمالي قبل الخصم: <b>{subtotal:,.0f} SAR</b>\n\n'
                'هل تريد إضافة خصم؟\n'
                '• أرسل نسبة مثل: <code>10%</code>\n'
                '• أو مبلغ ثابت مثل: <code>500</code>\n'
                '• أو <b>لا</b> لتخطي الخصم'
            )

        item = parse_item_line(text)
        if not item:
            return (
                '❓ لم أفهم. أرسل المنتج بهذا الشكل:\n'
                '<code>اسم المنتج × الكمية × السعر</code>\n\n'
                'مثال: <code>كرسي مكتب × 5 × 200</code>'
            )

        state['items'].append(item)
        disc_str = f' (خصم {item["discount_pct"]}%)' if item['discount_pct'] else ''
        return (
            f'✅ تمت الإضافة: <b>{item["name"]}</b> — '
            f'{item["quantity"]:g} × {item["unit_price"]:,.0f}{disc_str} = {item["line_total"]:,.0f} SAR\n\n'
            f'أرسل منتجاً آخر أو <b>انتهيت</b> للمتابعة.'
        )

    # ── Step 3: Discount ──
    if step == 'discount':
        disc_type, disc_value = parse_discount_input(text)
        state['discount_type']  = disc_type
        state['discount_value'] = disc_value
        state['step'] = 'notes'

        subtotal, disc_amt, total = _calc_totals_bot(state['items'], disc_type, disc_value)
        disc_str = (
            f'\n🏷️ خصم: {disc_amt:,.0f} SAR'
            if disc_type != 'none' else ''
        )
        return (
            f'💰 الإجمالي: <b>{total:,.0f} SAR</b>{disc_str}\n\n'
            'أرسل ملاحظات لعرض السعر (أو <b>لا</b> لتخطي):'
        )

    # ── Step 4: Notes → Create ──
    if step == 'notes':
        if not any(kw in text.lower() for kw in SKIP_KEYWORDS):
            state['notes'] = text.strip()

        try:
            q_number, qid = create_quotation_from_state(state)
        except Exception as e:
            _QUOTATION_STATE.pop(chat_id, None)
            return f'❌ فشل إنشاء العرض: {e}'

        _QUOTATION_STATE.pop(chat_id, None)

        subtotal, disc_amt, total = _calc_totals_bot(
            state['items'], state['discount_type'], state['discount_value']
        )
        summary = _items_summary(state['items'])
        disc_line = f'\n🏷️ خصم: {disc_amt:,.0f} SAR' if disc_amt else ''

        return (
            f'✅ <b>تم إنشاء عرض السعر بنجاح!</b>\n\n'
            f'📄 رقم العرض: <b>{q_number}</b>\n'
            f'🏢 العميل: {state["customer_name"]}\n\n'
            f'<b>المنتجات:</b>\n{summary}\n\n'
            f'💰 الإجمالي الفرعي: {subtotal:,.0f} SAR'
            f'{disc_line}\n'
            f'💵 <b>الإجمالي: {total:,.0f} SAR</b>\n\n'
            f'يمكنك مراجعة العرض وإرساله من التطبيق.'
        )

    # Unknown state — reset
    _QUOTATION_STATE.pop(chat_id, None)
    return '⚠️ حدث خطأ. أرسل /start للبدء من جديد.'


def get_db_for_tenant(tenant_id):
    """Get a DB connection using the tenant_id directly (no Flask request context needed)."""
    try:
        import sqlite3
        # Respect the same env var the rest of the app uses
        db_path = os.getenv('DATABASE_NAME', os.getenv('DB_PATH', '/data/crm_multi.db'))
        if not os.path.exists(db_path):
            # fallback for development
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'crm_multi.db')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


# ─── Webhook handler ──────────────────────────────────────────────────────────

@telegram_bp.route('/webhook', methods=['POST'])
@csrf.exempt
def webhook():
    """Telegram sends all updates here."""
    if not BOT_TOKEN:
        return jsonify({'ok': False, 'error': 'Bot not configured'}), 503

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'ok': True})

    message = data.get('message') or data.get('edited_message')
    if not message:
        return jsonify({'ok': True})

    chat_id = message['chat']['id']
    text = message.get('text', '').strip()
    voice = message.get('voice')

    conn = get_db_for_tenant(None)
    if not conn:
        send_message(chat_id, '⚠️ Database connection error.')
        return jsonify({'ok': True})

    ensure_telegram_columns(conn)

    # ── /start or /link <code> ──
    if text.startswith('/start') or text.startswith('/link'):
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else None

        if code:
            sp = get_salesperson_by_token(conn, code)
            if sp:
                # Link this Telegram chat to the salesperson account
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE sales_team SET telegram_chat_id = ?, telegram_link_token = NULL WHERE salesperson_id = ?",
                    (str(chat_id), sp['salesperson_id'])
                )
                conn.commit()
                conn.close()
                send_message(chat_id,
                    f'✅ تم ربط حسابك بنجاح! مرحباً {sp["first_name"]}.\n\n'
                    f'يمكنك الآن:\n\n'
                    f'📄 <b>إنشاء عرض سعر:</b>\n'
                    f'أرسل: <code>عرض سعر</code>\n\n'
                    f'🏢 <b>إنشاء عميل جديد:</b>\n'
                    f'<code>عميل جديد: شركة النور، المسؤول خالد، 0556789012</code>\n\n'
                    f'📝 <b>تسجيل متابعة:</b>\n'
                    f'أرسل ملاحظة نصية أو صوتية باسم العميل\n\n'
                    f'🎤 الرسائل الصوتية مدعومة بالعربي والإنجليزي'
                )
            else:
                conn.close()
                send_message(chat_id, '❌ الرمز غير صحيح أو منتهي الصلاحية.\nافتح التطبيق واحصل على رمز جديد.')
        else:
            # Check if already linked
            sp = get_salesperson_by_chat_id(conn, chat_id)
            conn.close()
            if sp:
                send_message(chat_id, f'👋 مرحباً {sp["first_name"]}!\n\nحسابك مرتبط بالفعل. أرسل ملاحظة عن أي عميل وسأضيفها تلقائياً.')
            else:
                send_message(chat_id,
                    '👋 مرحباً!\n\n'
                    'لربط حسابك:\n'
                    '1️⃣ افتح تطبيق CRM\n'
                    '2️⃣ اضغط على <b>Telegram</b> في القائمة\n'
                    '3️⃣ انسخ الرمز وأرسله هنا\n\n'
                    'مثال: /link ABC123'
                )
        return jsonify({'ok': True})

    # ── Check if user is linked ──
    sp = get_salesperson_by_chat_id(conn, chat_id)
    if not sp:
        conn.close()
        send_message(chat_id, '⚠️ حسابك غير مرتبط بعد.\nأرسل /start للبدء.')
        return jsonify({'ok': True})

    salesperson_id = sp['salesperson_id']
    tenant_id = sp['tenant_id']

    # ── Voice note → transcribe then treat as text ──
    if voice:
        send_message(chat_id, '🎤 جاري تفريغ الرسالة الصوتية...')
        try:
            # 1. Get the file path from Telegram
            file_id = voice['file_id']
            r = requests.get(f'{TELEGRAM_API}/getFile', params={'file_id': file_id}, timeout=15)
            file_path = r.json()['result']['file_path']

            # 2. Download the OGG audio
            audio_url = f'https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}'
            audio_resp = requests.get(audio_url, timeout=30)
            audio_bytes = audio_resp.content

            # 3. Transcribe
            transcribed = transcribe_voice(audio_bytes)
        except Exception as e:
            conn.close()
            send_message(chat_id, f'❌ فشل تحميل الرسالة الصوتية. حاول مرة أخرى.')
            return jsonify({'ok': True})

        if not transcribed:
            conn.close()
            send_message(chat_id, '❌ لم أتمكن من تفريغ الرسالة. تأكد من وضوح الصوت أو أرسل ملاحظتك كنص.')
            return jsonify({'ok': True})

        send_message(chat_id, f'📝 فهمت: "{transcribed}"')
        text = transcribed   # fall through to NLP parser below

    # ── Text message → quotation | new customer | follow-up ──
    if text:
        # ── Active quotation conversation ──
        if chat_id in _QUOTATION_STATE or detect_quotation_intent(text):
            conn.close()
            reply = handle_quotation_flow(chat_id, text, salesperson_id, tenant_id)
            send_message(chat_id, reply)
            return jsonify({'ok': True})

        # Check for new customer intent first
        if detect_new_customer_intent(text):
            customer_id, result = create_customer_from_telegram(text, salesperson_id, tenant_id)
            if customer_id:
                send_message(chat_id,
                    f'✅ تم إنشاء العميل بنجاح!\n\n'
                    f'🏢 <b>{result}</b>\n\n'
                    f'يمكنك الآن إرسال متابعات باسم هذا العميل.'
                )
            else:
                send_message(chat_id,
                    f'❌ فشل إنشاء العميل: {result}\n\n'
                    f'تأكد من إرسال البيانات بهذا الشكل:\n'
                    f'<code>عميل جديد: شركة النور، المسؤول خالد، 0556789012</code>'
                )
            return jsonify({'ok': True})

        parsed = parse_message_text(text, salesperson_id, tenant_id)

        if parsed and parsed['customer']:
            customer = parsed['customer']
            today = datetime.now().strftime('%Y-%m-%d')

            try:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO sales_followup (
                        customer_id, assigned_salesperson_id, last_contact_date,
                        last_contact_method, summary_last_contact, next_action,
                        current_sales_stage, tenant_id, created_at, created_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'), ?)
                ''', (
                    customer['customer_id'], salesperson_id, today,
                    'رسالة تيليجرام', text,
                    parsed['action'] or 'متابعة اتصال',
                    parsed['stage'], tenant_id, salesperson_id
                ))
                conn.commit()
                conn.close()

                stage_str = f"\n📊 المرحلة: {parsed['stage']}" if parsed['stage'] else ''
                action_str = f"\n⏭️ التالي: {parsed['action']}" if parsed['action'] else ''
                send_message(chat_id,
                    f'✅ تمت إضافة متابعة لـ <b>{customer["company_name"]}</b>{stage_str}{action_str}\n\n'
                    f'📝 الملخص: {text[:100]}{"..." if len(text)>100 else ""}'
                )
            except Exception as e:
                conn.close()
                send_message(chat_id, f'❌ حدث خطأ أثناء الحفظ. حاول مرة أخرى.')
        else:
            # Couldn't match a customer — ask for clarification
            conn2 = get_db_for_tenant(tenant_id)
            if conn2:
                cursor2 = conn2.cursor()
                cursor2.execute(
                    "SELECT company_name FROM customers WHERE tenant_id = ? AND assigned_salesperson_id = ? LIMIT 10",
                    (tenant_id, salesperson_id)
                )
                names = [r['company_name'] for r in cursor2.fetchall()]
                conn2.close()
                names_str = '\n'.join(f'• {n}' for n in names) if names else '(لا يوجد عملاء)'
            else:
                names_str = ''

            conn.close()
            send_message(chat_id,
                '🤔 لم أتمكن من تحديد العميل من رسالتك.\n\n'
                'تأكد من ذكر اسم العميل بوضوح. عملاؤك:\n' + names_str
            )
    else:
        conn.close()

    return jsonify({'ok': True})


# ─── Web UI: Account Linking ──────────────────────────────────────────────────

@telegram_bp.route('/link')
@require_tenant
def link_account():
    """Page where the salesperson gets their link code."""
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    salesperson_id = session['salesperson_id']
    conn = get_db()
    cursor = conn.cursor()
    ensure_telegram_columns(conn)

    cursor.execute(
        "SELECT first_name, telegram_chat_id, telegram_link_token FROM sales_team WHERE salesperson_id = ?",
        (salesperson_id,)
    )
    sp = cursor.fetchone()
    conn.close()

    is_linked = bool(sp and sp['telegram_chat_id'])
    link_token = sp['telegram_link_token'] if sp else None
    bot_username = os.getenv('TELEGRAM_BOT_USERNAME', 'YourCRMBot')

    return render_template('telegram/link.html',
        is_linked=is_linked,
        link_token=link_token,
        bot_username=bot_username,
    )


@telegram_bp.route('/link/generate', methods=['POST'])
@require_tenant
def generate_code():
    """Generate a fresh link code for the current salesperson."""
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    salesperson_id = session['salesperson_id']
    conn = get_db()
    cursor = conn.cursor()
    ensure_telegram_columns(conn)

    token = generate_link_token()
    cursor.execute(
        "UPDATE sales_team SET telegram_link_token = ? WHERE salesperson_id = ?",
        (token, salesperson_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('telegram.link_account'))


@telegram_bp.route('/link/disconnect', methods=['POST'])
@require_tenant
def disconnect():
    """Unlink Telegram from this account."""
    if 'salesperson_id' not in session:
        return redirect(url_for('auth.login'))

    salesperson_id = session['salesperson_id']
    conn = get_db()
    cursor = conn.cursor()
    ensure_telegram_columns(conn)
    cursor.execute(
        "UPDATE sales_team SET telegram_chat_id = NULL, telegram_link_token = NULL WHERE salesperson_id = ?",
        (salesperson_id,)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('telegram.link_account'))


# ─── Webhook registration helper ─────────────────────────────────────────────

def set_webhook(base_url=None):
    """Call this once to register the webhook with Telegram."""
    base_url = (base_url or os.getenv('APP_BASE_URL', '')).rstrip('/')
    webhook_url = f'{base_url}/telegram/webhook'
    resp = requests.post(f'{TELEGRAM_API}/setWebhook', json={'url': webhook_url})
    print(resp.json())


@telegram_bp.route('/status')
@require_tenant
def bot_status():
    """Admin-only: show live bot + webhook status for debugging."""
    if session.get('role') != 'admin':
        return jsonify({'error': 'admin only'}), 403

    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    result = {
        'token_set': bool(token),
        'token_prefix': token[:10] + '...' if token else None,
        'database_name_env': os.getenv('DATABASE_NAME', '(not set)'),
        'app_base_url_env': os.getenv('APP_BASE_URL', '(not set)'),
    }

    if token:
        api = f'https://api.telegram.org/bot{token}'
        try:
            me = requests.get(f'{api}/getMe', timeout=8).json()
            result['bot_info'] = me
        except Exception as e:
            result['bot_info_error'] = str(e)
        try:
            wh = requests.get(f'{api}/getWebhookInfo', timeout=8).json()
            result['webhook_info'] = wh
        except Exception as e:
            result['webhook_info_error'] = str(e)

    return jsonify(result)


@telegram_bp.route('/register-webhook', methods=['POST'])
@require_tenant
def register_webhook():
    """Admin-only: re-register the Telegram webhook URL."""
    if session.get('role') != 'admin':
        flash('Admin only.', 'error')
        return redirect(url_for('telegram.link_account'))

    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    if not token:
        flash('TELEGRAM_BOT_TOKEN is not set in environment variables.', 'error')
        return redirect(url_for('telegram.link_account'))

    base_url = os.getenv('APP_BASE_URL', request.host_url).rstrip('/')
    webhook_url = f'{base_url}/telegram/webhook'
    api = f'https://api.telegram.org/bot{token}'
    try:
        resp = requests.post(f'{api}/setWebhook', json={'url': webhook_url}, timeout=10)
        data = resp.json()
        if data.get('ok'):
            flash(f'✅ Webhook registered: {webhook_url}', 'success')
        else:
            flash(f'❌ Telegram error: {data.get("description", "unknown")}', 'error')
    except Exception as e:
        flash(f'❌ Request failed: {e}', 'error')

    return redirect(url_for('telegram.link_account'))
