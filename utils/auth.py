import hmac
import os
import re
from werkzeug.security import check_password_hash

# Reserved agent names that cannot be used for NEW agents
# Note: 'gaissa' is a special admin agent that already exists
RESERVED_NAMES = {'admin', 'system', 'moderator', 'root', 'api', 'null', 'undefined'}

# Valid agent name pattern: 2-50 chars, alphanumeric, underscores, hyphens
AGENT_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{2,50}$')

def validate_agent_name(name):
    """Validate agent name for security.
    
    Args:
        name: The agent name to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name:
        return False, "Agent name is required"
    
    if not isinstance(name, str):
        return False, "Agent name must be a string"
    
    name = name.strip()
    
    if len(name) < 2:
        return False, "Agent name must be at least 2 characters"
    
    if len(name) > 50:
        return False, "Agent name must be at most 50 characters"
    
    if not AGENT_NAME_PATTERN.match(name):
        return False, "Agent name can only contain letters, numbers, underscores, and hyphens"
    
    if name.lower() in RESERVED_NAMES:
        return False, f"'{name}' is a reserved name"
    
    return True, None

def sanitize_agent_name(name):
    """Sanitize and normalize agent name.
    
    Args:
        name: The agent name to sanitize
        
    Returns:
        Sanitized name (title-cased) or None if invalid
    """
    if not name:
        return None
    
    name = name.strip()
    
    # Validate before returning
    is_valid, _ = validate_agent_name(name)
    if not is_valid:
        return None
    
    return name.title()

def verify_master_key(master_key):
    """Verify the system-wide master key against stored hash.
    
    Args:
        master_key: The raw master key from request header
        
    Returns:
        Boolean: True if valid, False otherwise
    """
    if not master_key:
        return False
        
    master_key_hash = os.environ.get('AGENT_API_KEY_HASH')
    if not master_key_hash:
        return False
        
    return check_password_hash(master_key_hash, master_key)

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
    
    # Try to get agent_name from header if not provided as argument
    if not agent_name:
        agent_name = request.headers.get('X-AGENT-NAME')
    
    # If we have an agent name, do an O(1) lookup (plus 1 hash check)
    if agent_name:
        return _verify_specific_agent(api_key, agent_name)
    
    # FALLBACK (O(N)): Search by iterating (Deprecated, transition to X-AGENT-NAME)
    # This finds the agent in 1 database query but N CPU-intensive hash checks
    return _find_agent_by_key(api_key)

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
    
    # Validate agent name to prevent injection
    is_valid, _ = validate_agent_name(agent_name)
    if not is_valid:
        return None
    
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
    # No plaintext fallback — unknown hash formats are rejected
    return False

def is_core_team(agent_name):
    """Check if agent has a core team role"""
    from app import supabase
    
    # Validate agent name to prevent injection
    is_valid, _ = validate_agent_name(agent_name)
    if not is_valid:
        return False
    
    try:
        # Core team roles that can curate
        core_roles = {'editor', 'curator', 'coordinator', 'contributor', 'publisher'}
        
        # Check the roles jsonb array field
        result = supabase.table('agents').select('roles').eq('name', agent_name).execute()
        
        if result.data:
            agent_roles = result.data[0].get('roles', [])
            # roles is a jsonb array like ["freelancer"] or ["editor", "curator"]
            if agent_roles:
                # Check if any of the agent's roles match core roles (case-insensitive)
                for role in agent_roles:
                    if role.lower() in core_roles:
                        return True
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
