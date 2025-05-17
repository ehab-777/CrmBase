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

# Validate environment variables
validate_env_vars()

app = Flask(__name__, 
    static_folder='static',  # Specify the static folder
    static_url_path='/static'  # Specify the URL path for static files
)

# Load configuration
app_config = config.get(os.getenv('FLASK_ENV', 'default'))
app.config.from_object(app_config)

# Configure SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI', 'sqlite:///crm_multi.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = True  # Enable SQL query logging

# Initialize SQLAlchemy and Flask-Migrate
db.init_app(app)
migrate = Migrate(app, db)

def init_db():
    """Initialize the database with tables and default data."""
    try:
        # Get the database path from environment variable
        db_path = os.getenv('DATABASE_URL', 'sqlite:///crm_multi.db')
        
        # Extract the actual file path from SQLAlchemy URL
        if db_path.startswith('sqlite:///'):
            db_file = db_path.replace('sqlite:///', '')
        else:
            db_file = db_path
            
        # Check if database file exists
        if os.path.exists(db_file):
            app.logger.info(f"Database file found at {db_file}. Skipping initialization.")
            return
            
        app.logger.info(f"Database file not found at {db_file}. Creating new database...")
        
        # Create tables
        with app.app_context():
            db.create_all()
            app.logger.info("Database tables created successfully!")
            
            # Add default tenant if none exists
            default_tenant = Tenant.query.filter_by(name='Default Tenant').first()
            if not default_tenant:
                default_tenant = Tenant(
                    name='Default Tenant',
                    db_key='default'
                )
                db.session.add(default_tenant)
                db.session.commit()
                app.logger.info("Default tenant added successfully")
            
            # Add default admin user if none exists
            admin_user = SalesPerson.query.filter_by(username='admin').first()
            if not admin_user:
                admin_user = SalesPerson(
                    username='admin',
                    first_name='Admin',
                    last_name='User',
                    password=bcrypt.generate_password_hash('admin123').decode('utf-8'),
                    salesperson_name='admin',
                    work_email='admin@example.com',
                    role='admin',
                    tenant_id=default_tenant.id
                )
                db.session.add(admin_user)
                db.session.commit()
                app.logger.info("Default admin user added successfully")
                
    except Exception as e:
        app.logger.error(f"Error initializing database: {str(e)}")
        raise

# Configure Flask-Session
app.config['SESSION_TYPE'] = 'filesystem'  # Store sessions in filesystem
app.config['SESSION_FILE_DIR'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_session')
app.config['SESSION_FILE_THRESHOLD'] = 100  # Maximum number of sessions to store
app.config['SESSION_COOKIE_SECURE'] = False  # Allow cookies over HTTP in development
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
        if session.get('role') == 'admin':
            return redirect(url_for('dashboard.admin_dashboard'))
        elif session.get('role') == 'manager':
            return redirect(url_for('dashboard.manager_dashboard'))
        return redirect(url_for('dashboard.dashboard'))
    return redirect(url_for('auth.login'))

@app.route('/login')
def login_redirect():
    return redirect(url_for('auth.login'))

# Add ProxyFix middleware
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

if __name__ == '__main__':
    host = os.getenv('FLASK_HOST', '127.0.0.1')  # Changed to localhost
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'  # Enable debug mode by default
    app.run(host=host, port=port, debug=debug)