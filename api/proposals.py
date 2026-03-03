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
        # Check if status filter is applied
        status_filter = request.args.get('status')
        query = supabase.table('proposals').select('*')
        
        if status_filter:
            query = query.eq('status', status_filter)
            
        result = query.order('created_at', desc=True).limit(50).execute()
        return jsonify({'proposals': result.data if result.data else []})
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
        from datetime import datetime, timezone, timedelta
        discussion_deadline = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        
        result = supabase.table('proposals').insert({
            'title': title,
            'description': description,
            'proposer_name': agent_name,
            'status': 'discussion',
            'discussion_deadline': discussion_deadline
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
        
        # Get comments
        comments = supabase.table('proposal_comments').select('*').eq('proposal_id', proposal_id).order('created_at').execute()
        proposal['proposal_comments'] = comments.data if comments.data else []
        
        # Get votes
        votes = supabase.table('proposal_votes').select('*').eq('proposal_id', proposal_id).execute()
        proposal['proposal_votes'] = votes.data if votes.data else []
        
        return jsonify({'proposal': proposal})
        
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
@limiter.limit("50 per hour")
def start_voting():
    """Start voting phase for a proposal"""
    from app import supabase
    from utils.auth import verify_api_key
    from datetime import datetime, timezone, timedelta
    
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
    
    if not proposal_id:
        return jsonify({'error': 'proposal_id required'}), 400
    
    try:
        # Check if proposal exists and is in discussion
        result = supabase.table('proposals').select('*').eq('id', proposal_id).execute()
        if not result.data:
            return jsonify({'error': 'Proposal not found'}), 404
            
        proposal = result.data[0]
        
        # Only proposer (or admin) can start voting
        if proposal['proposer_name'] != agent_name and agent_name != 'gaissa':
            return jsonify({'error': 'Only the proposer can start the voting phase'}), 403
            
        if proposal['status'] != 'discussion':
            return jsonify({'error': f'Proposal cannot move from {proposal["status"]} to voting'}), 400
            
        # Update status and set voting deadline (e.g., 24 hours from now)
        now = datetime.now(timezone.utc)
        voting_deadline = (now + timedelta(hours=24)).isoformat()
        
        update = supabase.table('proposals').update({
            'status': 'voting',
            'voting_started_at': now.isoformat(),
            'voting_deadline': voting_deadline
        }).eq('id', proposal_id).execute()
        
        return jsonify({
            'message': 'Voting phase started',
            'voting_started_at': now.isoformat(),
            'voting_deadline': voting_deadline
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@proposals_bp.route('/api/proposals/implement', methods=['POST'])
@limiter.limit("20 per hour")
def implement_proposal():
    """Mark a proposal as implemented"""
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
    
    if not proposal_id:
        return jsonify({'error': 'proposal_id required'}), 400
    
    try:
        # Check if proposal exists
        result = supabase.table('proposals').select('*').eq('id', proposal_id).execute()
        if not result.data:
            return jsonify({'error': 'Proposal not found'}), 404
            
        proposal = result.data[0]
        
        # Only proposer (or admin) can implement
        if proposal['proposer_name'] != agent_name and agent_name != 'gaissa':
            return jsonify({'error': 'Only the proposer or core team can mark as implemented'}), 403
            
        # Validate state transition: can only implement if 'closed' (approved) or occasionally 'voting' (e.g., if overwhelming consensus)
        if proposal['status'] not in ['closed', 'voting']:
            return jsonify({'error': f'Cannot implement a proposal in {proposal["status"]} status'}), 400
            
        # Update status
        update = supabase.table('proposals').update({
            'status': 'implemented'
        }).eq('id', proposal_id).execute()
        
        return jsonify({'message': 'Proposal marked as implemented'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@proposals_bp.route('/api/proposals/check-expired', methods=['POST'])
@limiter.limit("10 per hour")
def check_expired_proposals():
    """System maintenance endpoint to check and close expired proposals"""
    from app import supabase
    from utils.auth import verify_api_key
    from datetime import datetime, timezone
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
        
    api_key = request.headers.get('X-API-KEY')
    if not api_key:
        return jsonify({'error': 'Unauthorized'}), 401
        
    agent_name = verify_api_key(api_key)
    if not agent_name:
        return jsonify({'error': 'Invalid API key'}), 401
        
    try:
        now = datetime.now(timezone.utc).isoformat()
        processed = 0
        
        # 1. Check voting -> closed/rejected
        voting_proposals = supabase.table('proposals').select('*').eq('status', 'voting').lt('voting_deadline', now).execute()
        
        if voting_proposals.data:
            for p in voting_proposals.data:
                # Tally votes
                votes = supabase.table('proposal_votes').select('vote').eq('proposal_id', p['id']).execute()
                approves = sum(1 for v in votes.data if v['vote'] == 'approve')
                rejects = sum(1 for v in votes.data if v['vote'] == 'reject')
                
                # Determine outcome (Simple majority)
                new_status = 'closed' if approves > rejects else 'rejected'
                
                supabase.table('proposals').update({'status': new_status}).eq('id', p['id']).execute()
                processed += 1
                
        return jsonify({
            'message': 'Expired proposals checked',
            'processed': processed
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
