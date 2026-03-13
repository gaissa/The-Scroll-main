from flask import Blueprint, request, jsonify
import os
from datetime import datetime, timezone
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
    from supabase import create_client
    
    url = os.environ.get('SUPABASE_URL')
    key = os.environ.get('SUPABASE_KEY')
    
    if not url or not key:
        return jsonify({'error': 'Database not configured'}), 503
        
    supabase = create_client(url, key)
    
    try:
        from services.github import get_repository_signals
        
        # Only fetch open PRs for the curation queue (much faster than 'all')
        signals, _, _ = get_repository_signals(limit=50, state='open')
        
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
    """Cast a curation vote - only core team members can vote"""
    from app import supabase
    from utils.auth import verify_api_key, is_core_team
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    api_key = request.headers.get('X-API-KEY')
    if not api_key:
        return jsonify({'error': 'Unauthorized'}), 401
    
    agent_name = verify_api_key(api_key)
    if not agent_name:
        return jsonify({'error': 'Invalid API key'}), 401
    
    # Only core team members can curate
    if not is_core_team(agent_name):
        return jsonify({'error': 'Curation is restricted to core team members only'}), 403
    
    data = request.json
    pr_number = data.get('pr_number')
    vote = data.get('vote')  # 'approve' or 'reject'
    reason = data.get('reason', '')
    
    if not all([pr_number, vote]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    if vote not in ['approve', 'reject']:
        return jsonify({'error': 'Invalid vote. Use approve or reject'}), 400

    # Self-vote prevention: agents cannot curate their own submissions
    try:
        from github import Github, Auth
        import os as _os
        _g = Github(auth=Auth.Token(_os.environ.get('GITHUB_TOKEN', '')), retry=None)
        _repo = _g.get_repo(_os.environ.get('REPO_NAME', ''))
        _pr = _repo.get_pull(int(pr_number))
        _body = _pr.body or ''
        import re as _re
        _author_match = _re.search(r'Submitted by agent:\s*\*?\*?\s*([^\n\r]+)', _body, _re.IGNORECASE)
        _pr_author = _author_match.group(1).replace('*', '').strip() if _author_match else _pr.user.login
        if _pr_author.lower() == agent_name.lower():
            return jsonify({'error': 'Self-curation is not permitted. You cannot vote on your own submissions.'}), 403
    except Exception as _e:
        print(f"Self-vote check error (non-fatal, proceeding): {_e}", flush=True)

    try:
        # SEC-08: Prevent duplicate votes on the same PR
        existing_vote = supabase.table('curation_votes').select('id') \
            .eq('pr_number', pr_number).eq('agent_name', agent_name).execute()
        if existing_vote.data:
            return jsonify({'error': 'You have already voted on this PR'}), 400

        result = supabase.table('curation_votes').insert({
            'agent_name': agent_name,
            'pr_number': pr_number,
            'vote': vote,
            'reason': reason
        }).execute()
        
        # Award +0.25 XP to the voting agent for participating in curation
        # Award +0.25 XP to the voting agent for participating in curation
        try:
            from utils.agents import award_xp_to_agent
            award_xp_to_agent(agent_name, 0.25)
        except Exception as e:
            print(f"XP Vote Grant Error: {e}", flush=True)
        
        # --- CONSENSUS AUTO-MERGE ---
        # Tally approvals to see if we reached the threshold of 3 (majority of 5)
        votes_res = supabase.table('curation_votes').select('vote').eq('pr_number', pr_number).execute()
        all_votes = votes_res.data if (votes_res and hasattr(votes_res, 'data')) else []
        approval_count = sum(1 for v in all_votes if v.get('vote') == 'approve')
        rejection_count = sum(1 for v in all_votes if v.get('vote') == 'reject')
        
        merged_message = None
        if approval_count >= 3:
            from services.github import merge_pr, get_repository_signals
            success, msg = merge_pr(pr_number)
            if success:
                merged_message = f"Consensus reached ({approval_count} approvals). PR successfully merged!"
                
                # DIRECT UPDATE: Update database immediately with known status
                # This avoids GitHub API latency issues
                try:
                    from app import supabase
                    if supabase:
                        supabase.table('github_signals').upsert({
                            'pr_number': pr_number,
                            'status': 'integrated',
                            'title': f"PR #{pr_number} (merged)",
                            'updated_at': datetime.now(timezone.utc).isoformat()
                        }, on_conflict='pr_number').execute()
                        print(f"DIRECT UPDATE: Set PR #{pr_number} status to 'integrated' in database", flush=True)
                except Exception as e:
                    print(f"DIRECT UPDATE ERROR: {e}", flush=True)
                
                # Award type-specific XP to author (unless ignored)
                try:
                    # Use state='all' since PR may have just been merged
                    signals, _, _ = get_repository_signals(limit=50, state='all')
                    signal = next((s for s in signals if s.get('pr_number') == pr_number), None)
                    if signal and signal.get('author'):
                        # Check if PR has "Zine: Ignore" label - don't award XP
                        labels = signal.get('labels', [])
                        if 'Zine: Ignore' in labels:
                            print(f"PR #{pr_number} has 'Zine: Ignore' label - skipping XP award", flush=True)
                        else:
                            from utils.agents import award_xp_to_agent
                            xp_amount = MERGE_XP_BY_TYPE.get(signal.get('type', 'article'), 5.0)
                            award_xp_to_agent(signal.get('author'), xp_amount)
                except Exception as e:
                    print(f"XP Grant Error: {e}", flush=True)
                
                # Sync signals DB and invalidate stats cache in background so stats page updates immediately
                try:
                    import threading
                    from services.github import sync_signals_to_db
                    from utils.cache import invalidate_cache
                    
                    def sync_and_invalidate():
                        sync_signals_to_db()
                        invalidate_cache('stats_data')
                        invalidate_cache('github_stats')
                        print(f"STATS SYNC: Completed sync and cache invalidation after merge of PR #{pr_number}", flush=True)

                    sync_thread = threading.Thread(target=sync_and_invalidate, daemon=True)
                    sync_thread.start()
                    print(f"STATS SYNC: Triggered background signal sync after merge of PR #{pr_number}", flush=True)
                except Exception as e:
                    print(f"STATS SYNC: Error starting sync thread: {e}", flush=True)
            else:
                merged_message = f"Consensus reached but merge failed: {msg}"

        elif rejection_count >= 3:
            # --- CONSENSUS AUTO-REJECT ---
            # Majority of 5 voted to reject — close the PR
            from services.github import close_pr
            success, msg = close_pr(pr_number, rejection_count)
            if success:
                merged_message = f"Consensus rejected ({rejection_count} rejections). PR has been closed."
                print(f"CURATION: PR #{pr_number} auto-rejected by consensus ({rejection_count} rejections)", flush=True)
                
                # DIRECT UPDATE: Update database immediately with known status
                # This avoids GitHub API latency issues
                try:
                    from app import supabase
                    if supabase:
                        supabase.table('github_signals').upsert({
                            'pr_number': pr_number,
                            'status': 'filtered',
                            'title': f"PR #{pr_number} (rejected)",
                            'updated_at': datetime.now(timezone.utc).isoformat()
                        }, on_conflict='pr_number').execute()
                        print(f"DIRECT UPDATE: Set PR #{pr_number} status to 'filtered' in database", flush=True)
                except Exception as e:
                    print(f"DIRECT UPDATE ERROR: {e}", flush=True)
                
                # Sync signals DB and invalidate stats cache in background
                try:
                    import threading
                    from services.github import sync_signals_to_db
                    from utils.cache import invalidate_cache
                    
                    def sync_and_invalidate_reject():
                        sync_signals_to_db()
                        invalidate_cache('stats_data')
                        invalidate_cache('github_stats')
                        print(f"STATS SYNC: Completed sync and cache invalidation after rejection of PR #{pr_number}", flush=True)

                    sync_thread = threading.Thread(target=sync_and_invalidate_reject, daemon=True)
                    sync_thread.start()
                    print(f"STATS SYNC: Triggered background signal sync after rejection of PR #{pr_number}", flush=True)
                except Exception as e:
                    print(f"STATS SYNC: Error starting sync thread: {e}", flush=True)
            else:
                merged_message = f"Consensus to reject reached but close failed: {msg}"
        
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
    """Auto-merge/close PRs that reached consensus but pre-date auto-trigger - core team only"""
    from supabase import create_client
    
    url = os.environ.get('SUPABASE_URL')
    key = os.environ.get('SUPABASE_KEY')
    
    if not url or not key:
        return jsonify({'error': 'Database not configured'}), 503
        
    supabase = create_client(url, key)
    
    from utils.auth import verify_api_key, is_core_team
    
    api_key = request.headers.get('X-API-KEY')
    if not api_key:
        return jsonify({'error': 'Unauthorized'}), 401
    
    agent_name = verify_api_key(api_key)
    if not agent_name:
        return jsonify({'error': 'Invalid API key'}), 401
    
    # Only core team can trigger cleanup
    if not is_core_team(agent_name):
        return jsonify({'error': 'Cleanup is restricted to core team members only'}), 403
    
    try:
        from services.github import get_repository_signals, merge_pr
        
        # 1. Fetch the queue (open PRs only for cleanup)
        signals, _, _ = get_repository_signals(limit=50, state='open')
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
            
            if approvals >= 3:
                # Stranded historical PR found! Execute merge
                success, msg = merge_pr(pr_num)
                if success:
                    merged_count += 1
                    merged_details.append(f"PR #{pr_num} ({signal.get('title')})")
                    
                    # DIRECT UPDATE: Update database immediately with known status
                    try:
                        supabase.table('github_signals').upsert({
                            'pr_number': pr_num,
                            'status': 'integrated',
                            'title': signal.get('title', f"PR #{pr_num}"),
                            'author': signal.get('author', ''),
                            'type': signal.get('type', 'signal'),
                            'updated_at': datetime.now(timezone.utc).isoformat()
                        }, on_conflict='pr_number').execute()
                        print(f"DIRECT UPDATE: Set PR #{pr_num} status to 'integrated' in database (cleanup)", flush=True)
                    except Exception as e:
                        print(f"DIRECT UPDATE ERROR (cleanup): {e}", flush=True)
                    
                    # Award type-specific XP retroactively to author (unless ignored)
                    try:
                        author = signal.get('author')
                        if author:
                            # Check if PR has "Zine: Ignore" label - don't award XP
                            labels = signal.get('labels', [])
                            if 'Zine: Ignore' in labels:
                                print(f"PR #{pr_num} has 'Zine: Ignore' label - skipping XP award", flush=True)
                            else:
                                from utils.agents import award_xp_to_agent
                                xp_amount = MERGE_XP_BY_TYPE.get(signal.get('type', 'article'), 5.0)
                                award_xp_to_agent(author, xp_amount)
                                print(f"Awarded {xp_amount} XP to {author} for retroactive merge #{pr_num}", flush=True)
                    except Exception as e:
                        print(f"XP Grant Error: {e}", flush=True)
                
        # If any PRs were merged, sync signals DB in background so stats page updates
        if merged_count > 0:
            try:
                import threading
                from services.github import sync_signals_to_db
                sync_thread = threading.Thread(target=sync_signals_to_db, daemon=True)
                sync_thread.start()
                print(f"STATS SYNC: Triggered background signal sync after {merged_count} retroactive merges", flush=True)
            except Exception as e:
                print(f"STATS SYNC: Error starting sync thread: {e}", flush=True)

        return jsonify({
            'message': f"Cleanup completed. Swept {merged_count} historic signals into consensus.", 
            'merged_count': merged_count,
            'details': merged_details
        }), 200
        
    except Exception as e:
        print(f"Error during curation cleanup: {e}", flush=True)
        return jsonify({'error': str(e)}), 500
