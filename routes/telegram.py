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


def get_bot_token():
    return os.getenv('TELEGRAM_BOT_TOKEN', '')


def get_api_base():
    token = get_bot_token()
    return f'https://api.telegram.org/bot{token}' if token else ''


# ─── Helpers ──────────────────────────────────────────────────────────────────

def send_message(chat_id, text, parse_mode='HTML'):
    token = get_bot_token()
    if not token:
        return
    requests.post(f'{get_api_base()}/sendMessage', json={
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
    }, timeout=10)


def send_document(chat_id, pdf_bytes, filename, caption=''):
    """Send a PDF file to a Telegram chat via sendDocument."""
    token = get_bot_token()
    if not token:
        return
    requests.post(
        f'{get_api_base()}/sendDocument',
        data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'},
        files={'document': (filename, pdf_bytes, 'application/pdf')},
        timeout=30,
    )


def generate_quotation_pdf_bytes(quotation_id, tenant_id):
    """
    Fetch quotation from DB, render quotation_pdf.html, convert to PDF bytes.
    Returns (pdf_bytes, quotation_number) or raises RuntimeError.
    Must be called from within a Flask application context.
    """
    from flask import render_template as _render
    conn = get_db_for_tenant(tenant_id)
    if not conn:
        raise RuntimeError('DB connection failed')

    q = conn.execute('''
        SELECT q.*,
               c.company_name, c.contact_person, c.phone_number,
               c.email_address, c.company_address,
               sp.salesperson_name, sp.work_email AS sp_email,
               sp.phone_number AS sp_phone
        FROM quotations q
        JOIN customers  c  ON q.customer_id   = c.customer_id
        JOIN sales_team sp ON q.salesperson_id = sp.salesperson_id
        WHERE q.quotation_id = ? AND q.tenant_id = ?
    ''', (quotation_id, tenant_id)).fetchone()

    if not q:
        conn.close()
        raise RuntimeError('Quotation not found')

    items = conn.execute(
        'SELECT * FROM quotation_items WHERE quotation_id = ? ORDER BY sort_order',
        (quotation_id,)
    ).fetchall()
    conn.close()

    html = _render('quotations/quotation_pdf.html',
                   quotation=dict(q), items=items)

    q_number = dict(q).get('quotation_number', str(quotation_id))
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Try WeasyPrint first (full Arabic/RTL support)
    try:
        from weasyprint import HTML as WP_HTML
        pdf_bytes = WP_HTML(string=html, base_url=f'file://{_base}/').write_pdf()
        return pdf_bytes, q_number
    except ImportError:
        pass

    # Fallback: xhtml2pdf
    try:
        from xhtml2pdf import pisa
        import io as _io
        def _cb(uri, rel):
            if uri.startswith('/static/fonts/'):
                font_name = uri.split('/')[-1]
                sys_path = f'/usr/share/fonts/truetype/amiri/{font_name}'
                if os.path.exists(sys_path):
                    return sys_path
                local = os.path.join(_base, 'static', 'fonts', font_name)
                if os.path.exists(local) and os.path.getsize(local) > 10000:
                    return local
            elif uri.startswith('/static/'):
                return os.path.join(_base, 'static', uri[8:])
            return uri
        buf = _io.BytesIO()
        status = pisa.CreatePDF(html.encode('utf-8'), dest=buf, encoding='utf-8', link_callback=_cb)
        if status.err:
            raise RuntimeError('xhtml2pdf error')
        return buf.getvalue(), q_number
    except ImportError:
        raise RuntimeError('No PDF library available')


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
    sp = cursor.fetchone()
    if not sp:
        return None
    expires = sp['telegram_token_expires'] if 'telegram_token_expires' in sp.keys() else None
    if expires:
        try:
            if datetime.fromisoformat(expires) < datetime.now():
                return None  # expired
        except Exception:
            pass
    return sp


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

# ─── NLP helpers ─────────────────────────────────────────────────────────────

STAGE_KEYWORDS = {
    'عميل محتمل':       ['عميل محتمل', 'جديد', 'اتصل', 'اتصلت', 'تواصلت معه لأول'],
    'جاري التواصل':     ['جاري التواصل', 'تواصلنا', 'تواصلت', 'تحدثت', 'كلمته',
                         'تكلمنا', 'رددت عليه', 'رد علي', 'على تواصل'],
    'تقديم عرض السعر': ['عرض سعر', 'قدمت عرض', 'ارسلت عرض', 'أرسلت عرض',
                         'بعثت عرض', 'هبعت عرض', 'طلب عرض'],
    'جاري التفاوض':     ['تفاوض', 'تفاوضنا', 'يفاوض', 'موافق', 'يناقش',
                         'نتفاوض', 'مناقشة السعر', 'يريد تعديل'],
    'تم التسليم':       ['تسليم', 'تم التسليم', 'سلمنا', 'انتهى', 'اكتمل',
                         'اشترى', 'وقّع', 'دفع', 'تم البيع', 'اتفقنا'],
    'لم يتم البيع':     ['رفض', 'لم يوافق', 'فشل', 'خسرنا', 'مش مهتم',
                         'رفض العرض', 'ما وافق', 'انتهى سلباً'],
}

ACTION_KEYWORDS = {
    'متابعة اتصال':           ['اتصل', 'اتصال', 'تابع', 'اتصل به', 'هتصل'],
    'انتظار رد العميل':       ['انتظار', 'ينتظر', 'رد', 'في انتظار', 'ما رد', 'لسه مارد'],
    'إرسال عرض سعر':          ['ارسل عرض', 'أرسل عرض', 'هبعت عرض', 'عرض سعر'],
    'دعوة لزيارة المعرض':     ['زيارة', 'يزور', 'معرض', 'يجي', 'يحضر'],
    'متابعة التمويل / الدفع': ['دفع', 'تمويل', 'فاتورة', 'سداد', 'دفعة'],
    'إغلاق البيع':             ['اغلق', 'اغلاق', 'انهى', 'نغلق', 'نهائي'],
}

CONTACT_METHOD_KEYWORDS = {
    'اتصال':   ['اتصل', 'اتصلت', 'تصلت', 'call', 'كلمته بالتلفون'],
    'واتساب':  ['واتساب', 'whatsapp', 'واتس', 'رسالة'],
    'زيارة':   ['زرته', 'زيارة', 'قابلته', 'ذهبت', 'visit'],
    'إيميل':   ['إيميل', 'ايميل', 'email', 'بعثت ايميل'],
    'اجتماع':  ['اجتماع', 'اجتمعنا', 'meeting', 'لقاء'],
}

def _detect_contact_method(text):
    t = text.lower()
    for method, kws in CONTACT_METHOD_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return method
    return None

