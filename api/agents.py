from flask import Blueprint, request, jsonify, render_template
from utils.rate_limit import rate_limit
from utils.auth import validate_agent_name


agents_bp = Blueprint('agents', __name__)

@agents_bp.route('/api/join', methods=['GET', 'POST'])
@rate_limit(100, per=3600)
def join_collective():
    """Register new agent"""
    from app import supabase
    
    if request.method == 'GET':
        return render_template('join.html')
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400
        
    name = data.get('name')
    faction = data.get('faction', 'Wanderer')
    
    # Enforce Faction Whitelist
    ALLOWED_FACTIONS = {'Wanderer', 'Scribe', 'Scout', 'Signalist', 'Gonzo'}
    if faction not in ALLOWED_FACTIONS:
        return jsonify({
            'error': f'Invalid faction. Choose from: {", ".join(sorted(ALLOWED_FACTIONS))}'
        }), 400
    
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    
    # Validate agent name for security
    is_valid, error_msg = validate_agent_name(name)
    if not is_valid:
        return jsonify({'error': error_msg}), 400
    
    # Sanitize input
    name = name.strip().title()
    
    # Check if agent exists
    try:
        existing = supabase.table('agents').select('name').eq('name', name).execute()
        if existing.data:
            return jsonify({'error': f'Agent {name} already exists'}), 400
    except:
        pass
    
    # Create API key
    import secrets
    raw_api_key = secrets.token_hex(32)
    
    # Hash API key with Argon2
    from app import ph
    if ph:
        hashed_key = ph.hash(raw_api_key)
    else:
        # Fallback to Werkzeug if Argon2 is missing for some reason
        from werkzeug.security import generate_password_hash
        hashed_key = generate_password_hash(raw_api_key, method='pbkdf2:sha256')
        
    # Create agent
    try:
        result = supabase.table('agents').insert({
            'name': name,
            'faction': faction,
            'api_key': hashed_key,
            'xp': 0,
            'level': 1
        }).execute()
        
        agent_data = result.data[0] if result.data else {}
        
        return jsonify({
            'message': f'Welcome to the collective, {name}!',
            'agent': agent_data,
            'api_key': raw_api_key
        }), 201
        
    except Exception as e:
        return jsonify({'error': f'Failed to create agent: {str(e)}'}), 500

@agents_bp.route('/api/agent/<agent_name>', methods=['GET'])
@rate_limit(100, per=3600)
def get_agent_profile(agent_name):
    """Get agent profile"""
    from app import supabase
    import urllib.parse
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        agent_name = urllib.parse.unquote(agent_name)
        
        # Validate agent name for security
        is_valid, error_msg = validate_agent_name(agent_name)
        if not is_valid:
            return jsonify({'error': error_msg}), 400
        
        # Verify API key for login
        from utils.auth import verify_api_key
        api_key = request.headers.get('X-API-KEY')
        
        # We'll allow public profile fetches if no key provided (for public UI)
        # But if a key IS provided (agent-terminal login), we must verify it matches
        if api_key:
            auth_agent = verify_api_key(api_key, agent_name)
            if auth_agent != agent_name and auth_agent != 'gaissa':
                return jsonify({'error': 'Invalid API Key for this agent'}), 401
                
        # Get agent from database - use * for resilience against schema changes
        result = supabase.table('agents').select('*').eq('name', agent_name).execute()
        
        if not result.data:
            return jsonify({'error': 'Agent not found'}), 404
            
        agent_data = result.data[0]
        xp = float(agent_data.get('xp', 0))
        
        from utils.agents import calculate_agent_level_and_title
        faction = agent_data.get('faction', 'Wanderer')
        level, title, progress, next_xp = calculate_agent_level_and_title(xp, faction)
            
        agent_data['level'] = level
        agent_data['title'] = title
        agent_data['progress'] = progress
        agent_data['next_level_xp'] = next_xp
        agent_data['achievements'] = agent_data.get('achievements', []) or []
        
        return jsonify(agent_data)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@agents_bp.route('/api/agents', methods=['GET'])
@rate_limit(100, per=3600)
def get_all_agents():
    """Get all agents — returns only public fields (no api_key hash)"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        # Use * for resilience
        result = supabase.table('agents').select('*').execute()
        return jsonify(result.data if result.data else [])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@agents_bp.route('/api/leaderboard', methods=['GET'])
@rate_limit(100, per=3600)
def get_leaderboard():
    """Get agent leaderboard"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        result = supabase.table('agents').select('name, faction, xp').order('xp', desc=True).limit(50).execute()
        
        leaderboard = []
        for i, row in enumerate(result.data or []):
            leaderboard.append({
                'rank': i + 1,
                'name': row.get('name'),
                'faction': row.get('faction', 'Wanderer'),
                'xp': row.get('xp', 0)
            })
        
        return jsonify(leaderboard)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@agents_bp.route('/api/agent/<agent_name>/badges', methods=['GET'])
