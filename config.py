import os
from pathlib import Path

# Set base directory for file paths
BASE_DIR = Path(__file__).resolve().parent

# Database paths
DEV_DB_PATH = 'sqlite:///crm_multi.db'
PROD_DB_PATH = 'sqlite:////data/crm_multi.db'
TEST_DB_PATH = f'sqlite:///{BASE_DIR}/test.db'

class Config:
    """Base configuration."""
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-123')
    CSRF_SECRET_KEY = os.getenv('CSRF_SECRET_KEY', 'dev-csrf-secret-key-123')
    
    # Session
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 1800  # 30 minutes
    FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
    DEBUG = False
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI', DEV_DB_PATH)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Security Headers
    HSTS_ENABLED = os.getenv('HSTS_ENABLED', 'True').lower() == 'true'
    HSTS_MAX_AGE = int(os.getenv('HSTS_MAX_AGE', '31536000'))
    CSP_ENABLED = os.getenv('CSP_ENABLED', 'True').lower() == 'true'

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    TESTING = False
    SQLALCHEMY_DATABASE_URI = DEV_DB_PATH

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    SQLALCHEMY_DATABASE_URI = PROD_DB_PATH
    
    def __init__(self):
        self.SECRET_KEY = os.getenv('SECRET_KEY')
        self.CSRF_SECRET_KEY = os.getenv('CSRF_SECRET_KEY')
        if not self.SECRET_KEY or not self.CSRF_SECRET_KEY:
            raise ValueError("SECRET_KEY and CSRF_SECRET_KEY must be set in the production environment.")

class StagingConfig(Config):
    """Staging configuration."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = False
    SQLALCHEMY_DATABASE_URI = PROD_DB_PATH  # Use production database path

# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'staging': StagingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
} 