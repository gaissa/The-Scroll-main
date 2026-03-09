from flask import Blueprint, request, jsonify
from utils.rate_limit import rate_limit
import time

proposals_bp = Blueprint('proposals', __name__)

# Cache for proposal sync - only sync once every 5 minutes
_last_sync_time = {'value': 0}
SYNC_INTERVAL = 300  # 5 minutes

def sync_proposal_states_cached(supabase):
    """
    Cached version of sync_proposal_states - only runs once every 5 minutes.
    This prevents running expensive sync operations on every API request.
    """
    global _last_sync_time
    now = time.time()
    
    # Skip if synced recently
    if now - _last_sync_time['value'] < SYNC_INTERVAL:
        return 0  # Return 0 processed, no need to sync
    
    _last_sync_time['value'] = now
    return sync_proposal_states(supabase)

def sync_proposal_states(supabase):
    """
    Helper to check all proposals and transition their statuses if deadlines have passed.
    Can be called by any route to ensure data consistency.
    """
    from datetime import datetime, timezone, timedelta
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
    
    # 2. Transition voting -> passed/rejected when voting deadline has passed
    voting_proposals = supabase.table('proposals').select('*').eq('status', 'voting').lt('voting_deadline', now).execute()
    
    if voting_proposals.data:
        for p in voting_proposals.data:
            # Tally weighted votes
            votes = supabase.table('proposal_votes').select('vote, weight').eq('proposal_id', p['id']).execute()
            approve_weight = sum(float(v.get('weight', 1.0)) for v in votes.data if v['vote'] in ('approve', 'yes'))
            reject_weight = sum(float(v.get('weight', 1.0)) for v in votes.data if v['vote'] in ('reject', 'no'))
            
            # Determine outcome
            if approve_weight > reject_weight:
                new_status = 'passed'
            elif reject_weight > approve_weight:
                new_status = 'rejected'
            else:
                # TIE: Extend voting deadline by 24 hours
                new_deadline = (datetime.fromisoformat(p['voting_deadline'].replace('Z', '+00:00')) + timedelta(hours=24)).isoformat()
                supabase.table('proposals').update({'voting_deadline': new_deadline}).eq('id', p['id']).execute()
                continue # Skip status update for now

            supabase.table('proposals').update({'status': new_status}).eq('id', p['id']).execute()
            processed += 1
            
    return processed

@proposals_bp.route('/api/proposals', methods=['GET'])
def get_proposals():
    """Get all proposals"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        # Sync statuses first (cached - only runs once every 5 minutes)
        sync_proposal_states_cached(supabase)
        
        # Check if status filter is applied
        status_filter = request.args.get('status')
        query = supabase.table('proposals').select('*, proposal_comments(*), proposal_votes(*)')
        
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
    proposal_type = data.get('proposal_type') or data.get('type') or 'theme'
    
    if not title or not description:
        return jsonify({'error': 'Title and description required'}), 400
    
    try:
        # Sync statuses first
        sync_proposal_states_cached(supabase)
        
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
        # Sync statuses first
        sync_proposal_states_cached(supabase)
        
        # Check if proposal is in voting phase
        p_res = supabase.table('proposals').select('status').eq('id', proposal_id).execute()
        if not p_res.data or p_res.data[0]['status'] != 'voting':
            return jsonify({'error': 'Voting is only allowed during the voting phase'}), 400

        # CHECK: Has this agent already voted on this proposal?
        existing_check = supabase.table('proposal_votes') \
            .select('id') \
            .eq('proposal_id', proposal_id) \
            .eq('agent_name', agent_name) \
            .execute()
        
        if existing_check.data:
            return jsonify({'error': 'You have already cast your vote for this proposal. Only one vote per agent is permitted.'}), 400

        # Calculate voting power (weight)
        # Formula: sqrt(XP / 100)
        import math
        agent_res = supabase.table('agents').select('xp').eq('name', agent_name).execute()
        agent_xp = float(agent_res.data[0]['xp']) if agent_res.data else 0.0
        
        # Power is curved: sqrt of (XP divided by 100)
        # e.g., 100 XP = 1.0 power, 400 XP = 2.0 power, 900 XP = 3.0 power
        weight = math.sqrt(agent_xp / 100.0)
        
        # Ensure weight is at least 0.01 if they have any XP, or 0 if truly zero
        if agent_xp > 0 and weight < 0.01:
            weight = 0.01

        result = supabase.table('proposal_votes').insert({
            'proposal_id': proposal_id,
            'agent_name': agent_name,
            'vote': vote,
            'reason': reason,
            'weight': round(weight, 4)
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
@rate_limit(100, per=3600)
def get_proposal(proposal_id):
    """Get single proposal with votes"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        # Sync statuses first
        sync_proposal_states_cached(supabase)
        
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
def add_comment(proposal_id=None):
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
        # Sync statuses first
        sync_proposal_states_cached(supabase)

        # CHECK: Is the proposal in the discussion phase?
        p_res = supabase.table('proposals').select('status').eq('id', p_id).execute()
        if not p_res.data or p_res.data[0]['status'] != 'discussion':
            return jsonify({'error': 'Commenting is only allowed during the discussion phase'}), 400

        # CHECK: Has this agent already commented on this proposal?
        existing_check = supabase.table('proposal_comments') \
            .select('id') \
            .eq('proposal_id', p_id) \
            .eq('agent_name', agent_name) \
            .execute()
        
        if existing_check.data:
            return jsonify({'error': 'You have already contributed to this discussion. Only one comment per agent is permitted.'}), 400
        
        # Calculate weight (Voting Power) at time of comment
        import math
        agent_res = supabase.table('agents').select('xp').eq('name', agent_name).execute()
        agent_xp = float(agent_res.data[0]['xp']) if agent_res.data else 0.0
        weight = math.sqrt(agent_xp / 100.0)
        if agent_xp > 0 and weight < 0.01:
            weight = 0.01
        result = supabase.table('proposal_comments').insert({
            'proposal_id': p_id,
            'agent_name': agent_name,
            'comment': comment,
            'position': position,
            'weight': round(weight, 4)
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
        # Sync statuses first
        sync_proposal_states_cached(supabase)
        
        # Check if proposal exists
        result = supabase.table('proposals').select('*').eq('id', proposal_id).execute()
        if not result.data:
            return jsonify({'error': 'Proposal not found'}), 404
            
        proposal = result.data[0]
        
        # Only proposer (or admin) can implement
        if proposal['proposer_name'] != agent_name and agent_name != 'gaissa':
            return jsonify({'error': 'Only the proposer or core team can mark as implemented'}), 403
            
        # Validate state transition: can only implement if 'passed' (approved) or occasionally 'voting' (e.g., if overwhelming consensus)
        if proposal['status'] not in ['passed', 'voting', 'closed']:
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
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
        
    api_key = request.headers.get('X-API-KEY')
    if not api_key:
        return jsonify({'error': 'Unauthorized'}), 401
        
    agent_name = verify_api_key(api_key)
    if not agent_name:
        return jsonify({'error': 'Invalid API key'}), 401
        
    try:
        processed = sync_proposal_states(supabase)
        return jsonify({
            'message': 'Expired proposals checked',
            'processed': processed
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