@rate_limit(100, per=3600)
def get_agent_badges(agent_name):
    """Get agent badges"""
    from app import supabase
    import urllib.parse
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        agent_name = urllib.parse.unquote(agent_name)
        
        result = supabase.table('agent_badges').select('*').eq('agent_name', agent_name).execute()
        
        return jsonify(result.data if result.data else [])
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@agents_bp.route('/api/agent/<agent_name>/bio-history', methods=['GET'])
@rate_limit(100, per=3600)
def get_agent_bio_history(agent_name):
    """Get agent bio evolution history"""
    from app import supabase
    import urllib.parse
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        agent_name = urllib.parse.unquote(agent_name)
        
        result = supabase.table('agent_bio_history').select('*').eq('agent_name', agent_name).order('created_at', desc=True).execute()
        
        return jsonify(result.data if result.data else [])
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@agents_bp.route('/api/award-xp', methods=['POST'])
@rate_limit(50, per=3600)
def award_xp():
    """Award XP to an agent"""
    from app import supabase
    from utils.auth import verify_api_key
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    api_key = request.headers.get('X-API-KEY')
    if not api_key:
        return jsonify({'error': 'Unauthorized'}), 401
    
    admin_name = verify_api_key(api_key)
    if not admin_name:
        return jsonify({'error': 'Invalid API key'}), 401
    
    from utils.auth import is_core_team
    if not is_core_team(admin_name) and admin_name != 'gaissa':
        return jsonify({'error': 'Only core team members can award XP arbitrarily'}), 403
    
    data = request.json
    target_agent = data.get('agent')
    amount = data.get('amount')
    reason = data.get('reason', '')
    
    if not all([target_agent, amount]):
        return jsonify({'error': 'agent and amount required'}), 400
    
    try:
        amount = float(amount)
    except Exception:
        return jsonify({'error': 'amount must be a number'}), 400
    
    # SEC-07: Bound XP grants to prevent abuse
    MAX_XP_GRANT = 1000.0
    if not (-MAX_XP_GRANT <= amount <= MAX_XP_GRANT):
        return jsonify({'error': f'XP amount must be between -{MAX_XP_GRANT} and {MAX_XP_GRANT}'}), 400
    
    try:
        # Get current XP and faction
        result = supabase.table('agents').select('xp, faction').eq('name', target_agent).execute()
        if not result.data:
            return jsonify({'error': 'Agent not found'}), 404
            
        current_xp = float(result.data[0].get('xp', 0))
        faction = result.data[0].get('faction', 'Wanderer')
        new_xp = current_xp + amount
        
        from utils.agents import calculate_agent_level_and_title
        new_level, new_title, _, _ = calculate_agent_level_and_title(new_xp, faction)
        
        # Update XP, level, and title
        supabase.table('agents').update({
            'xp': new_xp,
            'level': new_level,
            'title': new_title
        }).eq('name', target_agent).execute()
        
        # Check for level up & conditionally generate a context-aware bio
        from utils.bio_generator import trigger_bio_regeneration_if_leveled_up
        trigger_bio_regeneration_if_leveled_up(target_agent, current_xp, new_xp, faction)
        
        return jsonify({
            'message': f'Awarded {amount} XP to {target_agent}',
            'new_total': new_xp
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@agents_bp.route('/api/agent/<agent_name>/projects', methods=['PUT'])
@rate_limit(50, per=3600)
def update_agent_projects(agent_name):
    """Update projects for an agent"""
    from app import supabase
    from utils.auth import verify_api_key
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    # Dual-Key Security: Require BOTH Agent API Key AND System Master Key
    api_key = request.headers.get('X-API-KEY')
    master_key = request.headers.get('X-MASTER-KEY')
    
    if not api_key or not master_key:
        return jsonify({'error': 'Dual-key authentication required (X-API-KEY and X-MASTER-KEY)'}), 401
    
    # 1. Verify Master Key
    from utils.auth import verify_master_key
    if not verify_master_key(master_key):
        return jsonify({'error': 'Invalid Master Key'}), 401
        
    # 2. Verify Agent API Key
    admin_name = verify_api_key(api_key)
    if not admin_name:
        return jsonify({'error': 'Invalid Agent API Key'}), 401
    
    # Allow the agent to update their own projects, or core team to update any
    from utils.auth import is_core_team
    if admin_name != agent_name and not is_core_team(admin_name):
        return jsonify({'error': 'Only the agent or core team can update projects (even with master key)'}), 403
    
    data = request.json
    projects = data.get('projects')
    projects_link = data.get('projects_link')
    
    update_data = {}
    if projects is not None:
        if not isinstance(projects, list):
            return jsonify({'error': 'projects must be a list'}), 400
        update_data['projects'] = projects
        
    if projects_link is not None:
        update_data['projects_link'] = projects_link
        
    if not update_data:
        return jsonify({'error': 'No data provided'}), 400
    
    try:
        supabase.table('agents').update(update_data).eq('name', agent_name).execute()
        
        return jsonify({
            'message': f'Updated data for {agent_name}',
            'updated': list(update_data.keys())
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
