from dotenv import load_dotenv
import os

# Load environment variables first
load_dotenv()

# Get environment and validate it
env = os.getenv('FLASK_ENV', 'development')
if env not in ['development', 'production', 'testing', 'staging']:
    raise ValueError(f"Invalid FLASK_ENV value: {env}. Must be one of: development, production, testing, staging")

print(f"Running in {env} environment")

from flask import Flask, render_template, request, redirect, url_for, session, g, abort, jsonify
from flask_migrate import Migrate
import sqlite3
from datetime import datetime, date, timedelta, timezone
from tenant_utils import get_db, get_current_tenant_id, add_tenant_filter, require_tenant
from config import config
from routes.customers import customers_bp
from routes.settings import settings_bp
from routes.follow_up import follow_up_bp
from routes.users import users_bp
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from security import init_security, bcrypt
from env_validator import validate_env_vars
from werkzeug.middleware.proxy_fix import ProxyFix
from models import db, Tenant, SalesPerson
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_babel import Babel

# Validate environment variables
validate_env_vars()

app = Flask(__name__, 
    static_folder='static',  # Specify the static folder
    static_url_path='/static'  # Specify the URL path for static files
)

# Load configuration
app_config = config.get(env)
app.config.from_object(app_config)

# Configure Babel
app.config['BABEL_DEFAULT_LOCALE'] = 'en'
app.config['BABEL_SUPPORTED_LOCALES'] = ['en', 'ar']
babel = Babel(app)

@babel.localeselector
def get_locale():
    return session.get('lang', 'en')

# Configure SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI', 'sqlite:////data/crm_multi.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = True  # Enable SQL query logging

# Initialize SQLAlchemy and Flask-Migrate
db = SQLAlchemy(app)
migrate = Migrate(app, db, directory='migrations')
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'

# Configure Flask-Session
app.config['SESSION_TYPE'] = 'filesystem'  # Store sessions in filesystem
app.config['SESSION_FILE_DIR'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_session')
app.config['SESSION_FILE_THRESHOLD'] = 100  # Maximum number of sessions to store
app.config['SESSION_COOKIE_SECURE'] = app_config.SESSION_COOKIE_SECURE
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = None  # (optional, disables CSRF token expiration)

# Initialize security extensions
init_security(app)

# Register blueprints
app.register_blueprint(auth_bp)  # Register auth blueprint first
app.register_blueprint(customers_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(follow_up_bp)
app.register_blueprint(users_bp)
app.register_blueprint(dashboard_bp)  # Register dashboard blueprint

@app.teardown_appcontext
def teardown_db(error):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.route('/')
def index():
    if 'salesperson_id' in session:
        if session.get('role') in ['admin', 'manager']:
            return redirect(url_for('dashboard.manager_dashboard'))
        return redirect(url_for('dashboard.dashboard'))
    return redirect(url_for('auth.login'))

@app.route('/login')
def login_redirect():
    return redirect(url_for('auth.login'))

@app.route('/change_lang/<lang>')
def change_lang(lang):
    if lang in ['en', 'ar']:
        session['lang'] = lang
    return redirect(request.referrer or '/')

# Add ProxyFix middleware
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

if __name__ == '__main__':
    host = os.getenv('FLASK_HOST', '127.0.0.1')  # Changed to localhost
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'  # Enable debug mode by default
    app.run(host=host, port=port, debug=debug)