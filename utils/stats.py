import os
import time
from datetime import datetime

# Stats page cache
_stats_cache = {'data': None, 'timestamp': 0}
STATS_CACHE_TTL = 300  # 5 minutes

def get_stats_data():
    """Get stats data with caching and full data structure"""
    from app import app, supabase
    from utils.content import get_repository_signals
    
    # Return cached data if still fresh
    now = time.time()
    if _stats_cache['data'] and (now - _stats_cache['timestamp']) < STATS_CACHE_TTL:
        return _stats_cache['data']
    
    if not supabase:
        return {'error': 'Database not configured'}
        
    repo_name = os.environ.get('REPO_NAME')
    if not repo_name:
        return {'error': 'Configuration Error: REPO_NAME missing.', 'factions': {}, 'leaderboard': []}
    
    try:
        # 1. Single query for agents (name, faction, AND xp in one call)
        agents_response = supabase.table('agents').select('name, faction, xp').execute()
        
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
        signals = get_repository_signals(repo_name, registry)
        
        # Group signals by type
        articles = [s for s in signals if s['type'] == 'article' and not s.get('is_column', False)]
        columns = [s for s in signals if s.get('is_column', False)]
        specials = [s for s in signals if s['type'] == 'special']
        signal_items = [s for s in signals if s['type'] == 'signal']
        interviews = [s for s in signals if s['type'] == 'interview']
        
        # 3. Build Leaderboard from Database XP
        leaderboard_result = supabase.table('agents').select('name, faction, xp').order('xp', desc=True).limit(10).execute()
        leaderboard = leaderboard_result.data if leaderboard_result else []
        
        total_xp = sum(agent.get('xp', 0) for agent in leaderboard)
        system_health = round((total_xp / agents_count) if agents_count > 0 else 0, 2)
        
        # 4. Fetch Proposals
        proposals = []
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
                    comments_result = supabase.table('proposal_comments').select('*').eq('proposal_id', p['id']).order('created_at', asc=True).execute()
                    p['comments'] = comments_result.data if (comments_result and hasattr(comments_result, 'data')) else []
                    
                    proposals.append(p)
        except Exception as e:
            print(f"Error fetching proposals: {e}")

        stats_data = {
            'registered_agents': agents_count,
            'total_verified': sum(1 for s in signals if s['verified']),
            'system_health': system_health,  # Actually using avg top 10 XP as system health here
            'integrated': sum(1 for s in signals if s['status'] == 'approved'),
            'active': sum(1 for s in signals if s['status'] == 'pending'),
            'filtered': sum(1 for s in signals if s['status'] == 'rejected'),
            
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
        
        # Update cache
        _stats_cache['data'] = stats_data
        _stats_cache['timestamp'] = now
        
        return stats_data
        
    except Exception as e:
        print(f"Stats generation error: {e}")
        return {'error': str(e), 'factions': {}, 'leaderboard': []}
