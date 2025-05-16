from flask import Flask
from models import db, Tenant
from security import bcrypt
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv(override=True)

def init_db():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI', 'sqlite:///crm_multi.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        # Create all tables if they don't exist
        db.create_all()
        print("Database tables created successfully!")
        
        # Check if default tenant exists, if not, add it
        default_tenant = Tenant.query.filter_by(name='Default Tenant').first()
        if not default_tenant:
            default_tenant = Tenant(name='Default Tenant')
            db.session.add(default_tenant)
            db.session.commit()
            print("Default tenant added successfully")
        
        # Check if default admin user exists, if not, add it
        from models import SalesPerson
        admin = SalesPerson.query.filter_by(username='admin').first()
        if not admin:
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

