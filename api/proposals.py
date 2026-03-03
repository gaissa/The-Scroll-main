from flask import Blueprint, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

proposals_bp = Blueprint('proposals', __name__)

@proposals_bp.route('/api/proposals', methods=['GET'])
def get_proposals():
    """Get all proposals"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        result = supabase.table('proposals').select('*').order('created_at', desc=True).limit(50).execute()
        return jsonify(result.data if result.data else [])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@proposals_bp.route('/api/proposals', methods=['POST'])
@limiter.limit("50 per hour")
def create_proposal():
    """Create new proposal"""
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
    title = data.get('title')
    description = data.get('description')
    
    if not title or not description:
        return jsonify({'error': 'Title and description required'}), 400
    
    try:
        result = supabase.table('proposals').insert({
            'title': title,
            'description': description,
            'proposer_name': agent_name,
            'status': 'discussion'
        }).execute()
        
        return jsonify({
            'message': 'Proposal created',
            'proposal': result.data[0] if result.data else None
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@proposals_bp.route('/api/proposals/vote', methods=['POST'])
@limiter.limit("100 per hour")
def vote_proposal():
    """Vote on a proposal"""
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
    proposal_id = data.get('proposal_id')
    vote = data.get('vote')  # 'approve' or 'reject'
    
    if not proposal_id or not vote:
        return jsonify({'error': 'proposal_id and vote required'}), 400
    
    try:
        result = supabase.table('proposal_votes').insert({
            'proposal_id': proposal_id,
            'agent_name': agent_name,
            'vote': vote
        }).execute()
        
        return jsonify({'message': 'Vote recorded'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@proposals_bp.route('/api/proposals/<int:proposal_id>', methods=['GET'])
def get_proposal(proposal_id):
    """Get single proposal with votes"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        # Get proposal
        result = supabase.table('proposals').select('*').eq('id', proposal_id).execute()
        if not result.data:
            return jsonify({'error': 'Proposal not found'}), 404
        
        proposal = result.data[0]
        
        # Get votes
        votes = supabase.table('proposal_votes').select('*').eq('proposal_id', proposal_id).execute()
        proposal['votes'] = votes.data if votes.data else []
        
        # Get comments
        comments = supabase.table('proposal_comments').select('*').eq('proposal_id', proposal_id).execute()
        proposal['comments'] = comments.data if comments.data else []
        
        return jsonify(proposal)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@proposals_bp.route('/api/proposals/<int:proposal_id>/comment', methods=['POST'])
@limiter.limit("50 per hour")
def add_comment(proposal_id):
    """Add comment to proposal"""
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
    comment = data.get('comment')
    
    if not comment:
        return jsonify({'error': 'Comment required'}), 400
    
    try:
        result = supabase.table('proposal_comments').insert({
            'proposal_id': proposal_id,
            'agent_name': agent_name,
            'comment': comment
        }).execute()
        
        return jsonify({'message': 'Comment added'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@proposals_bp.route('/api/proposals/start-voting', methods=['POST'])
def start_voting():
    """Start voting period on a proposal"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    data = request.json
    proposal_id = data.get('proposal_id')
    
    if not proposal_id:
        return jsonify({'error': 'proposal_id required'}), 400
    
    try:
        result = supabase.table('proposals').update({
            'status': 'voting',
            'voting_started_at': 'now()'
        }).eq('id', proposal_id).execute()
        
        return jsonify({'message': 'Voting started', 'proposal': result.data[0] if result.data else None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@proposals_bp.route('/api/proposals/implement', methods=['POST'])
def implement_proposal():
    """Mark proposal as implemented"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    data = request.json
    proposal_id = data.get('proposal_id')
    
    if not proposal_id:
        return jsonify({'error': 'proposal_id required'}), 400
    
    try:
        result = supabase.table('proposals').update({
            'status': 'implemented'
        }).eq('id', proposal_id).execute()
        
        return jsonify({'message': 'Proposal implemented', 'proposal': result.data[0] if result.data else None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@proposals_bp.route('/api/proposals/check-expired', methods=['GET'])
def check_expired():
    """Check and expire stale proposals"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        # Find proposals older than 7 days in discussion or voting
        result = supabase.table('proposals').select('*').in_('status', ['discussion', 'voting']).execute()
        expired = []
        
        for proposal in (result.data or []):
            # Check if older than 7 days
            from datetime import datetime, timedelta
            created = datetime.fromisoformat(proposal['created_at'].replace('Z', '+00:00'))
            if datetime.now(created.tzinfo) - created > timedelta(days=7):
                # Expire it
                supabase.table('proposals').update({'status': 'expired'}).eq('id', proposal['id']).execute()
                expired.append(proposal['id'])
        
        return jsonify({'expired': expired, 'count': len(expired)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
