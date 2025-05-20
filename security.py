from flask_bcrypt import Bcrypt
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_session import Session
from flask_login import LoginManager
from models import db, User

# Initialize security extensions
bcrypt = Bcrypt()
csrf = CSRFProtect()
session = Session()
login_manager = LoginManager()

def init_security(app):
    """Initialize all security extensions with the Flask app"""
    bcrypt.init_app(app)
    csrf.init_app(app)
    session.init_app(app)
    login_manager.init_app(app)
    
    # Ensure CSRF token is available in all templates
    @app.after_request
    def add_csrf_token(response):
        if not response.headers.get('X-CSRFToken'):
            response.headers['X-CSRFToken'] = generate_csrf()
        return response 

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id)) 