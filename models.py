from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin

db = SQLAlchemy()

class Tenant(db.Model):
    __tablename__ = 'tenants'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    db_key = db.Column(db.String(50), unique=True, nullable=False, default='default')
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    def __repr__(self):
        return f'<Tenant {self.name}>'

class CompanyProfile(db.Model):
    __tablename__ = 'company_profiles'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, unique=True)
    company_name = db.Column(db.String(100))
    company_description = db.Column(db.Text)
    industry = db.Column(db.String(100))
    websites = db.Column(db.Text)
    business_units = db.Column(db.Text)
    core_services = db.Column(db.Text)
    products = db.Column(db.Text)
    target_audience = db.Column(db.Text)
    target_industries = db.Column(db.Text)
    geographic_market = db.Column(db.Text)
    competitors = db.Column(db.Text)
    usps = db.Column(db.Text)
    vision = db.Column(db.Text)
    mission = db.Column(db.Text)
    business_goals = db.Column(db.Text)
    strategic_priorities = db.Column(db.Text)
    current_priorities = db.Column(db.Text)
    things_not_to_focus_on = db.Column(db.Text)
    decision_rules = db.Column(db.Text)
    ai_instructions = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())
    
    def __repr__(self):
        return f'<CompanyProfile {self.company_name}>'

class SalesPerson(db.Model):
    __tablename__ = 'sales_team'
    
    salesperson_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(255), nullable=False)
    salesperson_name = db.Column(db.String(50), nullable=False)
    work_email = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20))
    role = db.Column(db.String(20), default='salesperson')
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    telegram_chat_id = db.Column(db.String(50), nullable=True, unique=True)
    telegram_link_token = db.Column(db.String(10), nullable=True)
    
    def __repr__(self):
        return f'<SalesPerson {self.username}>'

class Customer(db.Model):
    __tablename__ = 'customers'
    
    customer_id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(100), nullable=False)
    contact_person = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    email_address = db.Column(db.String(100))
    company_address = db.Column(db.String(200))
    lead_source = db.Column(db.String(50))
    initial_interest = db.Column(db.String(200))
    company_industry = db.Column(db.String(100))
    contact_person_position = db.Column(db.String(100))
    subcategory_id = db.Column(db.Integer, db.ForeignKey('business_subcategories.id'), nullable=True)
    current_stage = db.Column(db.String(50))
    assigned_salesperson_id = db.Column(db.Integer, db.ForeignKey('sales_team.salesperson_id'), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    date_added = db.Column(db.DateTime, default=db.func.now())
    
    def __repr__(self):
        return f'<Customer {self.company_name}>'

class SalesFollowup(db.Model):
    __tablename__ = 'sales_followup'
    
    followup_id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.customer_id'), nullable=False)
    assigned_salesperson_id = db.Column(db.Integer, db.ForeignKey('sales_team.salesperson_id'), nullable=False)
    last_contact_date = db.Column(db.DateTime, nullable=False)
    last_contact_method = db.Column(db.String(50))
    summary_last_contact = db.Column(db.Text)
    next_action = db.Column(db.String(50))
    next_action_due_date = db.Column(db.DateTime)
    current_sales_stage = db.Column(db.String(50))
    potential_deal_value = db.Column(db.Float)
    notes = db.Column(db.Text)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    created_by = db.Column(db.Integer, db.ForeignKey('sales_team.salesperson_id'), nullable=False)
    
    def __repr__(self):
        return f'<SalesFollowup {self.followup_id}>'

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user')
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    def __repr__(self):
        return f'<User {self.username}>'

class Role(db.Model):
    __tablename__ = 'roles'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    def __repr__(self):
        return f'<Role {self.name}>'

class Permission(db.Model):
    __tablename__ = 'permissions'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    def __repr__(self):
        return f'<Permission {self.name}>'

class BusinessTrack(db.Model):
    __tablename__ = 'business_tracks'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255))
    is_active = db.Column(db.Integer, default=1)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    def __repr__(self):
        return f'<BusinessTrack {self.name}>'

class BusinessSubcategory(db.Model):
    __tablename__ = 'business_subcategories'
    
    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey('business_tracks.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Integer, default=1)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    def __repr__(self):
        return f'<BusinessSubcategory {self.name}>'

class Task(db.Model):
    __tablename__ = 'tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(50), default='pending')
    due_date = db.Column(db.DateTime)
    subcategory_id = db.Column(db.Integer, db.ForeignKey('business_subcategories.id'), nullable=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey('sales_team.salesperson_id'), nullable=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    def __repr__(self):
        return f'<Task {self.title}>' 