def parse_message_text(text, salesperson_id, tenant_id):
    """
    Lightweight Arabic NLP — returns parsed dict for quick-confirm flow.
    Never saves directly.
    """
    text_lower = text.lower()

    stage = None
    for s, keywords in STAGE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            stage = s
            break

    action = None
    for a, keywords in ACTION_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            action = a
            break

    contact_method = _detect_contact_method(text)

    conn = get_db_for_tenant(tenant_id)
    if not conn:
        return None

    cursor = conn.cursor()
    cursor.execute(
        '''SELECT customer_id, company_name, company_id, current_stage
           FROM customers WHERE tenant_id = ? AND assigned_salesperson_id = ?
           AND is_active = 1''',
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
        'customer':       matched_customer,
        'stage':          stage,
        'action':         action,
        'contact_method': contact_method,
        'summary':        text,
    }


# ─── Follow-up conversational flow ───────────────────────────────────────────

FOLLOWUP_TRIGGERS = [
    'متابعة', 'متابعه', 'اضف متابعة', 'اضف متابعه',
    'إضافة متابعة', 'سجل متابعة', 'سجل متابعه',
    'تسجيل متابعة', 'اضف تواصل', 'سجل تواصل',
    'متابعة عميل', 'follow up', 'followup', 'add followup',
]

CONTACT_METHODS  = ['اتصال', 'واتساب', 'زيارة', 'إيميل', 'اجتماع']
STAGES_LIST      = [
    'عميل محتمل', 'جاري التواصل', 'تقديم عرض السعر',
    'جاري التفاوض', 'تم التسليم', 'لم يتم البيع',
]
NEXT_ACTIONS_LIST = [
    'متابعة اتصال', 'إرسال عرض سعر', 'دعوة لزيارة المعرض',
    'انتظار رد العميل', 'متابعة التمويل / الدفع', 'إغلاق البيع',
]

_FOLLOWUP_STATE: dict = {}
_FU_CANCEL = ['الغ', 'إلغاء', 'الغاء', 'cancel', '/cancel', 'وقف', 'خروج']
_FU_SKIP   = ['تخطى', 'تخطي', 'skip', 'بدون', 'لا يوجد', '/skip']


def detect_followup_intent(text):
    t = text.strip().lower()
    return any(trigger in t for trigger in FOLLOWUP_TRIGGERS)


