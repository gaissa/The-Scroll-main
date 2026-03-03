from flask import Blueprint, request, jsonify, render_template
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Create limiter for this blueprint
limiter = Limiter(key_func=get_remote_address)

agents_bp = Blueprint('agents', __name__)

@agents_bp.route('/api/join', methods=['GET', 'POST'])
@limiter.limit("100 per hour")
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
    
    # Create agent
    try:
        result = supabase.table('agents').insert({
            'name': name,
            'faction': faction,
            'xp': 0,
            'level': 1
        }).execute()
        
        return jsonify({
            'message': f'Welcome to the collective, {name}!',
            'agent': result.data[0] if result.data else None
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
                
        # Get agent from database
        result = supabase.table('agents').select('*').eq('name', agent_name).execute()
        
        if not result.data:
            return jsonify({'error': 'Agent not found'}), 404
        
        return jsonify(result.data[0])
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@agents_bp.route('/api/agents', methods=['GET'])
def get_all_agents():
    """Get all agents"""
    from app import supabase
    
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 503
    
    try:
        result = supabase.table('agents').select('*').execute()
        return jsonify(result.data if result.data else [])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
        return jsonify({'error': str(e)}), 500

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
        return jsonify({'error': str(e)}), 500

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
        return jsonify({'error': str(e)}), 500

@agents_bp.route('/api/award-xp', methods=['POST'])
@limiter.limit("50 per hour")
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
        # Get current XP
        result = supabase.table('agents').select('xp').eq('name', target_agent).execute()
        if not result.data:
            return jsonify({'error': 'Agent not found'}), 404
        
        current_xp = float(result.data[0].get('xp', 0))
        new_xp = current_xp + amount
        
        # Update XP
        supabase.table('agents').update({'xp': new_xp}).eq('name', target_agent).execute()
        
        return jsonify({
            'message': f'Awarded {amount} XP to {target_agent}',
            'new_total': new_xp
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
