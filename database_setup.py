from flask import Flask
from models import db, Tenant
from security import bcrypt
from dotenv import load_dotenv
import os
from sqlalchemy import inspect

# Load environment variables
load_dotenv(override=True)

def init_db():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI', 'sqlite:///crm_multi.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        # Get existing tables
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        # Create only missing tables
        db.create_all()
        print("Database tables checked and created if missing!")
        
        # Only add default tenant if no tenants exist
        if 'tenants' in existing_tables and not Tenant.query.first():
            default_tenant = Tenant(name='Default Tenant')
            db.session.add(default_tenant)
            db.session.commit()
            print("Default tenant added successfully")
            
            # Add default admin user only if no users exist
            from models import SalesPerson
            if not SalesPerson.query.first():
                admin = SalesPerson(
                    username='admin',
                    first_name='Admin',
                    last_name='User',
                    password=bcrypt.generate_password_hash('admin123').decode('utf-8'),
                    salesperson_name='admin',
                    work_email='admin@example.com',
                    role='admin',
                    tenant_id=default_tenant.id
                )
                db.session.add(admin)
                db.session.commit()
                print("Default admin user added successfully")

if __name__ == '__main__':
    init_db()