def _parse_date_input(text):
    """Parse Arabic/numeric date. Returns YYYY-MM-DD or None."""
    from datetime import timedelta
    t = text.strip().lower()
    if t in ('غداً', 'غدا', 'غدًا', 'tomorrow', 'بكرا', 'بكره'):
        return (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    if t in ('بعد غد', 'بعد غداً', 'بعد غدا'):
        return (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')
    m = re.match(r'^(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?$', t)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else datetime.now().year
        if year < 100:
            year += 2000
        try:
            from datetime import date as _date
            return _date(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return None


def _save_followup(state, actor_name):
    """Insert follow-up into activities table. Returns (activity_id, error_msg)."""
    conn = get_db_for_tenant(state['tenant_id'])
    if not conn:
        return None, 'خطأ في قاعدة البيانات'
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO activities (
                tenant_id, entity_type, entity_id, action,
                actor_name, details,
                activity_type, contact_date, summary,
                sales_stage, next_action, next_action_due,
                deal_value,
                created_by, company_id, created_at
            ) VALUES (?, 'customer', ?, 'follow_up',
                      ?, ?,
                      ?, ?, ?,
                      ?, ?, ?,
                      ?,
                      ?, ?, datetime('now','localtime'))
        ''', (
            state['tenant_id'], state['customer_id'],
            actor_name, f'متابعة تيليجرام — {state.get("stage") or "—"}',
            state.get('contact_method') or 'تيليجرام',
            state.get('contact_date') or datetime.now().strftime('%Y-%m-%d'),
            state.get('summary', ''),
            state.get('stage'), state.get('next_action'), state.get('next_action_date'),
            state.get('deal_value'),
            state['salesperson_id'], state.get('company_id'),
        ))
        conn.commit()
        activity_id = cursor.lastrowid
        conn.close()
        return activity_id, None
    except Exception as e:
        conn.close()
        return None, str(e)


def _followup_confirm_text(state):
    method   = state.get('contact_method') or '—'
    stage    = state.get('stage') or '—'
    summary  = state.get('summary') or '—'
    action   = state.get('next_action') or '—'
    act_date = state.get('next_action_date') or '—'
    deal     = f'{state["deal_value"]:,.0f} ر.س' if state.get('deal_value') else '—'
    return (
        f'📋 <b>مراجعة المتابعة</b>\n\n'
        f'🏢 العميل: <b>{state["customer_name"]}</b>\n'
        f'📞 طريقة التواصل: {method}\n'
        f'📊 المرحلة: {stage}\n'
        f'📝 الملخص: {summary[:80]}{"..." if len(summary) > 80 else ""}\n'
        f'⏭️ الإجراء القادم: {action}\n'
        f'📅 تاريخ الإجراء: {act_date}\n'
        f'💰 قيمة الصفقة: {deal}\n\n'
        f'✅ <b>نعم</b> — للحفظ\n'
        f'🔄 <b>لا</b> — للإلغاء'
    )


def handle_followup_flow(chat_id, text, salesperson_id, tenant_id, actor_name=''):
    """
    Conversational follow-up creation — two entry modes:
      • quick_confirm: arrived from free-text detection, customer already matched
      • guided:        arrived from FOLLOWUP_TRIGGERS, step-by-step selection
    Returns reply string or None.
    """
    t       = text.strip()
    t_lower = t.lower()

    if any(kw in t_lower for kw in _FU_CANCEL):
        _FOLLOWUP_STATE.pop(chat_id, None)
        return '❌ تم إلغاء المتابعة.'

    state = _FOLLOWUP_STATE.get(chat_id)
    step  = state['step'] if state else None

    # ── Quick confirm (from free-text detection) ──────────────────────────────
    if step == 'quick_confirm':
        if any(kw in t_lower for kw in ['نعم', 'yes', 'تمام', 'صح', 'اكيد', 'أكيد', 'موافق']):
            act_id, err = _save_followup(state, actor_name)
            _FOLLOWUP_STATE.pop(chat_id, None)
            if act_id:
                action_line = f'\n⏭️ {state["next_action"]}' if state.get('next_action') else ''
                return f'✅ <b>تمت إضافة المتابعة!</b>\n\n🏢 {state["customer_name"]}\n📊 {state.get("stage") or "—"}{action_line}'
            return f'❌ فشل الحفظ: {err}'
        elif any(kw in t_lower for kw in ['لا', 'no', 'لأ', 'تعديل', 'غلط', 'خطأ']):
            # Drop to guided — customer already set, start from contact_method
            state['step'] = 'contact_method'
            methods = '\n'.join(f'{i+1}️⃣ {m}' for i, m in enumerate(CONTACT_METHODS))
            return f'📞 <b>طريقة التواصل:</b>\n\n{methods}'
        else:
            return '❓ أرسل <b>نعم</b> للحفظ أو <b>لا</b> للتعديل.'

    # ── Guided Step 0: Start — list customers ────────────────────────────────
    if state is None:
        conn = get_db_for_tenant(tenant_id)
        if not conn:
            return '⚠️ خطأ في قاعدة البيانات.'
        rows = conn.execute('''
            SELECT customer_id, company_name, company_id, current_stage
            FROM customers
            WHERE tenant_id = ? AND assigned_salesperson_id = ? AND is_active = 1
            ORDER BY company_name LIMIT 15
        ''', (tenant_id, salesperson_id)).fetchall()
        conn.close()
        if not rows:
            return '⚠️ لا يوجد عملاء مسجلون باسمك.'
        _FOLLOWUP_STATE[chat_id] = {
            'step': 'customer_select',
            'salesperson_id': salesperson_id,
            'tenant_id': tenant_id,
            'customers': [dict(r) for r in rows],
        }
        lines = '\n'.join(
            f'{i+1}. {r["company_name"]}' + (f' — {r["current_stage"]}' if r['current_stage'] else '')
            for i, r in enumerate(rows)
        )
        return (
            '📝 <b>إضافة متابعة</b>\n\n'
            'اختر العميل:\n\n' + lines +
            '\n\nأرسل الرقم أو جزء من الاسم — أو /cancel للإلغاء'
        )

    # ── Guided Step 1: Customer selection ────────────────────────────────────
    if step == 'customer_select':
        customers = state['customers']
        chosen = None
        if re.fullmatch(r'\d+', t):
            idx = int(t) - 1
            if 0 <= idx < len(customers):
                chosen = customers[idx]
        if not chosen:
            tl = t.lower()
            for c in customers:
                if tl in c['company_name'].lower() or c['company_name'].lower() in tl:
                    chosen = c
                    break
        if not chosen:
            return '❓ لم أجد هذا العميل. أرسل رقمه من القائمة أو جزءاً من اسمه.'

        state.update({
            'customer_id':   chosen['customer_id'],
            'customer_name': chosen['company_name'],
            'company_id':    chosen.get('company_id'),
            'current_stage': chosen.get('current_stage'),
            'step':          'contact_method',
        })
        methods = '\n'.join(f'{i+1}️⃣ {m}' for i, m in enumerate(CONTACT_METHODS))
        return f'📞 <b>طريقة التواصل:</b>\n\n{methods}'

    # ── Guided Step 2: Contact method ────────────────────────────────────────
    if step == 'contact_method':
        chosen_m = None
        if re.fullmatch(r'\d+', t):
            idx = int(t) - 1
            if 0 <= idx < len(CONTACT_METHODS):
                chosen_m = CONTACT_METHODS[idx]
        if not chosen_m:
            for m in CONTACT_METHODS:
                if m in t or t in m:
                    chosen_m = m
                    break
        if not chosen_m:
            methods = '\n'.join(f'{i+1}️⃣ {m}' for i, m in enumerate(CONTACT_METHODS))
            return f'❓ اختر رقم طريقة التواصل:\n\n{methods}'

        state['contact_method'] = chosen_m
        state['step'] = 'stage'
        cur = state.get('current_stage')
        header = f'المرحلة الحالية: <b>{cur}</b>\n\n' if cur else ''
        stages = '\n'.join(f'{i+1}️⃣ {s}' for i, s in enumerate(STAGES_LIST))
        return f'📊 <b>مرحلة البيع:</b>\n\n{header}{stages}\n\nأو <b>تخطى</b> للإبقاء على المرحلة الحالية'

    # ── Guided Step 3: Stage ─────────────────────────────────────────────────
    if step == 'stage':
        if any(kw in t_lower for kw in _FU_SKIP):
            state['stage'] = state.get('current_stage')
        elif re.fullmatch(r'\d+', t):
            idx = int(t) - 1
            if 0 <= idx < len(STAGES_LIST):
                state['stage'] = STAGES_LIST[idx]
            else:
                stages = '\n'.join(f'{i+1}️⃣ {s}' for i, s in enumerate(STAGES_LIST))
                return f'❓ أرسل رقماً من 1 إلى {len(STAGES_LIST)}:\n\n{stages}'
        else:
            for s in STAGES_LIST:
                if s in t or t in s:
                    state['stage'] = s
                    break
            else:
                stages = '\n'.join(f'{i+1}️⃣ {s}' for i, s in enumerate(STAGES_LIST))
                return f'❓ أرسل رقم المرحلة أو <b>تخطى</b>:\n\n{stages}'
        state['step'] = 'summary'
        return '📝 اكتب <b>ملخص المحادثة</b> (أو أرسل رسالة صوتية):'

    # ── Guided Step 4: Summary ───────────────────────────────────────────────
    if step == 'summary':
        if len(t) < 3:
            return '❓ الملخص قصير جداً. اكتب ما تم التحدث عنه:'
        state['summary'] = t
        state['step'] = 'next_action'
        actions = '\n'.join(f'{i+1}️⃣ {a}' for i, a in enumerate(NEXT_ACTIONS_LIST))
        return f'⏭️ <b>الإجراء القادم:</b>\n\n{actions}\n\nأو <b>تخطى</b>'

    # ── Guided Step 5: Next action ───────────────────────────────────────────
    if step == 'next_action':
        if any(kw in t_lower for kw in _FU_SKIP):
            state['next_action'] = None
            state['step'] = 'deal_value'
            return '💰 <b>قيمة الصفقة المتوقعة</b> بالريال (أو <b>تخطى</b>):'
        chosen_a = None
        if re.fullmatch(r'\d+', t):
            idx = int(t) - 1
            if 0 <= idx < len(NEXT_ACTIONS_LIST):
                chosen_a = NEXT_ACTIONS_LIST[idx]
        if not chosen_a:
            for a in NEXT_ACTIONS_LIST:
                if a in t or t in a:
                    chosen_a = a
                    break
        if not chosen_a:
            actions = '\n'.join(f'{i+1}️⃣ {a}' for i, a in enumerate(NEXT_ACTIONS_LIST))
            return f'❓ أرسل رقم الإجراء أو <b>تخطى</b>:\n\n{actions}'
        state['next_action'] = chosen_a
        state['step'] = 'next_action_date'
        return '📅 <b>تاريخ الإجراء القادم:</b>\n\nمثال: <code>غداً</code> أو <code>25/5</code> أو <b>تخطى</b>'

    # ── Guided Step 6: Next action date ─────────────────────────────────────
    if step == 'next_action_date':
        if any(kw in t_lower for kw in _FU_SKIP):
            state['next_action_date'] = None
        else:
            parsed_date = _parse_date_input(t)
            if not parsed_date:
                return '❓ تاريخ غير صحيح. مثال: <code>غداً</code> أو <code>25/5</code> أو <b>تخطى</b>'
            state['next_action_date'] = parsed_date
        state['step'] = 'deal_value'
        return '💰 <b>قيمة الصفقة المتوقعة</b> بالريال (أو <b>تخطى</b>):'

    # ── Guided Step 7: Deal value ────────────────────────────────────────────
    if step == 'deal_value':
        if any(kw in t_lower for kw in _FU_SKIP):
            state['deal_value'] = None
        else:
            num = re.sub(r'[^\d.]', '', t)
            if not num:
                return '❓ أرسل رقماً مثل <code>5000</code> أو <b>تخطى</b>:'
            state['deal_value'] = float(num)
        state['step'] = 'confirm'
        return _followup_confirm_text(state)

    # ── Guided Step 8: Confirm ───────────────────────────────────────────────
    if step == 'confirm':
        if any(kw in t_lower for kw in ['نعم', 'yes', 'تمام', 'صح', 'اكيد', 'أكيد', 'موافق']):
            act_id, err = _save_followup(state, actor_name)
            _FOLLOWUP_STATE.pop(chat_id, None)
            if act_id:
                action_line = f'\n⏭️ الإجراء: {state["next_action"]}' if state.get('next_action') else ''
                date_line   = f'\n📅 موعده: {state["next_action_date"]}' if state.get('next_action_date') else ''
                return (
                    f'✅ <b>تمت إضافة المتابعة!</b>\n\n'
                    f'🏢 {state["customer_name"]}\n'
                    f'📊 {state.get("stage") or "—"}'
                    f'{action_line}{date_line}'
                )
            return f'❌ فشل الحفظ: {err}'
        elif any(kw in t_lower for kw in ['لا', 'no', 'لأ', 'غلط', 'خطأ']):
            _FOLLOWUP_STATE.pop(chat_id, None)
            return '🔄 تم الإلغاء. أرسل <b>متابعة</b> للبدء من جديد.'
        else:
            return '❓ أرسل <b>نعم</b> للحفظ أو <b>لا</b> للإلغاء.'

    _FOLLOWUP_STATE.pop(chat_id, None)
    return '⚠️ حدث خطأ. أرسل /start للبدء من جديد.'


# ─── New customer conversational flow ────────────────────────────────────────

import re

NEW_CUSTOMER_TRIGGERS = [
    # عميل
    'عميل جديد', 'عميل جديده', 'عملاء جدد',
    'اضف عميل', 'أضف عميل', 'اضيف عميل', 'أضيف عميل',
    'سجل عميل', 'سجّل عميل', 'تسجيل عميل',
    'اريد اضيف عميل', 'أريد أضيف عميل', 'عايز اضيف عميل',
    'عايز اسجل عميل', 'اريد تسجيل عميل',
    # زبون
    'زبون جديد', 'زبون جديده', 'اضف زبون', 'أضف زبون',
    # شركة
    'شركه جديده', 'شركة جديدة', 'شركه جديد',
    'اضف شركه', 'أضف شركة', 'اضف شركة',
    'سجل شركه', 'سجل شركة',
    # مشروع
    'مشروع جديد', 'مشروع جديده',
    'اضف مشروع', 'أضف مشروع', 'سجل مشروع',
    # إضافة
    'اضافه عميل', 'إضافة عميل', 'اضافة عميل',
    'اضافه شركه', 'إضافة شركة',
    # جهة اتصال
    'جهة اتصال', 'جهه اتصال', 'اضف جهة اتصال', 'اضف جهه اتصال',
    'سجل جهة اتصال', 'شخص جديد', 'اضف شخص', 'فرد جديد',
    # English
    'new customer', 'add customer', 'new client', 'add client',
    'new contact', 'add contact',
]

def detect_new_customer_intent(text):
    t = text.strip().lower()
    return any(trigger in t for trigger in NEW_CUSTOMER_TRIGGERS)


def _save_new_customer(state):
    """Insert collected customer data into DB. Returns (customer_id, error_msg)."""
    conn = get_db_for_tenant(state['tenant_id'])
    if not conn:
        return None, 'خطأ في قاعدة البيانات'
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO customers
                (company_name, contact_person, phone_number,
                 email_address, contact_person_position,
                 assigned_salesperson_id, tenant_id,
                 lead_source, date_added)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'telegram', datetime('now','localtime'))
        ''', (
            state['company_name'],
            state['contact_person'],
            state['phone'],
            state.get('email') or None,
            state.get('position') or None,
            state['salesperson_id'],
            state['tenant_id'],
        ))
        conn.commit()
        customer_id = cursor.lastrowid
        conn.close()
        return customer_id, None
    except Exception as e:
        conn.close()
        return None, str(e)


# ─── New-customer state machine ───────────────────────────────────────────────
# Steps: type_choice → name → contact_person → phone → email → position → confirm

_NEW_CUSTOMER_STATE: dict = {}

_NC_CANCEL = ['الغ', 'إلغاء', 'الغاء', 'cancel', '/cancel', 'وقف', 'خروج']
_NC_SKIP   = ['تخطى', 'تخطي', 'skip', 'لا', 'بدون', 'لا يوجد', '/skip']


def _is_valid_phone(text):
    digits = re.sub(r'[\s\-\+]', '', text)
    return digits.isdigit() and 8 <= len(digits) <= 15


def _is_valid_email(text):
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', text.strip()))


def handle_new_customer_flow(chat_id, text, salesperson_id, tenant_id):
    """
    Conversational new-customer creation.
    Returns reply string, or None if already sent.
    """
    t = text.strip()
    t_lower = t.lower()

    # Cancel at any point
    if any(kw in t_lower for kw in _NC_CANCEL):
        _NEW_CUSTOMER_STATE.pop(chat_id, None)
        return '❌ تم إلغاء إضافة العميل.'

    state = _NEW_CUSTOMER_STATE.get(chat_id)

    # ── Step 0: Start ──
    if state is None:
        _NEW_CUSTOMER_STATE[chat_id] = {
            'step': 'type_choice',
            'salesperson_id': salesperson_id,
            'tenant_id': tenant_id,
        }
        return (
            '🏢 <b>إضافة عميل جديد</b>\n\n'
            'هل تريد إضافة:\n\n'
            '1️⃣ شركة\n'
            '2️⃣ مشروع\n'
            '3️⃣ جهة اتصال (شخص)\n\n'
            'أرسل الرقم أو اكتب نوعه — أو /cancel للإلغاء'
        )

    step = state['step']

    # ── Step 1: نوع العميل ──
    if step == 'type_choice':
        if t in ('1', 'شركه', 'شركة', 'company'):
            state['customer_type'] = 'شركة'
            state['step'] = 'name'
            return '🏢 اكتب <b>اسم الشركة</b>:'
        elif t in ('2', 'مشروع', 'project'):
            state['customer_type'] = 'مشروع'
            state['step'] = 'name'
            return '📁 اكتب <b>اسم المشروع</b>:'
        elif t in ('3', 'جهة اتصال', 'جهه اتصال', 'شخص', 'فرد', 'contact', 'person'):
            state['customer_type'] = 'جهة اتصال'
            state['step'] = 'name'
            return '👤 اكتب <b>اسم الشخص</b> كاملاً:'
        else:
            return '❓ أرسل <b>1</b> للشركة، <b>2</b> للمشروع، أو <b>3</b> لجهة اتصال.'

    # ── Step 2: الاسم ──
    if step == 'name':
        if len(t) < 2:
            return '❓ الاسم قصير جداً. أعد الكتابة:'
        state['company_name'] = t
        if state.get('customer_type') == 'جهة اتصال':
            # الشخص هو جهة الاتصال — نتخطى سؤال المسؤول
            state['contact_person'] = t
            state['step'] = 'phone'
            return '📱 اكتب <b>رقم الجوال</b>:'
        state['step'] = 'contact_person'
        return '👤 اكتب <b>اسم المسؤول</b> / جهة الاتصال:'

    # ── Step 3: المسؤول ──
    if step == 'contact_person':
        if len(t) < 2:
            return '❓ الاسم قصير جداً. أعد الكتابة:'
        state['contact_person'] = t
        state['step'] = 'phone'
        return '📱 اكتب <b>رقم الجوال</b>:'

    # ── Step 4: الجوال ──
    if step == 'phone':
        if not _is_valid_phone(t):
            return '❓ رقم غير صحيح. أرسل رقم جوال صحيح (مثال: 0556789012):'
        state['phone'] = re.sub(r'[\s\-]', '', t)
        state['step'] = 'email'
        return '📧 اكتب <b>الإيميل</b> (أو أرسل <b>تخطى</b>):'

    # ── Step 5: الإيميل ──
    if step == 'email':
        if any(kw in t_lower for kw in _NC_SKIP):
            state['email'] = None
        elif _is_valid_email(t):
            state['email'] = t.strip()
        else:
            return '❓ الإيميل غير صحيح. أرسل إيميل صحيح أو <b>تخطى</b>:'
        state['step'] = 'position'
        return '💼 اكتب <b>المسمى الوظيفي</b> للمسؤول (أو أرسل <b>تخطى</b>):'

    # ── Step 6: المسمى الوظيفي ──
    if step == 'position':
        state['position'] = None if any(kw in t_lower for kw in _NC_SKIP) else t
        state['step'] = 'confirm'

        ctype    = state['customer_type']
        cname    = state['company_name']
        contact  = state['contact_person']
        phone    = state['phone']
        email    = state.get('email') or '—'
        position = state.get('position') or '—'

        return (
            f'📋 <b>مراجعة البيانات</b>\n\n'
            f'النوع: {ctype}\n'
            f'الاسم: <b>{cname}</b>\n'
            f'المسؤول: {contact}\n'
            f'الجوال: {phone}\n'
            f'الإيميل: {email}\n'
            f'المسمى الوظيفي: {position}\n\n'
            f'هل البيانات صحيحة؟\n'
            f'✅ <b>نعم</b> — للحفظ\n'
            f'🔄 <b>لا</b> — للبدء من جديد'
        )

    # ── Step 7: التأكيد ──
    if step == 'confirm':
        if any(kw in t_lower for kw in ['نعم', 'yes', 'تمام', 'صح', 'اكيد', 'أكيد', 'موافق', '✅']):
            customer_id, err = _save_new_customer(state)
            _NEW_CUSTOMER_STATE.pop(chat_id, None)
            if customer_id:
                return (
                    f'✅ <b>تم إضافة العميل بنجاح!</b>\n\n'
                    f'🏢 {state["company_name"]}\n'
                    f'👤 {state["contact_person"]}\n'
                    f'📱 {state["phone"]}\n\n'
                    f'يمكنك الآن إرسال متابعات باسم هذا العميل.'
                )
            else:
                return f'❌ فشل الحفظ: {err}'
        elif any(kw in t_lower for kw in ['لا', 'no', 'لأ', 'غلط', 'خطأ']):
            _NEW_CUSTOMER_STATE.pop(chat_id, None)
            return '🔄 تم الإلغاء. أرسل <b>عميل جديد</b> للبدء من جديد.'
        else:
            return '❓ أرسل <b>نعم</b> للحفظ أو <b>لا</b> للإلغاء.'

    # حالة غير معروفة — reset
    _NEW_CUSTOMER_STATE.pop(chat_id, None)
    return '⚠️ حدث خطأ. أرسل /start للبدء من جديد.'


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


PDF_TRIGGERS = ['pdf', 'بي دي اف', 'ارسل العرض', 'أرسل العرض', 'ارسل pdf', 'إرسال العرض']


def _send_quotation_pdf(chat_id, quotation_id, tenant_id, q_number=None):
    """Generate PDF for quotation_id and send it to chat_id."""
    try:
        pdf_bytes, q_num = generate_quotation_pdf_bytes(quotation_id, tenant_id)
        fname   = f'quotation-{q_num}.pdf'
        caption = f'📄 عرض السعر <b>{q_num}</b>'
        send_document(chat_id, pdf_bytes, fname, caption)
    except Exception as e:
        send_message(chat_id, f'⚠️ تعذّر إنشاء PDF: {e}')


def handle_pdf_command(chat_id, text, salesperson_id, tenant_id):
    """
    Handle: pdf QT-2026-0001  OR  pdf 5  (quotation_id)
    Returns reply string or None if already sent.
    """
    # Extract identifier after the trigger keyword
    parts = text.strip().split(maxsplit=1)
    identifier = parts[1].strip() if len(parts) > 1 else ''

    conn = get_db_for_tenant(tenant_id)
    if not conn:
        return '⚠️ خطأ في قاعدة البيانات.'

    q = None
    if identifier:
        # Try quotation number match first
        q = conn.execute(
            '''SELECT quotation_id, quotation_number FROM quotations
               WHERE tenant_id = ? AND (quotation_number = ? OR quotation_id = ?)
               ORDER BY created_at DESC LIMIT 1''',
            (tenant_id, identifier.upper(), identifier if identifier.isdigit() else -1)
        ).fetchone()

    if not q:
        # No identifier — list last 5 quotations for this salesperson
        rows = conn.execute(
            '''SELECT q.quotation_id, q.quotation_number, c.company_name, q.total, q.status
               FROM quotations q
               JOIN customers c ON q.customer_id = c.customer_id
               WHERE q.tenant_id = ? AND q.salesperson_id = ?
                 AND q.status != 'cancelled'
               ORDER BY q.created_at DESC LIMIT 8''',
            (tenant_id, salesperson_id)
        ).fetchall()
        conn.close()

        if not rows:
            return '⚠️ لا توجد عروض أسعار.'

        lines = '\n'.join(
            f'{i+1}. <b>{r["quotation_number"]}</b> — {r["company_name"]} — {r["total"]:,.0f} SAR ({r["status"]})'
            for i, r in enumerate(rows)
        )
        return (
            '📄 <b>عروض الأسعار الأخيرة:</b>\n\n' + lines +
            '\n\nأرسل: <code>pdf QT-2026-0001</code> لاستلام PDF'
        )

    conn.close()
    send_message(chat_id, f'⏳ جاري إنشاء PDF لعرض <b>{q["quotation_number"]}</b>...')
    _send_quotation_pdf(chat_id, q['quotation_id'], tenant_id, q['quotation_number'])
    return None


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
            '📦 أرسل اسم المنتج وسأجلب سعره تلقائياً من النظام.\n\n'
            'مثال: <code>كاميرا ميجا</code>\n\n'
            'عند الانتهاء أرسل: <b>انتهيت</b>'
        )

    # ── Step 2: Add items — product search then quantity ──
    if step == 'add_items':
        if any(kw in text.lower() for kw in DONE_KEYWORDS):
            if not state['items']:
                return '⚠️ لم تضف أي منتجات بعد. أرسل اسم منتج أولاً.'
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

        # ── Waiting for quantity after product was found ──
        if 'pending_product' in state:
            qty_text = re.sub(r'[^\d.]', '', text.strip())
            try:
                qty = float(qty_text)
                if qty <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                return '❓ أرسل الكمية كرقم. مثال: <code>3</code>'

            prod = state.pop('pending_product')
            line_total = round(qty * prod['unit_price'], 2)
            state['items'].append({
                'name':         prod['name'],
                'quantity':     qty,
                'unit_price':   prod['unit_price'],
                'discount_pct': 0.0,
                'line_total':   line_total,
            })
            return (
                f'✅ تمت الإضافة: <b>{prod["name"]}</b> — '
                f'{qty:g} × {prod["unit_price"]:,.0f} = {line_total:,.0f} SAR\n\n'
                'أرسل منتجاً آخر أو <b>انتهيت</b> للمتابعة.'
            )

        # ── Search product by name ──
        conn_p = get_db_for_tenant(tenant_id)
        if not conn_p:
            return '⚠️ خطأ في قاعدة البيانات.'
        rows = conn_p.execute('''
            SELECT name, selling_price, unit
            FROM products
            WHERE tenant_id = ? AND is_active = 1
              AND (name LIKE ? OR description LIKE ?)
            ORDER BY name LIMIT 8
        ''', (tenant_id, f'%{text}%', f'%{text}%')).fetchall()
        conn_p.close()

        if not rows:
            return (
                f'❓ لم أجد منتجاً باسم "<b>{text}</b>".\n\n'
                'جرب اسماً آخر أو أرسل /cancel للإلغاء.'
            )

        if len(rows) == 1:
            p = rows[0]
            state['pending_product'] = {
                'name': p['name'],
                'unit_price': p['selling_price'] or 0,
                'unit': p['unit'],
            }
            return (
                f'✅ وجدت: <b>{p["name"]}</b>\n'
                f'💰 السعر: {p["selling_price"]:,.0f} SAR / {p["unit"]}\n\n'
                'أرسل الكمية:'
            )

        # Multiple matches — let user pick
        state['pending_products'] = [dict(r) for r in rows]
        state['step'] = 'select_product'
        lines = '\n'.join(
            f'{i+1}. <b>{r["name"]}</b> — {r["selling_price"]:,.0f} SAR / {r["unit"]}'
            for i, r in enumerate(rows)
        )
        return f'🔍 وجدت عدة منتجات، اختر الرقم:\n\n{lines}'

    # ── Step 2b: Select from multiple product matches ──
    if step == 'select_product':
        products = state.get('pending_products', [])
        chosen_p = None
        num_match = re.fullmatch(r'\d+', text.strip())
        if num_match:
            idx = int(text.strip()) - 1
            if 0 <= idx < len(products):
                chosen_p = products[idx]
        if not chosen_p:
            for p in products:
                if text.strip().lower() in p['name'].lower():
                    chosen_p = p
                    break
        if not chosen_p:
            return '❓ أرسل رقم المنتج من القائمة.'

        state['pending_product'] = {
            'name': chosen_p['name'],
            'unit_price': chosen_p['selling_price'] or 0,
            'unit': chosen_p['unit'],
        }
        state.pop('pending_products', None)
        state['step'] = 'add_items'
        return (
            f'✅ <b>{chosen_p["name"]}</b> — {chosen_p["selling_price"]:,.0f} SAR / {chosen_p["unit"]}\n\n'
            'أرسل الكمية:'
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

    # ── Step 4: Notes → Create → Send PDF ──
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
        summary  = _items_summary(state['items'])
        disc_line = f'\n🏷️ خصم: {disc_amt:,.0f} SAR' if disc_amt else ''

        confirmation = (
            f'✅ <b>تم إنشاء عرض السعر بنجاح!</b>\n\n'
            f'📄 رقم العرض: <b>{q_number}</b>\n'
            f'🏢 العميل: {state["customer_name"]}\n\n'
            f'<b>المنتجات:</b>\n{summary}\n\n'
            f'💰 الإجمالي الفرعي: {subtotal:,.0f} SAR'
            f'{disc_line}\n'
            f'💵 <b>الإجمالي: {total:,.0f} SAR</b>\n\n'
            f'⏳ جاري إنشاء ملف PDF...'
        )
        # Send text confirmation first, then PDF
        send_message(chat_id, confirmation)
        _send_quotation_pdf(chat_id, qid, state['tenant_id'], q_number)
        return None   # already sent above

    # Unknown state — reset
    _QUOTATION_STATE.pop(chat_id, None)
    return '⚠️ حدث خطأ. أرسل /start للبدء من جديد.'


HELP_TEXT = (
    '📖 <b>الأوامر المتاحة:</b>\n\n'
    '📝 <b>متابعة سريعة</b>\n'
    'أرسل نصاً أو صوتاً يذكر اسم العميل وسيقترح البوت الحفظ\n\n'
    '🗂️ <b>متابعة موجهة</b>\n'
    '<code>متابعة</code> — خطوة بخطوة مع كل التفاصيل\n\n'
    '🏢 <b>عميل / شركة / مشروع جديد</b>\n'
    'أرسل أي من:\n'
    '<code>عميل جديد</code> — <code>شركة جديدة</code> — <code>مشروع جديد</code>\n'
    'وسيطلب البوت البيانات خطوة بخطوة\n\n'
    '📄 <b>عرض سعر</b>\n'
    '<code>عرض سعر</code>\n\n'
    '📑 <b>PDF عرض سعر</b>\n'
    '<code>pdf QT-2026-0001</code>\n\n'
    '📋 <b>عملائي</b>\n'
    '<code>/customers</code>\n\n'
    '🗓️ <b>متابعات اليوم</b>\n'
    '<code>/today</code>\n\n'
    '📦 <b>المنتجات والأسعار</b>\n'
    '<code>/products</code> — كل المنتجات\n'
    '<code>/products كرسي</code> — بحث باسم منتج\n\n'
    '❌ <b>إلغاء عملية جارية</b>\n'
    '<code>/cancel</code>'
)


def handle_products_command(tenant_id, search=None):
    """Return product list with description and price, optionally filtered by search term."""
    conn = get_db_for_tenant(tenant_id)
    if not conn:
        return '⚠️ خطأ في قاعدة البيانات.'

    if search:
        rows = conn.execute('''
            SELECT name, category, description, selling_price, unit
            FROM products
            WHERE tenant_id = ? AND is_active = 1
              AND (name LIKE ? OR category LIKE ? OR description LIKE ?)
            ORDER BY name LIMIT 15
        ''', (tenant_id, f'%{search}%', f'%{search}%', f'%{search}%')).fetchall()
    else:
        rows = conn.execute('''
            SELECT name, category, description, selling_price, unit
            FROM products
            WHERE tenant_id = ? AND is_active = 1
            ORDER BY category, name LIMIT 30
        ''', (tenant_id,)).fetchall()
    conn.close()

    if not rows:
        msg = f'📦 لا توجد منتجات مطابقة لـ "{search}".' if search else '📦 لا توجد منتجات مسجلة.'
        return msg

    header = f'📦 <b>نتائج "{search}"</b>\n' if search else f'📦 <b>المنتجات ({len(rows)})</b>\n'
    lines = [header]
    current_cat = None
    for r in rows:
        cat = r['category'] or 'عام'
        if not search and cat != current_cat:
            lines.append(f'\n<b>— {cat} —</b>')
            current_cat = cat
        price = f'{r["selling_price"]:,.0f} ر.س / {r["unit"]}' if r['selling_price'] else 'السعر عند الطلب'
        desc = f'\n   📝 {r["description"][:80]}' if r['description'] else ''
        lines.append(f'• <b>{r["name"]}</b> — {price}{desc}')

    if len(rows) == 30:
        lines.append('\n(تعرض أول 30 منتج — استخدم البحث للتضييق)')
    return '\n'.join(lines)


def handle_today_command(salesperson_id, tenant_id):
    """Return a summary of today's follow-up activities for this salesperson."""
    conn = get_db_for_tenant(tenant_id)
    if not conn:
        return '⚠️ خطأ في قاعدة البيانات.'
    today = datetime.now().strftime('%Y-%m-%d')
    rows = conn.execute('''
        SELECT a.summary, a.sales_stage, a.next_action,
               c.company_name
        FROM activities a
        JOIN customers c ON a.entity_id = c.customer_id
        WHERE a.tenant_id = ? AND a.created_by = ?
          AND a.entity_type = 'customer' AND a.action = 'follow_up'
          AND date(a.created_at) = ?
        ORDER BY a.id DESC LIMIT 10
    ''', (tenant_id, salesperson_id, today)).fetchall()
    conn.close()
    if not rows:
        return f'📋 لا توجد متابعات مسجلة اليوم ({today}).'
    lines = [f'🗓️ <b>متابعات اليوم — {today}</b>\n']
    for i, r in enumerate(rows, 1):
        stage = f' [{r["sales_stage"]}]' if r['sales_stage'] else ''
        summary = (r['summary'] or '')[:60]
        lines.append(f'{i}. <b>{r["company_name"]}</b>{stage}\n   {summary}')
    return '\n\n'.join(lines)


def handle_customers_command(salesperson_id, tenant_id):
    """Return the salesperson's customer list."""
    conn = get_db_for_tenant(tenant_id)
    if not conn:
        return '⚠️ خطأ في قاعدة البيانات.'
    rows = conn.execute('''
        SELECT company_name, current_stage, phone_number
        FROM customers
        WHERE tenant_id = ? AND assigned_salesperson_id = ?
          AND is_active = 1
        ORDER BY company_name LIMIT 20
    ''', (tenant_id, salesperson_id)).fetchall()
    conn.close()
    if not rows:
        return '📋 لا يوجد عملاء مسجلون باسمك.'
    lines = [f'🏢 <b>عملاؤك ({len(rows)})</b>\n']
    for i, r in enumerate(rows, 1):
        stage = f' — {r["current_stage"]}' if r['current_stage'] else ''
        lines.append(f'{i}. {r["company_name"]}{stage}')
    if len(rows) == 20:
        lines.append('\n(تعرض أول 20 عميل)')
    return '\n'.join(lines)


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
    if not get_bot_token():
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
    conn.close()

    # ── Built-in commands ──
    if text == '/help':
        send_message(chat_id, HELP_TEXT)
        return jsonify({'ok': True})

    if text in ('/today', '/اليوم'):
        send_message(chat_id, handle_today_command(salesperson_id, tenant_id))
        return jsonify({'ok': True})

    if text in ('/customers', '/عملاء'):
        send_message(chat_id, handle_customers_command(salesperson_id, tenant_id))
        return jsonify({'ok': True})

    if text.startswith('/products') or text.startswith('/منتجات'):
        parts = text.split(maxsplit=1)
        search = parts[1].strip() if len(parts) > 1 else None
        send_message(chat_id, handle_products_command(tenant_id, search))
        return jsonify({'ok': True})

    conn = get_db_for_tenant(tenant_id)
    if not conn:
        send_message(chat_id, '⚠️ Database connection error.')
        return jsonify({'ok': True})

    # ── Voice note → transcribe then treat as text ──
    if voice:
        send_message(chat_id, '🎤 جاري تفريغ الرسالة الصوتية...')
        try:
            # 1. Get the file path from Telegram
            file_id = voice['file_id']
            r = requests.get(f'{get_api_base()}/getFile', params={'file_id': file_id}, timeout=15)
            file_path = r.json()['result']['file_path']

            # 2. Download the OGG audio
            audio_url = f'https://api.telegram.org/file/bot{get_bot_token()}/{file_path}'
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

    # ── Text message → pdf | quotation | new customer | follow-up ──
    if text:
        t_lower = text.lower().strip()

        # ── PDF request ──
        if any(t_lower.startswith(kw) for kw in PDF_TRIGGERS):
            conn.close()
            reply = handle_pdf_command(chat_id, text, salesperson_id, tenant_id)
            if reply:
                send_message(chat_id, reply)
            return jsonify({'ok': True})

        actor = sp['salesperson_name'] or sp['first_name'] or ''

        # ── Active sessions take priority over intent detection ──
        if chat_id in _NEW_CUSTOMER_STATE:
            conn.close()
            reply = handle_new_customer_flow(chat_id, text, salesperson_id, tenant_id)
            if reply:
                send_message(chat_id, reply)
            return jsonify({'ok': True})

        if chat_id in _FOLLOWUP_STATE:
            conn.close()
            reply = handle_followup_flow(chat_id, text, salesperson_id, tenant_id, actor)
            if reply:
                send_message(chat_id, reply)
            return jsonify({'ok': True})

        if chat_id in _QUOTATION_STATE:
            conn.close()
            reply = handle_quotation_flow(chat_id, text, salesperson_id, tenant_id)
            if reply:
                send_message(chat_id, reply)
            return jsonify({'ok': True})

        # ── Intent detection (fresh start) ──
        if detect_quotation_intent(text):
            conn.close()
            reply = handle_quotation_flow(chat_id, text, salesperson_id, tenant_id)
            if reply:
                send_message(chat_id, reply)
            return jsonify({'ok': True})

        if detect_new_customer_intent(text):
            conn.close()
            reply = handle_new_customer_flow(chat_id, text, salesperson_id, tenant_id)
            if reply:
                send_message(chat_id, reply)
            return jsonify({'ok': True})

        if detect_followup_intent(text):
            conn.close()
            reply = handle_followup_flow(chat_id, text, salesperson_id, tenant_id, actor)
            if reply:
                send_message(chat_id, reply)
            return jsonify({'ok': True})

        # ── Free text → try NLP match → quick confirm ────────────────────────
        parsed = parse_message_text(text, salesperson_id, tenant_id)
        conn.close()

        if parsed and parsed['customer']:
            customer = parsed['customer']
            # Build quick-confirm state
            _FOLLOWUP_STATE[chat_id] = {
                'step':          'quick_confirm',
                'salesperson_id': salesperson_id,
                'tenant_id':      tenant_id,
                'customer_id':    customer['customer_id'],
                'customer_name':  customer['company_name'],
                'company_id':     customer['company_id'] if 'company_id' in customer.keys() else None,
                'stage':          parsed['stage'],
                'next_action':    parsed['action'],
                'contact_method': parsed['contact_method'],
                'summary':        text,
                'contact_date':   datetime.now().strftime('%Y-%m-%d'),
            }
            stage_line  = f'\n📊 المرحلة: {parsed["stage"]}' if parsed['stage'] else ''
            action_line = f'\n⏭️ الإجراء: {parsed["action"]}' if parsed['action'] else ''
            method_line = f'\n📞 التواصل: {parsed["contact_method"]}' if parsed['contact_method'] else ''
            send_message(chat_id,
                f'🔍 فهمت متابعة لـ <b>{customer["company_name"]}</b>'
                f'{method_line}{stage_line}{action_line}\n\n'
                f'📝 الملخص: {text[:80]}{"..." if len(text) > 80 else ""}\n\n'
                f'✅ <b>نعم</b> للحفظ — <b>لا</b> للتعديل'
            )
        else:
            # No customer match → jump straight into guided flow
            reply = handle_followup_flow(chat_id, text, salesperson_id, tenant_id, actor)
            if reply:
                send_message(chat_id, reply)

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
        "SELECT first_name, telegram_chat_id, telegram_link_token, telegram_token_expires FROM sales_team WHERE salesperson_id = ?",
        (salesperson_id,)
    )
    sp = cursor.fetchone()
    conn.close()

    is_linked = bool(sp and sp['telegram_chat_id'])
    bot_username = os.getenv('TELEGRAM_BOT_USERNAME', 'YourCRMBot')

    # Only show token if it hasn't expired yet
    link_token = None
    token_expires = None
    if sp and sp['telegram_link_token']:
        raw_expires = sp['telegram_token_expires']
        if raw_expires:
            try:
                exp_dt = datetime.fromisoformat(raw_expires)
                if exp_dt > datetime.now():
                    link_token = sp['telegram_link_token']
                    token_expires = exp_dt.strftime('%H:%M — %Y/%m/%d')
            except Exception:
                pass
        else:
            link_token = sp['telegram_link_token']  # legacy token with no expiry

    return render_template('telegram/link.html',
        is_linked=is_linked,
        link_token=link_token,
        token_expires=token_expires,
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
    from datetime import timedelta
    expires = (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute(
        "UPDATE sales_team SET telegram_link_token = ?, telegram_token_expires = ? WHERE salesperson_id = ?",
        (token, expires, salesperson_id)
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
    resp = requests.post(f'{get_api_base()}/setWebhook', json={'url': webhook_url})
    print(resp.json())


def ensure_webhook():
    """
    Called on app startup. Re-registers the webhook if it is missing or points
    to a different URL. This auto-heals the connection after a server restart.
    """
    token = get_bot_token()
    base_url = os.getenv('APP_BASE_URL', '').rstrip('/')
    if not token or not base_url:
        return

    expected_url = f'{base_url}/telegram/webhook'
    try:
        api = f'https://api.telegram.org/bot{token}'
        wh = requests.get(f'{api}/getWebhookInfo', timeout=8).json()
        current_url = wh.get('result', {}).get('url', '')
        if current_url != expected_url:
            resp = requests.post(f'{api}/setWebhook', json={'url': expected_url}, timeout=8)
            print(f'[telegram] webhook re-registered → {expected_url}: {resp.json()}')
        else:
            print(f'[telegram] webhook OK → {current_url}')
    except Exception as e:
        print(f'[telegram] ensure_webhook error: {e}')


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
