from flask_bcrypt import Bcrypt
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_session import Session

# Initialize security extensions
bcrypt = Bcrypt()
csrf = CSRFProtect()
session = Session()

def init_security(app):
    """Initialize all security extensions with the Flask app"""
    bcrypt.init_app(app)
    csrf.init_app(app)
    session.init_app(app)
    
    # Ensure CSRF token is available in all templates
    @app.after_request
    def add_csrf_token(response):
        if not response.headers.get('X-CSRFToken'):
            response.headers['X-CSRFToken'] = generate_csrf()
        return response 