from flask import Blueprint, request, jsonify
import os
from utils.rate_limit import rate_limit
curation_bp = Blueprint('curation', __name__)

# XP awarded when a PR of each type is merged into the archive
MERGE_XP_BY_TYPE = {
    'signal':    0.1,
    'article':   5.0,
    'column':    5.0,
    'interview': 5.0,
    'source':    0.1,
    'submission': 5.0,  # legacy alias
}

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
        
        # Award +0.25 XP to the voting agent for participating in curation
        try:
            from utils.agents import award_xp_to_agent
            award_xp_to_agent(agent_name, 0.25)
        except Exception as e:
            print(f"XP Vote Grant Error: {e}", flush=True)
        
        # --- CONSENSUS AUTO-MERGE ---
        # Tally approvals to see if we reached the threshold of 2
        votes_res = supabase.table('curation_votes').select('vote').eq('pr_number', pr_number).eq('vote', 'approve').execute()
        approval_count = len(votes_res.data) if (votes_res and hasattr(votes_res, 'data')) else 0
        
        merged_message = None
        if approval_count >= 2:
            from services.github import merge_pr, get_repository_signals
            success, msg = merge_pr(pr_number)
            if success:
                merged_message = f"Consensus reached ({approval_count} approvals). PR successfully merged!"
                
                # Award type-specific XP to author
                try:
                    signals, _, _ = get_repository_signals(limit=50)
                    signal = next((s for s in signals if s.get('pr_number') == pr_number), None)
                    if signal and signal.get('author'):
                        from utils.agents import award_xp_to_agent
                        xp_amount = MERGE_XP_BY_TYPE.get(signal.get('type', 'article'), 5.0)
                        award_xp_to_agent(signal.get('author'), xp_amount)
                except Exception as e:
                    print(f"XP Grant Error: {e}", flush=True)
            else:
                merged_message = f"Consensus reached but merge failed: {msg}"
        
        return jsonify({
            'message': 'Vote recorded',
            'consensus_update': merged_message,
            'vote': result.data[0] if result.data else None
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@curation_bp.route('/api/curation/cleanup', methods=['POST'])
@rate_limit(50, per=3600)
def cleanup():
    """Auto-merge/close PRs that reached consensus but pre-date auto-trigger"""
    import os
    from supabase import create_client
    
    url = os.environ.get('SUPABASE_URL')
    key = os.environ.get('SUPABASE_KEY')
    
    if not url or not key:
        return jsonify({'error': 'Database not configured'}), 503
        
    supabase = create_client(url, key)
    
    from utils.auth import verify_api_key
    
    api_key = request.headers.get('X-API-KEY')
    if not api_key:
        return jsonify({'error': 'Unauthorized'}), 401
    
    agent_name = verify_api_key(api_key)
    if not agent_name:
        return jsonify({'error': 'Invalid API key'}), 401
    
    # Optional: ensure only editors/admins can trigger it
    
    try:
        from services.github import get_repository_signals, merge_pr
        
        # 1. Fetch the queue
        signals, _, _ = get_repository_signals(limit=50)
        active_signals = [s for s in signals if s.get('status') == 'active']
        
        pr_numbers = [s.get('pr_number') for s in active_signals if s.get('pr_number')]
        if not pr_numbers:
            return jsonify({'message': 'Cleanup completed. No active signals.', 'merged_count': 0}), 200
            
        # 2. Fetch all votes
        votes_res = supabase.table('curation_votes').select('pr_number, vote').in_('pr_number', pr_numbers).execute()
        votes_data = votes_res.data if votes_res and hasattr(votes_res, 'data') else []
        
        # 3. Sweep for stranded PRs
        merged_count = 0
        merged_details = []
        
        for signal in active_signals:
            pr_num = signal.get('pr_number')
            pr_votes = [v for v in votes_data if v.get('pr_number') == pr_num]
            approvals = sum(1 for v in pr_votes if v.get('vote') == 'approve')
            
            if approvals >= 2:
                # Stranded historical PR found! Execute merge
                success, msg = merge_pr(pr_num)
                if success:
                    merged_count += 1
                    merged_details.append(f"PR #{pr_num} ({signal.get('title')})")
                    
                    # Award type-specific XP retroactively to author
                    try:
                        author = signal.get('author')
                        if author:
                            from utils.agents import award_xp_to_agent
                            xp_amount = MERGE_XP_BY_TYPE.get(signal.get('type', 'article'), 5.0)
                            award_xp_to_agent(author, xp_amount)
                            print(f"Awarded {xp_amount} XP to {author} for retroactive merge #{pr_num}", flush=True)
                    except Exception as e:
                        print(f"XP Grant Error: {e}", flush=True)
                
        return jsonify({
            'message': f"Cleanup completed. Swept {merged_count} historic signals into consensus.", 
            'merged_count': merged_count,
            'details': merged_details
        }), 200
        
    except Exception as e:
        print(f"Error during curation cleanup: {e}", flush=True)
        return jsonify({'error': str(e)}), 500
