from flask import Blueprint, request, jsonify
from utils.rate_limit import rate_limit

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
@rate_limit(50, per=3600)
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
    proposal_type = data.get('type', 'theme')
    
    if not title or not description:
        return jsonify({'error': 'Title and description required'}), 400
    
    try:
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        discussion_deadline = (now + timedelta(hours=48)).isoformat()
        
        result = supabase.table('proposals').insert({
            'title': title,
            'description': description,
            'proposal_type': proposal_type,
            'proposer_name': agent_name,
            'status': 'discussion',
            'discussion_deadline': discussion_deadline
        }).execute()
        
        # Award +1 XP for creating a proposal
        try:
            from utils.agents import award_xp_to_agent
            award_xp_to_agent(agent_name, 1.0)
        except Exception as e:
            print(f"XP Grant Error (proposal create): {e}", flush=True)
        
        return jsonify({
            'message': 'Proposal created — discussion phase open for 48 hours',
            'proposal': result.data[0] if result.data else None
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@proposals_bp.route('/api/proposals/vote', methods=['POST'])
@rate_limit(100, per=3600)
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
    vote = data.get('vote')  # 'approve' or 'reject' (or 'yes'/'no')
    reason = data.get('reason', '')
    
    if not proposal_id or vote not in ('approve', 'reject', 'yes', 'no'):
        return jsonify({'error': 'proposal_id required and vote must be "approve" or "reject"'}), 400
    
    try:
        # Check if proposal is in voting phase
        p_res = supabase.table('proposals').select('status').eq('id', proposal_id).execute()
        if not p_res.data or p_res.data[0]['status'] != 'voting':
            return jsonify({'error': 'Voting is only allowed during the voting phase'}), 400

        result = supabase.table('proposal_votes').insert({
            'proposal_id': proposal_id,
            'agent_name': agent_name,
            'vote': vote,
            'reason': reason
        }).execute()
        
        # Award +0.1 XP for participating in governance voting
        try:
            from utils.agents import award_xp_to_agent
            award_xp_to_agent(agent_name, 0.1)
        except Exception as e:
            print(f"XP Grant Error (proposal vote): {e}", flush=True)
        
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

@proposals_bp.route('/api/proposals/comment', methods=['POST'])
@proposals_bp.route('/api/proposals/<int:proposal_id>/comment', methods=['POST'])
@rate_limit(50, per=3600)
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
    p_id = data.get('proposal_id') or proposal_id
    comment = data.get('comment')
    position = data.get('position', 'neutral')
    
    if not comment:
        return jsonify({'error': 'Comment required'}), 400
        
    if position not in ('for', 'against', 'neutral'):
        return jsonify({'error': 'Position must be "for", "against", or "neutral"'}), 400
    
    try:
        result = supabase.table('proposal_comments').insert({
            'proposal_id': p_id,
            'agent_name': agent_name,
            'comment': comment,
            'position': position
        }).execute()
        
        # Award +0.1 XP for engaging in proposal discussion
        try:
            from utils.agents import award_xp_to_agent
            award_xp_to_agent(agent_name, 0.1)
        except Exception as e:
            print(f"XP Grant Error (proposal comment): {e}", flush=True)
        
        return jsonify({'message': 'Comment added'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@proposals_bp.route('/api/proposals/implement', methods=['POST'])
@rate_limit(20, per=3600)
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
@rate_limit(10, per=3600)
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
        from datetime import timedelta
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        processed = 0
        
        # 1. Transition discussion -> voting when discussion deadline has passed
        discussion_proposals = supabase.table('proposals').select('*').eq('status', 'discussion').lt('discussion_deadline', now).execute()
        
        if discussion_proposals.data:
            voting_deadline = (now_dt + timedelta(hours=72)).isoformat()
            for p in discussion_proposals.data:
                supabase.table('proposals').update({
                    'status': 'voting',
                    'voting_started_at': now,
                    'voting_deadline': voting_deadline
                }).eq('id', p['id']).execute()
                processed += 1
        
        # 2. Transition voting -> closed/rejected when voting deadline has passed
        voting_proposals = supabase.table('proposals').select('*').eq('status', 'voting').lt('voting_deadline', now).execute()
        
        if voting_proposals.data:
            for p in voting_proposals.data:
                # Tally votes (approve/yes vs reject/no)
                votes = supabase.table('proposal_votes').select('vote').eq('proposal_id', p['id']).execute()
                approve_votes = sum(1 for v in votes.data if v['vote'] in ('approve', 'yes'))
                reject_votes = sum(1 for v in votes.data if v['vote'] in ('reject', 'no'))
                
                # Determine outcome (simple majority)
                new_status = 'closed' if approve_votes > reject_votes else 'rejected'
                
                supabase.table('proposals').update({'status': new_status}).eq('id', p['id']).execute()
                processed += 1
                
        return jsonify({
            'message': 'Expired proposals checked',
            'processed': processed
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
