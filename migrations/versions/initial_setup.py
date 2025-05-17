"""initial setup

Revision ID: initial_setup
Revises: 
Create Date: 2024-05-17 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime
from werkzeug.security import generate_password_hash

# revision identifiers, used by Alembic.
revision = 'initial_setup'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Create tenants table
    op.create_table('tenants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('db_key', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('db_key')
    )

    # Create sales_team table
    op.create_table('sales_team',
        sa.Column('salesperson_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('first_name', sa.String(length=50), nullable=False),
        sa.Column('last_name', sa.String(length=50), nullable=False),
        sa.Column('password', sa.String(length=255), nullable=False),
        sa.Column('salesperson_name', sa.String(length=50), nullable=False),
        sa.Column('work_email', sa.String(length=100), nullable=False),
        sa.Column('phone_number', sa.String(length=20), nullable=True),
        sa.Column('role', sa.String(length=20), nullable=True),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('salesperson_id'),
        sa.UniqueConstraint('username')
    )

    # Create customers table
    op.create_table('customers',
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('company_name', sa.String(length=100), nullable=False),
        sa.Column('contact_person', sa.String(length=100), nullable=False),
        sa.Column('phone_number', sa.String(length=20), nullable=False),
        sa.Column('email_address', sa.String(length=100), nullable=True),
        sa.Column('company_address', sa.String(length=200), nullable=True),
        sa.Column('lead_source', sa.String(length=50), nullable=True),
        sa.Column('initial_interest', sa.String(length=200), nullable=True),
        sa.Column('company_industry', sa.String(length=100), nullable=True),
        sa.Column('contact_person_position', sa.String(length=100), nullable=True),
        sa.Column('assigned_salesperson_id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('date_added', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['assigned_salesperson_id'], ['sales_team.salesperson_id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('customer_id')
    )

    # Create sales_followup table
    op.create_table('sales_followup',
        sa.Column('followup_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('assigned_salesperson_id', sa.Integer(), nullable=False),
        sa.Column('last_contact_date', sa.DateTime(), nullable=False),
        sa.Column('last_contact_method', sa.String(length=50), nullable=True),
        sa.Column('summary_last_contact', sa.Text(), nullable=True),
        sa.Column('next_action', sa.String(length=50), nullable=True),
        sa.Column('next_action_due_date', sa.DateTime(), nullable=True),
        sa.Column('current_sales_stage', sa.String(length=50), nullable=True),
        sa.Column('potential_deal_value', sa.Float(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['assigned_salesperson_id'], ['sales_team.salesperson_id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['sales_team.salesperson_id'], ),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.customer_id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('followup_id')
    )

    # Add default tenant
    op.execute("""
        INSERT INTO tenants (name, db_key, created_at)
        VALUES ('Default Tenant', 'default', CURRENT_TIMESTAMP)
    """)

    # Add default admin user
    op.execute("""
        INSERT INTO sales_team (
            username, first_name, last_name, password, salesperson_name,
            work_email, role, tenant_id, created_at
        )
        VALUES (
            'admin', 'Admin', 'User', :password, 'admin',
            'admin@example.com', 'admin', 1, CURRENT_TIMESTAMP
        )
    """, {'password': generate_password_hash('admin123')})

def downgrade():
    op.drop_table('sales_followup')
    op.drop_table('customers')
    op.drop_table('sales_team')
    op.drop_table('tenants') 