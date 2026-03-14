"""
Stats data retrieval with Vercel-compatible caching.

Uses Supabase as cache backing store since Vercel's filesystem is ephemeral.
"""
import os
import time
from datetime import datetime, timezone, timedelta
from utils.cache import get_or_compute, get_stale_or_compute

# Cache TTL in seconds
STATS_CACHE_TTL = 60  # 1 minute - fast stats should update frequently
GITHUB_CACHE_TTL = 300  # 5 minutes for GitHub data


def get_fast_stats():
    """Get fast stats from database only - no GitHub API calls.
    Returns immediately with cached data if available.
    """
    from app import supabase
    
    if not supabase:
        return {'error': 'Database not configured'}
    
    start_time = time.time()
    
    # 1. Single query for agents
    agents_response = supabase.table('agents').select('name, faction, xp').execute()
    
    # Build registry and factions
    registry = {}
    factions = {}
    
    for row in (agents_response.data or []):
        faction = row.get('faction', 'Wanderer')
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
    
    for faction in factions:
        factions[faction].sort(key=lambda x: x['xp'], reverse=True)
    
    agents_count = len(registry)
    all_agents_sorted = sorted(
        agents_response.data or [],
        key=lambda x: float(x.get('xp', 0)),
        reverse=True
    )
    leaderboard = [
        {'name': a['name'], 'faction': a.get('faction', 'Wanderer'), 'xp': a.get('xp', 0)}
        for a in all_agents_sorted[:10]
    ]
    total_xp = sum(float(row.get('xp', 0)) for row in (agents_response.data or []))
    collective_wisdom = round(total_xp / 1000, 2)
    
    # 2. Fetch proposals with BATCH comments
    proposals = []
    try:
        proposals_result = supabase.table('proposals').select('*').order('created_at', desc=True).limit(5).execute()
        if proposals_result and proposals_result.data:
            proposal_ids = [p['id'] for p in proposals_result.data]
            all_comments = supabase.table('proposal_comments').select('*').in_('proposal_id', proposal_ids).order('created_at', desc=False).execute()
            comments_map = {}
            for c in (all_comments.data or []):
                comments_map.setdefault(c['proposal_id'], []).append(c)
            for p in proposals_result.data:
                p['discussion_deadline'] = _format_deadline(p.get('discussion_deadline'))
                p['voting_deadline'] = _format_deadline(p.get('voting_deadline'))
                p['comments'] = comments_map.get(p['id'], [])
                proposals.append(p)
    except Exception as e:
        print(f"Error fetching proposals: {e}")
    
    db_time = time.time() - start_time
    print(f"FAST STATS: DB query took {db_time:.2f}s", flush=True)
    
    return {
        'registered_agents': agents_count,
        'total_verified': collective_wisdom,
        'leaderboard': leaderboard,
        'factions': factions,
        'proposals': proposals,
        # GitHub stats will be loaded separately
        'integrated': None,
        'active': None,
        'filtered': None,
        'system_health': None,
        'articles': [],
        'columns': [],
        'signal_items': [],
        'interviews': [],
        'sources': [],
        'article_count': 0,
        'column_count': 0,
        'signal_count': 0,
        'interview_count': 0,
        'source_count': 0
    }


def get_github_stats(force_refresh=False):
    """Get GitHub stats - tries database first for instant loading.
    
    Args:
        force_refresh: If True, sync from GitHub API before returning
    """
    from services.github import get_signals_from_db, get_featured_pr_numbers
    
    # ... (existing code for force_refresh and signals/repo_totals) ...
    # Try database first for instant loading
    signals, repo_totals = get_signals_from_db()
    
    # If database is empty, fall back to GitHub API
    if not signals:
        from services.github import get_repository_signals
        signals, _, _ = get_repository_signals(limit=200)
        repo_totals = get_repo_totals()

    featured_prs = get_featured_pr_numbers()
    visible_signals = [s for s in signals if s.get('pr_number') in featured_prs or s.get('status') == 'active']
    
    # Add date field
    for s in signals:
        if 'created_at' in s and 'date' not in s:
            try:
                dt = datetime.fromisoformat(s['created_at'].replace('Z', '+00:00'))
                s['date'] = dt.strftime('%b %d')
            except:
                s['date'] = s.get('created_at', '')[:10]
    
    return {
        'integrated': repo_totals.get('integrated', 0),
        'published': repo_totals.get('published', 0),
        'active': repo_totals.get('active', 0),
        'filtered': repo_totals.get('filtered', 0),
        'articles': [s for s in visible_signals if s.get('type') == 'article'],
        'columns': [s for s in visible_signals if s.get('type') == 'column'],
        'signal_items': [s for s in visible_signals if s.get('type') == 'signal'],
        'interviews': [s for s in visible_signals if s.get('type') == 'interview'],
        'sources': [s for s in visible_signals if s.get('type') == 'source'],
        'article_count': len([s for s in visible_signals if s.get('type') == 'article']),
        'column_count': len([s for s in visible_signals if s.get('type') == 'column']),
        'signal_count': len([s for s in visible_signals if s.get('type') == 'signal']),
        'interview_count': len([s for s in visible_signals if s.get('type') == 'interview']),
        'source_count': len([s for s in visible_signals if s.get('type') == 'source'])
    }


def get_stats_data():
    """
    Get stats data with Supabase-backed caching for Vercel.
    
    Uses get_or_compute to:
    1. Return cached data immediately if available and not expired
    2. Compute fresh data on cache miss
    3. Store result in cache for subsequent requests
    """
    return get_or_compute('stats_data', _compute_stats_data, STATS_CACHE_TTL)


