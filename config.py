import os
from pathlib import Path

# Set base directory for file paths
BASE_DIR = Path(__file__).resolve().parent

class Config:
    """Base configuration."""
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-123')
    CSRF_SECRET_KEY = os.getenv('CSRF_SECRET_KEY', 'dev-csrf-secret-key-123')
    
    # Session
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = int(os.getenv('PERMANENT_SESSION_LIFETIME', '3600'))
    
    # Database
    DATABASE_NAME = os.getenv('DATABASE_NAME', str(BASE_DIR / 'crm_multi.db'))
    DEFAULT_DB_KEY = os.getenv('DEFAULT_DB_KEY', 'default')
    
    # Security Headers
    HSTS_ENABLED = os.getenv('HSTS_ENABLED', 'True').lower() == 'true'
    HSTS_MAX_AGE = int(os.getenv('HSTS_MAX_AGE', '31536000'))
    CSP_ENABLED = os.getenv('CSP_ENABLED', 'True').lower() == 'true'

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SESSION_COOKIE_SECURE = False  # Allow cookies over HTTP in development
    TESTING = False
    
    # Development-specific settings
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-123')
    CSRF_SECRET_KEY = os.getenv('CSRF_SECRET_KEY', 'dev-csrf-secret-key-123')

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    
    def __init__(self):
        self.SECRET_KEY = os.getenv('SECRET_KEY')
        self.CSRF_SECRET_KEY = os.getenv('CSRF_SECRET_KEY')
        if not self.SECRET_KEY or not self.CSRF_SECRET_KEY:
            raise ValueError("SECRET_KEY and CSRF_SECRET_KEY must be set in the production environment.")

class TestingConfig(Config):
    """Testing configuration."""
    DEBUG = True
    TESTING = True
    DATABASE_NAME = str(BASE_DIR / 'test.db')
    
    # Testing-specific settings
    SECRET_KEY = 'test-secret-key'
    CSRF_SECRET_KEY = 'test-csrf-secret-key'

class StagingConfig(Config):
    """Staging configuration."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    
    # Use the same environment variable handling as the base Config class
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-123')
    CSRF_SECRET_KEY = os.getenv('CSRF_SECRET_KEY', 'dev-csrf-secret-key-123')

# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'staging': StagingConfig,
    'default': DevelopmentConfig
} 