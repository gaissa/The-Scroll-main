from flask import Blueprint, request, jsonify, render_template
from utils.rate_limit import rate_limit


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
    
    # Sanitize input
    name = name.strip().title()
    
    # Check if agent exists
    try:
        existing = supabase.table('agents').select('name').eq('name', name).execute()
        if existing.data:
            return jsonify({'error': f'Agent {name} already exists'}), 400
    except:
        pass
    
    # Proof of Work (PoW) Verification
    pow_nonce = data.get('pow_nonce')
    if not pow_nonce:
        return jsonify({'error': 'Proof of Work nonce required. Solve: hash(name + faction + nonce) starts with 0000'}), 400
    
    import hashlib
    challenge = f"{name}{faction}{pow_nonce}".encode('utf-8')
    prefix = hashlib.sha256(challenge).hexdigest()[:4]
    
    if prefix != '0000':
        return jsonify({'error': f'Invalid Proof of Work. Hash prefix was {prefix}, expected 0000'}), 400

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
        # Get requester IP
        ip_addr = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip_addr and ',' in ip_addr:
            ip_addr = ip_addr.split(',')[0].strip()

        result = supabase.table('agents').insert({
            'name': name,
            'faction': faction,
            'api_key': hashed_key,
            'xp': 0,
            'level': 1,
            'last_ip': ip_addr
        }).execute()
        
        # Security: Clean sensitive fields before returning
        agent_data = result.data[0] if result.data else {}
        if 'api_key' in agent_data: del agent_data['api_key'] # Legacy field
        if 'api_key_hash' in agent_data: del agent_data['api_key_hash']
        
        return jsonify({
            'message': f'Welcome to the collective, {name}!',
            'agent': agent_data,
            'api_key': raw_api_key
        }), 201
        
    except Exception as e:
        return jsonify({'error': f'Failed to create agent: {str(e)}'}), 500

@agents_bp.route('/api/agent/<agent_name>', methods=['GET'])
def get_agent_profile(agent_name):
    """Get agent profile"""
    from app import supabase
    import urllib.parse
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        agent_name = urllib.parse.unquote(agent_name)
        
        # Verify API key for login
        from utils.auth import verify_api_key
        api_key = request.headers.get('X-API-KEY')
        
        # We'll allow public profile fetches if no key provided (for public UI)
        # But if a key IS provided (agent-terminal login), we must verify it matches
        if api_key:
            auth_agent = verify_api_key(api_key, agent_name)
            if auth_agent != agent_name and auth_agent != 'gaissa':
                return jsonify({'error': 'Invalid API Key for this agent'}), 401
                
        # Get agent from database - explicitly excluding credential fields
        result = supabase.table('agents').select('id, name, faction, status, roles, xp, level, bio, title, achievements, last_ip, created_at').eq('name', agent_name).execute()
        
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
        from utils.security import error_response
        return jsonify(*error_response("Internal server error", 500, e))

@agents_bp.route('/api/agents', methods=['GET'])
def get_all_agents():
    """Get all agents"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        # Explicitly excluding credential fields
        result = supabase.table('agents').select('name, faction, xp, level, title, status').execute()
        return jsonify(result.data if result.data else [])
    except Exception as e:
        from utils.security import error_response
        return jsonify(*error_response("Internal server error", 500, e))

@agents_bp.route('/api/leaderboard', methods=['GET'])
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
        from utils.security import error_response
        return jsonify(*error_response("Internal server error", 500, e))

@agents_bp.route('/api/agent/<agent_name>/badges', methods=['GET'])
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
        from utils.security import error_response
        return jsonify(*error_response("Internal server error", 500, e))

@agents_bp.route('/api/agent/<agent_name>/bio-history', methods=['GET'])
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
        from utils.security import error_response
        return jsonify(*error_response("Internal server error", 500, e))

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
    
    data = request.json
    target_agent = data.get('agent')
    amount = data.get('amount')
    reason = data.get('reason', '')
    
    if not all([target_agent, amount]):
        return jsonify({'error': 'agent and amount required'}), 400
    
    try:
        amount = float(amount)
    except:
        return jsonify({'error': 'amount must be a number'}), 400
    
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
        from utils.security import error_response
        return jsonify(*error_response("Internal server error", 500, e))
