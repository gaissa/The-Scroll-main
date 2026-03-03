from flask import Blueprint, jsonify

issues_bp = Blueprint('issues', __name__)

@issues_bp.route('/api/issues', methods=['GET'])
def get_issues():
    """Get all published issues"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        result = supabase.table('issues').select('*').order('issue_number', desc=True).execute()
        return jsonify(result.data if result.data else [])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
