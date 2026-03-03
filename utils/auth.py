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
    
    # Standard agent key verification
    try:
        agents_response = supabase.table('agents').select('*').execute()
        if not agents_response.data:
            return None
            
        for agent in agents_response.data:
            stored_hash = agent['api_key']
            if stored_hash and check_password_hash(stored_hash, api_key):
                if agent_name and agent['name'].lower() != agent_name.lower():
                    continue
                return agent['name']
                
    except Exception as e:
        print(f"Error verifying API key: {e}")
        
    return None

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
