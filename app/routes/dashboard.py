from flask import Blueprint, render_template, request, session, redirect, url_for
from app.models.customer import Customer
from app.models.lead import Lead
from app.models.followup import Followup
from app.models.salesperson import Salesperson
from datetime import datetime, timedelta
from sqlalchemy import func, desc, and_

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    salesperson_id = session['user_id']
    salesperson_name = session.get('name', 'User')
    
    # Get all customers for the salesperson
    customers = Customer.query.filter(
        Customer.salesperson_id == salesperson_id
    ).all()
    
    # Get open leads - customers where the most recent follow-up's next_action is not "إغلاق البيع"
    open_leads = []
    total_value = 0
    for customer in customers:
        # Get the most recent follow-up for this customer
        latest_followup = Followup.query.filter(
            Followup.customer_id == customer.id
        ).order_by(Followup.created_at.desc()).first()
        
        # If there's no follow-up or the latest follow-up's next action is not "إغلاق البيع"
        if not latest_followup or latest_followup.next_action != 'إغلاق البيع':
            open_leads.append(customer)
            # Add the potential deal value from the most recent follow-up
            total_value += latest_followup.potential_deal_value if latest_followup and latest_followup.potential_deal_value else 0
    
    open_leads_count = len(open_leads)
    
    # Format the total value
    formatted_total_value = f"{total_value:,.0f}" if total_value is not None else "0"
    
    # Get sales pipeline
    sales_pipeline = {}
    stages = ['New', 'Qualified', 'Proposal', 'Negotiation', 'Closed']
    
    for stage in stages:
        leads = Lead.query.filter(
            Lead.salesperson_id == salesperson_id,
            Lead.status == stage
        ).all()
        sales_pipeline[stage] = leads
    
    # Get follow-ups for different time periods
    today = datetime.now().date()
    this_week_start = today
    this_week_end = today + timedelta(days=6)
    next_week_start = this_week_end + timedelta(days=1)
    next_week_end = next_week_start + timedelta(days=6)
    
    followups_today = Followup.query.join(Lead).filter(
        Lead.salesperson_id == salesperson_id,
        func.date(Followup.next_action_due_date) == today
    ).all()
    
    followups_this_week = Followup.query.join(Lead).filter(
        Lead.salesperson_id == salesperson_id,
        func.date(Followup.next_action_due_date) > today,
        func.date(Followup.next_action_due_date) <= this_week_end
    ).all()
    
    followups_next_week = Followup.query.join(Lead).filter(
        Lead.salesperson_id == salesperson_id,
        func.date(Followup.next_action_due_date) > this_week_end,
        func.date(Followup.next_action_due_date) <= next_week_end
    ).all()
    
    followups_later = Followup.query.join(Lead).filter(
        Lead.salesperson_id == salesperson_id,
        func.date(Followup.next_action_due_date) > next_week_end
    ).all()
    
    return render_template('dashboard/dashboard.html',
                         salesperson_name=salesperson_name,
                         sales_pipeline=sales_pipeline,
                         followups_today=followups_today,
                         followups_this_week=followups_this_week,
                         followups_next_week=followups_next_week,
                         followups_later=followups_later,
                         open_leads_count=open_leads_count,
                         total_open_leads_value=formatted_total_value) 