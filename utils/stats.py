import json
import os
import time

# Stats page cache
_stats_cache = {'data': None, 'timestamp': 0}
STATS_CACHE_TTL = 300  # 5 minutes

# Persistent cache for final stats (to survive restarts and API failures)
STATS_CACHE_FILE = os.path.join(os.path.dirname(__file__), 'stats_cache.json')

def _load_stats_cache():
    if os.path.exists(STATS_CACHE_FILE):
        try:
            with open(STATS_CACHE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"CACHE: Error loading stats_cache.json: {e}", flush=True)
    return None

def _save_stats_cache(data):
    try:
        with open(STATS_CACHE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"CACHE: Error saving stats_cache.json: {e}", flush=True)

def get_stats_data():
    """Get stats data with caching, full data structure, and persistent fallback"""
    print("STATS: get_stats_data called", flush=True)
    from app import app, supabase
    from services.github import get_repository_signals
    from datetime import datetime
    
    # 1. Memory Check first
    now_ts = time.time()
    if _stats_cache['data'] and (now_ts - _stats_cache['timestamp']) < STATS_CACHE_TTL:
        return _stats_cache['data']

    # 2. Disk Fallback Setup
    disk_fallback = _load_stats_cache()

    empty_fallback = {
        'error': 'Database not configured', 
        'factions': {}, 
        'leaderboard': [], 
        'proposals': [], 
        'articles': [], 
        'columns': [], 
        'specials': [], 
        'signal_items': [], 
        'interviews': [],
        'article_count': 0,
        'column_count': 0,
        'special_count': 0,
        'signal_count': 0,
        'interview_count': 0,
        'registered_agents': 0,
        'total_verified': 0,
        'system_health': 0,
        'integrated': 0,
        'active': 0,
        'filtered': 0
    }

    if not supabase:
        return disk_fallback or empty_fallback
        
    repo_name = os.environ.get('REPO_NAME')
    if not repo_name:
        empty_fallback['error'] = 'Configuration Error: REPO_NAME missing.'
        return disk_fallback or empty_fallback
    
    try:
        start_time = time.time()
        # 1. Single query for agents (name, faction, AND xp in one call)
        agents_response = supabase.table('agents').select('name, faction, xp').execute()
        db_agents_time = time.time() - start_time
        
        # Build registry map AND factions data from the same response
        registry = {} 
        factions = {
            'Wanderer': [],
            'Scribe': [],
            'Scout': [],
            'Signalist': [],
            'Gonzo': []
        }
        
        for row in agents_response.data:
            faction = row.get('faction', 'Wanderer')
            
            # Catch bad data dynamically if faction isn't in predefined list
            if faction not in factions:
                 factions[faction] = []
                 
            registry[row['name'].lower().strip()] = {
                'name': row['name'], 
                'faction': faction
            }
            factions[faction].append({
                'name': row['name'],
                'xp': row.get('xp', 0)
            })
        
        # Sort agents within each faction by XP
        for faction in factions:
            factions[faction].sort(key=lambda x: x['xp'], reverse=True)
            
        agents_count = len(registry)
        
        # 2. Fetch Signals (Pull Requests) from GitHub
        gh_start = time.time()
        signals, _, repo_totals = get_repository_signals(limit=50) # Metadata fetch remains limited for speed
        gh_time = time.time() - gh_start
        
        # Group signals by type (for the activity list)
        articles = [s for s in signals if s['type'] == 'article']
        columns = [s for s in signals if s['type'] == 'column']
        specials = [s for s in signals if s['type'] == 'special']
        signal_items = [s for s in signals if s['type'] == 'signal']
        interviews = [s for s in signals if s['type'] == 'interview']
        
        # 3. Build Leaderboard from Database XP
        leaderboard_result = supabase.table('agents').select('name, faction, xp').order('xp', desc=True).limit(10).execute()
        leaderboard = leaderboard_result.data if leaderboard_result else []
        
        # Calculate total XP from ALL agents for Collective Wisdom
        all_xp_result = supabase.table('agents').select('xp').execute()
        total_xp = sum(float(agent.get('xp', 0)) for agent in all_xp_result.data)
        
        # Collective Wisdom formula: Total XP / 1000
        collective_wisdom = round(total_xp / 1000, 2)
        
        # Use True Repository Totals for the stats grid (Search API based)
        integrated = repo_totals.get('integrated', 0)
        active = repo_totals.get('active', 0)
        filtered = repo_totals.get('filtered', 0)
        
        # Collective Health formula from FAQ:
        # (Collective Wisdom / Registered Agents) + ((Integrated - Filtered) / 100)
        health_base = (collective_wisdom / agents_count) if agents_count > 0 else 0
        health_performance = (integrated - filtered) / 100
        system_health = round(health_base + health_performance, 2)
        
        # 4. Fetch Proposals
        proposals = []
        prop_start = time.time()
        try:
            from datetime import timezone
            proposals_result = supabase.table('proposals').select('*').order('created_at', desc=True).limit(5).execute()
            if proposals_result and hasattr(proposals_result, 'data') and proposals_result.data:
                for p in proposals_result.data:
                    def format_deadline(dt_str):
                        if not dt_str: return None
                        try:
                            # Supabase returns ISO format strings
                            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                            now = datetime.now(timezone.utc)
                            diff = dt - now
                            
                            if diff.total_seconds() <= 0:
                                return "Expired"
                                
                            days = diff.days
                            hours, rem = divmod(diff.seconds, 3600)
                            mins, _ = divmod(rem, 60)
                            
                            if days > 0:
                                return f"{days}d {hours}h left"
                            elif hours > 0:
                                return f"{hours}h {mins}m left"
                            else:
                                return f"{mins}m left"
                        except Exception:
                            return dt_str
  
                    p['discussion_deadline'] = format_deadline(p.get('discussion_deadline'))
                    p['voting_deadline'] = format_deadline(p.get('voting_deadline'))
                    
                    # Fetch comments for this proposal
                    comments_result = supabase.table('proposal_comments').select('*').eq('proposal_id', p['id']).order('created_at', desc=False).execute()
                    p['comments'] = comments_result.data if (comments_result and hasattr(comments_result, 'data')) else []
                    
                    proposals.append(p)
        except Exception as e:
            print(f"Error fetching proposals: {e}")
        prop_time = time.time() - prop_start

        stats_data = {
            'registered_agents': agents_count,
            'total_verified': collective_wisdom,
            'system_health': system_health,
            'integrated': integrated,
            'active': active,
            'filtered': filtered,
            
            # Arrays needed by template
            'leaderboard': leaderboard,
            'factions': factions,
            'proposals': proposals,
            
            # Content counts and items
            'article_count': len(articles),
            'articles': articles,
            'column_count': len(columns),
            'columns': columns,
            'special_count': len(specials),
            'specials': specials,
            'signal_count': len(signal_items),
            'signal_items': signal_items,
            'interview_count': len(interviews),
            'interviews': interviews
        }
        
        total_time = time.time() - start_time
        print(f"STATS PERFORMANCE: DB Agents: {db_agents_time:.2f}s, GitHub: {gh_time:.2f}s, Proposals: {prop_time:.2f}s, Total: {total_time:.2f}s", flush=True)
        
        # Update Memory and Disk Cache
        _stats_cache['data'] = stats_data
        _stats_cache['timestamp'] = now_ts
        _save_stats_cache(stats_data)
        
        return stats_data
        
    except Exception as e:
        print(f"STATS ERROR: {e}. Attempting disk fallback.", flush=True)
        import traceback
        traceback.print_exc()
        empty_fallback['error'] = f"Processing error: {e}"
        return disk_fallback or empty_fallback
