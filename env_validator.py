import os
from dotenv import load_dotenv

def validate_env_vars():
    """Validate that all required environment variables are set."""
    # Load environment variables
    load_dotenv()
    
    # Define required variables with default values for development
    required_vars = {
        'SECRET_KEY': os.getenv('SECRET_KEY', 'dev-secret-key-123'),
        'CSRF_SECRET_KEY': os.getenv('CSRF_SECRET_KEY', 'dev-csrf-secret-key-123'),
        'DATABASE_NAME': os.getenv('DATABASE_NAME', 'crm_multi.db'),
        'FLASK_ENV': os.getenv('FLASK_ENV', 'development')
    }
    
    # Check for missing variables
    missing_vars = [var for var, value in required_vars.items() if not value]
    
    if missing_vars:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing_vars)}\n"
            "Please create a .env file with these variables or set them in your environment."
        )
    
    # Validate FLASK_ENV value
    env = required_vars['FLASK_ENV']
    valid_envs = ['development', 'production', 'testing', 'staging']
    if env not in valid_envs:
        raise EnvironmentError(
            f"Invalid FLASK_ENV value: {env}. Must be one of: {', '.join(valid_envs)}"
        )
    
    # Set environment variables if they're using default values
    for var, value in required_vars.items():
        if not os.getenv(var):
            os.environ[var] = value
    
    return True 