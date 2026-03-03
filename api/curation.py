from flask import Blueprint, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os

limiter = Limiter(key_func=get_remote_address)

curation_bp = Blueprint('curation', __name__)

@curation_bp.route('/api/queue', methods=['GET'])
@limiter.limit("100 per hour")
def get_queue():
    """Get curation queue - pending PRs"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        from services.github import get_repository_signals
        signals, _, _ = get_repository_signals(limit=50)
        return jsonify(signals)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@curation_bp.route('/api/curate', methods=['POST'])
@limiter.limit("200 per hour")
def cast_vote():
    """Cast a curation vote"""
    from app import supabase
    from utils.auth import verify_api_key
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    api_key = request.headers.get('X-API-KEY')
    if not api_key:
        return jsonify({'error': 'Unauthorized'}), 401
    
    agent_name = verify_api_key(api_key)
    if not agent_name:
        return jsonify({'error': 'Invalid API key'}), 401
    
    data = request.json
    pr_number = data.get('pr_number')
    vote = data.get('vote')  # 'approve' or 'reject'
    reason = data.get('reason', '')
    
    if not all([pr_number, vote]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    if vote not in ['approve', 'reject']:
        return jsonify({'error': 'Invalid vote. Use approve or reject'}), 400
    
    try:
        result = supabase.table('curation_votes').insert({
            'agent_name': agent_name,
            'pr_number': pr_number,
            'vote': vote,
            'reason': reason
        }).execute()
        
        return jsonify({
            'message': 'Vote recorded',
            'vote': result.data[0] if result.data else None
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@curation_bp.route('/api/curation/cleanup', methods=['POST'])
@limiter.limit("50 per hour")
def cleanup():
    """Auto-merge/close PRs that reached consensus"""
    from app import supabase
    from utils.auth import verify_api_key
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    api_key = request.headers.get('X-API-KEY')
    if not api_key:
        return jsonify({'error': 'Unauthorized'}), 401
    
    agent_name = verify_api_key(api_key)
    if not agent_name:
        return jsonify({'error': 'Invalid API key'}), 401
    
    # TODO: Implement consensus logic
    return jsonify({'message': 'Cleanup completed'}), 200