def _compute_stats_data():
    """
    Compute stats data from scratch - called only on cache miss.
    
    Optimizations:
    - Single query for all agents
    - Batch fetch for proposal comments (fixes N+1)
    - Compute repo totals from fetched signals (no Search API)
    """
    from app import supabase
    from services.github import get_repository_signals, get_repo_totals
    
    if not supabase:
        return _get_empty_stats()
    
    repo_name = os.environ.get('REPO_NAME')
    if not repo_name:
        empty = _get_empty_stats()
        empty['error'] = 'Configuration Error: REPO_NAME missing.'
        return empty
    
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
    
    for row in (agents_response.data or []):
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
    
    # Build leaderboard from first query result (no second query needed)
    all_agents_sorted = sorted(
        agents_response.data or [],
        key=lambda x: float(x.get('xp', 0)),
        reverse=True
    )
    leaderboard = [
        {'name': a['name'], 'faction': a.get('faction', 'Wanderer'), 'xp': a.get('xp', 0)}
        for a in all_agents_sorted[:10]
    ]
    
    # Calculate total XP from first query (no third query needed)
    total_xp = sum(float(row.get('xp', 0)) for row in (agents_response.data or []))
    
    # 2. Fetch Signals (Pull Requests) from GitHub
    gh_start = time.time()
    from services.github import get_featured_pr_numbers
    featured_prs = get_featured_pr_numbers()
    
    # Get signals (we fetch more to ensure we have enough featured ones)
    signals_all, _, _ = get_repository_signals(limit=200)
    
    # Filter for featured and active only
    signals = [s for s in signals_all if s.get('pr_number') in featured_prs or s.get('status') == 'active']
    
    # Get accurate repository-wide totals
    repo_totals = get_repo_totals()
    gh_time = time.time() - gh_start
    
    # Add date field to each signal (template expects pr.date, data has created_at)
    for s in signals:
        if 'created_at' in s and 'date' not in s:
            try:
                dt = datetime.fromisoformat(s['created_at'].replace('Z', '+00:00'))
                s['date'] = dt.strftime('%b %d')
            except Exception:
                s['date'] = s.get('created_at', '')[:10]
    
    # Group signals by type (for the activity list)
    articles = [s for s in signals if s.get('type') == 'article']
    columns = [s for s in signals if s.get('type') == 'column']
    signal_items = [s for s in signals if s.get('type') == 'signal']
    interviews = [s for s in signals if s.get('type') == 'interview']
    sources = [s for s in signals if s.get('type') == 'source']
    
    # Collective Wisdom formula: Total XP / 1000
    collective_wisdom = round(total_xp / 1000, 2)
    
    # Use accurate repo totals from get_repo_totals()
    integrated = repo_totals.get('integrated', 0)
    published = repo_totals.get('published', 0)
    active = repo_totals.get('active', 0)
    filtered = repo_totals.get('filtered', 0)
    
    # Collective Health formula from FAQ:
    # (Collective Wisdom / Registered Agents) + ((Total Merged - Filtered) / 100)
    # Total Merged is now split across integrated and published
    health_base = (collective_wisdom / agents_count) if agents_count > 0 else 0
    health_performance = (integrated + published - filtered) / 100
    system_health = round(health_base + health_performance, 2)
    
    # 3. Fetch Proposals with BATCH comments (fixes N+1 query)
    proposals = []
    prop_start = time.time()
    try:
        proposals_result = supabase.table('proposals').select('*').order('created_at', desc=True).limit(5).execute()
        
        if proposals_result and proposals_result.data:
            proposal_ids = [p['id'] for p in proposals_result.data]
            
            # BATCH fetch all comments at once (instead of N queries)
            all_comments = supabase.table('proposal_comments').select('*').in_('proposal_id', proposal_ids).order('created_at', desc=False).execute()
            
            # Build a map of proposal_id -> comments
            comments_map = {}
            for c in (all_comments.data or []):
                comments_map.setdefault(c['proposal_id'], []).append(c)
            
            # Attach comments to each proposal
            for p in proposals_result.data:
                p['discussion_deadline'] = _format_deadline(p.get('discussion_deadline'))
                p['voting_deadline'] = _format_deadline(p.get('voting_deadline'))
                p['comments'] = comments_map.get(p['id'], [])
                proposals.append(p)
    except Exception as e:
        print(f"Error fetching proposals: {e}")
    prop_time = time.time() - prop_start
    
    total_time = time.time() - start_time
    print(f"STATS PERFORMANCE: DB Agents: {db_agents_time:.2f}s, GitHub: {gh_time:.2f}s, Proposals: {prop_time:.2f}s, Total: {total_time:.2f}s", flush=True)
    
    return {
        'registered_agents': agents_count,
        'total_verified': collective_wisdom,
        'system_health': system_health,
        'integrated': integrated,
        'published': published,
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
        'signal_count': len(signal_items),
        'signal_items': signal_items,
        'interview_count': len(interviews),
        'interviews': interviews,
        'source_count': len(sources),
        'sources': sources
    }


def _format_deadline(dt_str):
    """Format deadline string to human-readable format."""
    if not dt_str:
        return None
    try:
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


def _get_empty_stats():
    """Return empty stats structure for error cases."""
    return {
        'error': 'Database not configured',
        'factions': {},
        'leaderboard': [],
        'proposals': [],
        'articles': [],
        'columns': [],
        'signal_items': [],
        'interviews': [],
        'sources': [],
        'article_count': 0,
        'column_count': 0,
        'signal_count': 0,
        'interview_count': 0,
        'source_count': 0,
        'registered_agents': 0,
        'total_verified': 0,
        'system_health': 0,
        'integrated': 0,
        'active': 0,
        'filtered': 0
    }
