"""
Vercel-compatible caching using Supabase as backing store.

Since Vercel's filesystem is ephemeral and in-memory cache is lost on cold starts,
we use Supabase as a persistent cache layer.
"""
from datetime import datetime, timezone, timedelta


def get_cache(key: str, ttl_seconds: int = 300):
    """
    Get cached data from Supabase if not expired.
    
    Args:
        key: Cache key to look up
        ttl_seconds: Time-to-live in seconds (used for expiration check)
    
    Returns:
        Cached data dict or None if not found/expired
    """
    from app import supabase
    
    if not supabase:
        return None
    
    try:
        result = supabase.table('cache_entries').select('data, expires_at').eq('key', key).execute()
        if result.data:
            entry = result.data[0]
            # Check expiration
            expires_at = entry.get('expires_at')
            if expires_at:
                expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                if datetime.now(timezone.utc) > expires_dt:
                    return None  # Expired
            return entry['data']
    except Exception as e:
        print(f"CACHE GET ERROR ({key}): {e}")
    return None


def set_cache(key: str, data: dict, ttl_seconds: int = 300):
    """
    Store data in Supabase cache with TTL.
    
    Args:
        key: Cache key to store under
        data: Data dict to cache
        ttl_seconds: Time-to-live in seconds
    
    Returns:
        True if successful, False otherwise
    """
    from app import supabase
    
    if not supabase:
        return False
    
    try:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
        supabase.table('cache_entries').upsert({
            'key': key,
            'data': data,
            'expires_at': expires_at
        }, on_conflict='key').execute()
        return True
    except Exception as e:
        print(f"CACHE SET ERROR ({key}): {e}")
        return False


def get_or_compute(key: str, compute_fn, ttl_seconds: int = 300):
    """
    Get from cache or compute and cache the result.
    
    This is the main entry point for cached data access.
    If cache hit, returns cached data immediately.
    If cache miss, calls compute_fn(), caches result, and returns it.
    
    Args:
        key: Cache key to look up
        compute_fn: Callable that returns data to cache (called on miss)
        ttl_seconds: Time-to-live in seconds
    
    Returns:
        Cached or computed data dict
    """
    cached = get_cache(key, ttl_seconds)
    if cached is not None:
        print(f"CACHE HIT: {key}")
        return cached
    
    print(f"CACHE MISS: {key}")
    data = compute_fn()
    if data:
        set_cache(key, data, ttl_seconds)
    return data


def get_stale_or_compute(key: str, compute_fn, ttl_seconds: int = 300, stale_seconds: int = 3600):
    """
    Get from cache (even if stale) or compute.
    
    Stale-while-revalidate pattern:
    - Return cached data immediately even if expired (up to stale_seconds)
    - If no cache or too stale, compute fresh data
    
    Args:
        key: Cache key to look up
        compute_fn: Callable that returns data to cache
        ttl_seconds: Fresh TTL in seconds
        stale_seconds: Maximum stale age in seconds (default 1 hour)
    
    Returns:
        Cached (possibly stale) or computed data dict
    """
    from app import supabase, init_supabase
    
    # Initialize supabase if needed
    if supabase is None:
        init_supabase()
        from app import supabase
    
    if not supabase:
        return compute_fn()
    
    try:
        result = supabase.table('cache_entries').select('data, updated_at').eq('key', key).execute()
        if result.data:
            entry = result.data[0]
            data = entry.get('data')
            updated_at = entry.get('updated_at')
            
            if data and updated_at:
                # Check if data is within stale window
                from datetime import datetime, timezone, timedelta
                try:
                    updated_dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                    age = (datetime.now(timezone.utc) - updated_dt).total_seconds()
                    
                    # Return if within stale window (even if past TTL)
                    if age < stale_seconds:
                        print(f"CACHE STALE HIT: {key} (age: {age:.0f}s)")
                        return data
                except:
                    pass
    except Exception as e:
        print(f"CACHE STALE ERROR ({key}): {e}")
    
    # Cache miss or too stale - compute fresh
    print(f"CACHE STALE MISS: {key}")
    data = compute_fn()
    if data:
        set_cache(key, data, ttl_seconds)
    return data


def invalidate_cache(key: str):
    """
    Remove a cache entry.
    
    Args:
        key: Cache key to remove
    
    Returns:
        True if successful, False otherwise
    """
    from app import supabase, init_supabase
    
    if supabase is None:
        init_supabase()
        from app import supabase
    
    if not supabase:
        return False
    
    try:
        supabase.table('cache_entries').delete().eq('key', key).execute()
        return True
    except Exception as e:
        print(f"CACHE INVALIDATE ERROR ({key}): {e}")
        return False


def clean_expired_cache():
    """
    Remove all expired cache entries.
    Can be called periodically or via cron job.
    
    Returns:
        Number of entries removed, or -1 on error
    """
    from app import supabase
    
    if not supabase:
        return -1
    
    try:
        now = datetime.now(timezone.utc).isoformat()
        result = supabase.table('cache_entries').delete().lt('expires_at', now).execute()
        return len(result.data) if result.data else 0
    except Exception as e:
        print(f"CACHE CLEAN ERROR: {e}")
        return -1