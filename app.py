from dotenv import load_dotenv
import os

# Load and validate environment variables first
load_dotenv()
env = os.getenv('FLASK_ENV', 'development')
print(f"Running in {env} environment")

from flask import Flask, render_template, request, redirect, url_for, session, g, abort, jsonify
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

# Validate environment variables
validate_env_vars()

app = Flask(__name__, 
    static_folder='static',  # Specify the static folder
    static_url_path='/static'  # Specify the URL path for static files
)

# Load configuration
app.config.from_object(config[env])

# Configure Flask-Session
app.config['SESSION_TYPE'] = 'filesystem'  # Store sessions in filesystem
app.config['SESSION_FILE_DIR'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_session')
app.config['SESSION_FILE_THRESHOLD'] = 100  # Maximum number of sessions to store

# Initialize security extensions
init_security(app)

DATABASE_NAME = os.getenv('DATABASE_NAME', 'crm_multi.db')
DEFAULT_DB_KEY = os.getenv('DEFAULT_DB_KEY', 'default')
PASSWORD_HASH_ALGORITHM = os.getenv('PASSWORD_HASH_ALGORITHM', 'sha256')

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

if __name__ == '__main__':
    host = os.getenv('FLASK_HOST', '127.0.0.1')  # Changed to localhost
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'  # Enable debug mode by default
    app.run(host=host, port=port, debug=debug)