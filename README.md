# CRM Base

A multi-tenant CRM web application built with Flask, featuring a Telegram bot for logging customer follow-ups and creating new customers via text or voice messages.

---

## Features

- **Multi-tenant**: Each organization has isolated data
- **Sales pipeline**: Track customers through sales stages
- **Follow-up logging**: Log contact history, next actions, deal values
- **Bilingual UI**: Full Arabic / English support with RTL layout
- **Telegram bot**: Link your Telegram account and log follow-ups or create customers without opening the app
- **Voice notes**: Send a voice note in Arabic or English — the bot transcribes it and logs it automatically
- **Role-based access**: Admin, Manager, Salesperson roles

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11 / Flask 2.0 |
| Database | SQLite (single file, persisted on Railway volume) |
| Auth | Flask-WTF CSRF, Flask-Bcrypt, Flask-Session |
| i18n | Flask-Babel (AR / EN) |
| Bot | pyTelegramBotAPI — webhook mode |
| Voice | faster-whisper (local, CPU, `base` model) |
| Deployment | Railway — Docker, persistent `/data` volume |

---

## Project Structure

```
CrmBase/
├── app.py                  # App factory, blueprints, Babel config
├── config.py               # Dev / Production config classes
├── models.py               # SQLAlchemy models
├── security.py             # CSRF, bcrypt, Flask-Session init
├── tenant_utils.py         # get_db(), require_tenant decorator
├── env_validator.py        # Startup env var checks
├── setup_production_db.py  # First-run DB init (Railway)
├── init.sh                 # Entrypoint: DB check → gunicorn
├── Dockerfile              # python:3.11.9-slim + ffmpeg
├── railway.toml            # Railway build/deploy config
├── requirements.txt
├── routes/
│   ├── auth.py             # Login / logout
│   ├── customers.py        # Customer CRUD
│   ├── follow_up.py        # Follow-up logging
│   ├── dashboard.py        # Manager & salesperson dashboards
│   ├── users.py            # Sales team management
│   ├── settings.py         # Tenant settings
│   └── telegram.py         # Bot webhook + account linking
├── templates/
│   ├── base.html
│   ├── components/navbar.html
│   ├── auth/
│   ├── customers/
│   ├── dashboard/
│   └── telegram/
├── static/
└── translations/           # AR / EN .po files
    ├── ar/LC_MESSAGES/
    └── en/LC_MESSAGES/
```

---

## Telegram Bot

Bot: [@crmbase7_bot](https://t.me/crmbase7_bot)

### Linking your account
1. Log in to the app and go to **Telegram** in the navbar
2. Click **Generate link code**
3. Send the code to the bot: `/link ABC123`
4. Done — your Telegram is now linked to your CRM account

### Creating a new customer
Send a message (text or voice):
```
عميل جديد: شركة النور، المسؤول خالد، 0556789012
```

### Logging a follow-up
Send a text or voice note mentioning the customer name:
```
كلمت شركة النور اليوم وقدمت عرض سعر، ننتظر الرد
```

The bot matches the customer, detects the sales stage and next action, and logs the follow-up automatically.

### Voice notes
Send any voice message in Arabic or English. The bot transcribes it using faster-whisper and processes it as text.

---

## Environment Variables

| Variable | Description |
|---|---|
| `FLASK_ENV` | `production` or `development` |
| `SECRET_KEY` | Flask session secret |
| `CSRF_SECRET_KEY` | WTF CSRF secret |
| `DATABASE_NAME` | SQLite path — `/data/crm_multi.db` |
| `SQLALCHEMY_DATABASE_URI` | `sqlite:////data/crm_multi.db` |
| `SESSION_FILE_DIR` | Session storage — `/data/flask_session` |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `TELEGRAM_BOT_USERNAME` | e.g. `crmbase7_bot` |
| `APP_BASE_URL` | Public URL (no trailing slash) |
| `WHISPER_MODEL` | `base` (default), `small`, or `medium` |
| `WHISPER_CACHE` | Model cache dir — `/data/whisper_models` |
| `HF_TOKEN` | (Optional) Hugging Face token for faster model downloads |

---

## Local Development

```bash
# 1. Create virtualenv
python -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create .env
cp .env.example .env   # edit as needed

# 4. Init database
export FLASK_ENV=development
python setup_production_db.py

# 5. Run
python app.py
```

---

## Deployment (Railway)

1. Connect GitHub repo to Railway
2. Set all environment variables listed above
3. Add a Volume mounted at `/data`
4. Railway builds via `Dockerfile` and runs `init.sh`
5. `init.sh` creates the DB on first run, then starts gunicorn

### Re-register Telegram webhook after deploy
Go to `/telegram/link` as admin and click **Register Webhook**.

---

## Default Admin Account

Created automatically on first run:

| Field | Value |
|---|---|
| Username | `admin` |
| Password | `admin123` |

**Change the password immediately after first login.**
