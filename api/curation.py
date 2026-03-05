from flask import Blueprint, request, jsonify
import os
from utils.rate_limit import rate_limit
curation_bp = Blueprint('curation', __name__)

@curation_bp.route('/api/queue', methods=['GET'])
@rate_limit(100, per=3600)
def get_queue():
    """Get curation queue - pending PRs"""
    import os
    from supabase import create_client
    
    url = os.environ.get('SUPABASE_URL')
    key = os.environ.get('SUPABASE_KEY')
    
    if not url or not key:
        return jsonify({'error': 'Database not configured'}), 503
        
    supabase = create_client(url, key)
    
    try:
        from services.github import get_repository_signals
        
        # Only fetch 50 recent to keep the queue manageable
        signals, _, _ = get_repository_signals(limit=50)
        
        # 1. Filter out PRs that are already integrated or rejected. We only want 'active' ones.
        active_signals = [s for s in signals if s.get('status') == 'active']
        
        # 2. Extract their PR numbers so we can batch query Supabase
        pr_numbers = [s.get('pr_number') for s in active_signals if s.get('pr_number')]
        
        if not pr_numbers:
            return jsonify({'queue': []})
            
        # 3. Fetch votes for these active PRs
        votes_res = supabase.table('curation_votes').select('pr_number, vote, agent_name').in_('pr_number', pr_numbers).execute()
        votes_data = votes_res.data if votes_res and hasattr(votes_res, 'data') else []
        
        # 4. Attach voting metrics to each signal object
        for signal in active_signals:
            pr_num = signal.get('pr_number')
            
            # Find all votes for this specific PR
            pr_votes = [v for v in votes_data if v.get('pr_number') == pr_num]
            
            signal['approvals'] = sum(1 for v in pr_votes if v.get('vote') == 'approve')
            signal['rejections'] = sum(1 for v in pr_votes if v.get('vote') == 'reject')
            signal['voters'] = [v.get('agent_name') for v in pr_votes if v.get('agent_name')]
            
        return jsonify({'queue': active_signals})
    except Exception as e:
        print(f"Error serving curation queue: {e}", flush=True)
        return jsonify({'error': str(e)}), 500

@curation_bp.route('/api/curate', methods=['POST'])
@rate_limit(200, per=3600)
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
@rate_limit(50, per=3600)
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
