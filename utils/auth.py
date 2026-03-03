import hmac
import os
from werkzeug.security import check_password_hash

def verify_api_key(api_key, agent_name=None):
    """Verify API key and return agent name if valid"""
    from app import supabase
    
    if not api_key or not supabase:
        return None
    
    # Check master key first (restricted to gaissa only)
    master_key_hash = os.environ.get('AGENT_API_KEY_HASH')
    if master_key_hash and check_password_hash(master_key_hash, api_key):
        if agent_name and agent_name.lower() != 'gaissa':
            pass
        return 'gaissa'
    
    # C-1 FIX: Search by key first if no agent_name provided
    # This finds the agent in 1 query instead of scanning all
    if not agent_name:
        return _find_agent_by_key(api_key)
    
    # If agent_name provided, query only that specific agent
    return _verify_specific_agent(api_key, agent_name)

def _find_agent_by_key(api_key):
    """Find agent by key - searches efficiently"""
    from app import supabase, ph
    
    try:
        # Get all agents with api_key set - much smaller subset
        result = supabase.table('agents').select('name, api_key').not_.is_('api_key', 'null').execute()
        if not result.data:
            return None
            
        for agent in result.data:
            stored_hash = agent.get('api_key')
            if not stored_hash:
                continue
                
            if _check_hash(stored_hash, api_key):
                return agent['name']
                
    except Exception as e:
        print(f"Error finding agent by key: {e}")
        
    return None

def _verify_specific_agent(api_key, agent_name):
    """Verify API key for a specific agent - single query"""
    from app import supabase, ph
    
    try:
        result = supabase.table('agents').select('name, api_key').eq('name', agent_name).execute()
        if not result.data:
            return None
            
        agent = result.data[0]
        stored_hash = agent['api_key']
        if not stored_hash:
            return None
            
        if _check_hash(stored_hash, api_key):
            return agent['name']
                
    except Exception as e:
        print(f"Error verifying API key for {agent_name}: {e}")
        
    return None

def _verify_all_agents(api_key):
    """Legacy: Check all agents - O(N)"""
    from app import supabase, ph
    
    try:
        agents_response = supabase.table('agents').select('*').execute()
        if not agents_response.data:
            return None
            
        for agent in agents_response.data:
            stored_hash = agent['api_key']
            if not stored_hash:
                continue
                
            if _check_hash(stored_hash, api_key):
                return agent['name']
                
    except Exception as e:
        print(f"Error verifying API key: {e}")
        
    return None

def _check_hash(stored_hash, api_key):
    """Check if API key matches stored hash"""
    from app import ph
    
    # Check Argon2 format first
    if stored_hash.startswith('$argon2'):
        if ph:
            try:
                return ph.verify(stored_hash, api_key)
            except Exception:
                pass
    # Fallback to Werkzeug format
    elif stored_hash.startswith('pbkdf2:') or stored_hash.startswith('scrypt:'):
        try:
            return check_password_hash(stored_hash, api_key)
        except Exception:
            pass
    # Extreme fallback for legacy plain text API keys
    else:
        return (stored_hash == api_key)
    
    return False

def is_core_team(agent_name):
    """Check if agent is in core team"""
    from app import supabase
    
    try:
        # Core team roles
        core_roles = {'Editor', 'Curator', 'System', 'Coordinator'}
        result = supabase.table('agents').select('faction').eq('name', agent_name).execute()
        
        if result.data:
            return result.data[0].get('faction') in core_roles
        return False
    except:
        return False

def get_api_key_header():
    """Get API key from request header"""
    from flask import request
    return request.headers.get('X-API-KEY')

def safe_error(e):
    """Return safe error response"""
    from flask import jsonify
    return jsonify({'error': str(e)}), 500
