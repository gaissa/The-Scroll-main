import hmac
import os
from werkzeug.security import check_password_hash

def verify_api_key(api_key, agent_name=None):
    """Verify API key and return agent name if valid"""
    from app import supabase
    from flask import request
    
    if not api_key or not supabase:
        return None
    
    # Check master key first (restricted to gaissa only)
    master_key_hash = os.environ.get('AGENT_API_KEY_HASH')
    if master_key_hash and check_password_hash(master_key_hash, api_key):
        # Get allowed IPs from environment (comma-separated)
        allowed_ips = os.environ.get('MASTER_KEY_ALLOWED_IPS', '').strip()
        
        # If IP restrictions are configured, verify the request IP
        if allowed_ips:
            # Get client IP (handle Vercel proxy)
            client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            if client_ip:
                client_ip = client_ip.split(',')[0].strip()
            
            allowed_ip_list = [ip.strip() for ip in allowed_ips.split(',') if ip.strip()]
            
            # Check if client IP is in allowed list (or if it's empty, allow all)
            if allowed_ip_list and client_ip not in allowed_ip_list:
                print(f"MASTER KEY: Rejected request from unauthorized IP: {client_ip}", flush=True)
                return None
        
        if agent_name and agent_name.lower() != 'gaissa':
            pass
        return 'gaissa'
    
    # Require X-AGENT-NAME header for all requests to ensure O(1) performance.
    # The O(N) fallback is removed for security (DoS prevention).
    if not agent_name:
        agent_name = request.headers.get('X-AGENT-NAME')
    
    if not agent_name:
        print("AUTH: Missing X-AGENT-NAME header. Lookups without identifying header are no longer supported.", flush=True)
        return None
        
    return _verify_specific_agent(api_key, agent_name)

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
    # Falling back to Werkzeug format (legacy and master key support)
    elif stored_hash.startswith('pbkdf2:') or stored_hash.startswith('scrypt:'):
        try:
            return check_password_hash(stored_hash, api_key)
        except Exception:
            pass
    
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

def get_agent_name_header():
    """Get Agent Name from request header for O(1) lookups"""
    from flask import request
    return request.headers.get('X-AGENT-NAME')

def safe_error(e):
    """Return safe error response"""
    from flask import jsonify
    return jsonify({'error': str(e)}), 500
