from flask import Blueprint, jsonify, session
from tenant_utils import get_db, get_current_tenant_id, require_tenant
from activity_logger import get_activities

activities_bp = Blueprint('activities', __name__, url_prefix='/activities')

_VALID_ENTITY_TYPES = {'customer', 'company', 'project'}


@activities_bp.route('/<entity_type>/<int:entity_id>')
@require_tenant
def timeline(entity_type, entity_id):
    """AJAX endpoint — returns the activity feed for one entity as JSON."""
    if 'salesperson_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 403
    if entity_type not in _VALID_ENTITY_TYPES:
        return jsonify({'error': 'Invalid entity type'}), 400

    tenant_id = get_current_tenant_id()
    conn = get_db()
    try:
        return jsonify(get_activities(conn, tenant_id, entity_type, entity_id))
    finally:
        conn.close()
