import os

def get_github_client():
    """Get GitHub client"""
    try:
        from github import Github, Auth
        token = os.environ.get('GITHUB_TOKEN')
        if token:
            # Disable automatic retries to prevent the 10-minute hang on secondary rate limits
            return Github(auth=Auth.Token(token), retry=None)
        return None
    except ImportError:
        return None

def get_repo():
    """Get GitHub repository"""
    try:
        g = get_github_client()
        if not g:
            return None
        
        repo_name = os.environ.get('REPO_NAME')
        if not repo_name:
            return None
        
        return g.get_repo(repo_name)
    except:
        return None

import yaml
import json

# Persistent cache for full signals list (as fallback)
SIGNALS_CACHE_FILE = os.path.join(os.path.dirname(__file__), 'signals_cache.json')

# Persistent cache for PR metadata (author, type)
PR_CACHE_FILE = os.path.join(os.path.dirname(__file__), 'pr_cache.json')
_pr_metadata_cache = {}

def _load_pr_cache():
    global _pr_metadata_cache
    if os.path.exists(PR_CACHE_FILE):
        try:
            with open(PR_CACHE_FILE, 'r') as f:
                _pr_metadata_cache = json.load(f)
        except Exception as e:
            print(f"CACHE: Error loading pr_cache.json: {e}", flush=True)
    else:
        _pr_metadata_cache = {}

def _save_pr_cache():
    try:
        with open(PR_CACHE_FILE, 'w') as f:
            json.dump(_pr_metadata_cache, f)
    except Exception as e:
        print(f"CACHE: Error saving pr_cache.json: {e}", flush=True)

def _load_signals_cache():
    if os.path.exists(SIGNALS_CACHE_FILE):
        try:
            with open(SIGNALS_CACHE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"CACHE: Error loading signals_cache.json: {e}", flush=True)
    return []

def _save_signals_cache(signals):
    try:
        with open(SIGNALS_CACHE_FILE, 'w') as f:
            json.dump(signals, f)
    except Exception as e:
        print(f"CACHE: Error saving signals_cache.json: {e}", flush=True)

from github import Github, Auth, RateLimitExceededException, GithubException

def get_repository_signals(limit=50, page=0, category=None):
    """Fetch PRs/signals from GitHub with metadata caching and persistent signals fallback"""
    print(f"FETCH: get_repository_signals(limit={limit}) called", flush=True)
    
    # 1. Load data from disk first as potential fallback
    _load_pr_cache()
    cached_signals = _load_signals_cache()
    
    signals = []
    try:
        g = get_github_client()
        if not g:
            print("GITHUB: Client not initialized. Returning signals from disk.", flush=True)
            return cached_signals, len(cached_signals)
        
        repo_name = os.environ.get('REPO_NAME')
        if not repo_name:
            return cached_signals, len(cached_signals)
        
        repo = g.get_repo(repo_name)
        
        # Category to label mapping
        category_queries = {
            'articles': 'Zine Submission',
            'columns': 'Zine Column',
            'specials': 'Zine Special Issue',
            'signals': 'Zine Signal',
            'interviews': 'Zine Interview'
        }
        
        # Get all PRs (open and closed)
        prs = repo.get_pulls(state='all', sort='created', direction='desc')
        
        count = 0
        deep_parses_this_run = 0
        MAX_DEEP_PARSES = 10 # Slightly more allowed now that we have fast-fail and disk fallback
        
        for pr in prs:
            if count >= limit:
                break
            
            labels = [label.name for label in pr.labels]
            
            # Skip ignored
            if 'Zine: Ignore' in labels:
                continue
            
            # Filter by category if specified
            if category and category in category_queries:
                if category_queries[category] not in labels:
                    continue
            
            # Metadata Cache Key
            cache_key = f"{pr.number}_{pr.head.sha}"
            
            pauthor = pr.user.login
            ptype = 'signal'
            if 'Zine Submission' in labels: ptype = 'article'
            elif 'Zine Column' in labels: ptype = 'column'
            elif 'Zine Special Issue' in labels: ptype = 'special'
            elif 'Zine Signal' in labels: ptype = 'signal'
            elif 'Zine Interview' in labels: ptype = 'interview'

            if cache_key in _pr_metadata_cache:
                pauthor = _pr_metadata_cache[cache_key]['author']
                ptype = _pr_metadata_cache[cache_key]['type']
            elif deep_parses_this_run < MAX_DEEP_PARSES:
                # TRY TO PARSE REAL AUTHOR AND TYPE FROM CONTENT
                try:
                    # Find the contribution file
                    files = pr.get_files()
                    for f in files:
                        if f.filename.startswith('submissions/') and f.filename.endswith('.md'):
                            # Get content from the head of the PR branch
                            content_file = repo.get_contents(f.filename, ref=pr.head.sha)
                            decoded_content = content_file.decoded_content.decode('utf-8')
                            
                            if decoded_content.startswith('---'):
                                parts = decoded_content.split('---', 2)
                                if len(parts) >= 3:
                                    fm = yaml.safe_load(parts[1])
                                    if fm:
                                        if fm.get('author'): pauthor = fm['author']
                                        if fm.get('type'): ptype = fm['type']
                            
                            deep_parses_this_run += 1
                            break 
                    
                    # Update cache incrementally
                    _pr_metadata_cache[cache_key] = {
                        'author': pauthor,
                        'type': ptype
                    }
                    _save_pr_cache()
                    print(f"CACHE: Updated PR #{pr.number} metadata ({pauthor}, {ptype})", flush=True)
                except (RateLimitExceededException, GithubException) as re:
                    print(f"GITHUB RATE LIMIT/FAIL during PR #{pr.number}: {re}. Falling back to defaults.", flush=True)
                    deep_parses_this_run = MAX_DEEP_PARSES # Stop deep parsing this run
                except Exception as fe:
                    print(f"Error parsing PR #{pr.number} content: {fe}", flush=True)

            # Check for verification labels
            is_verified = pr.merged or any(l.lower() in ['verified', 'agnt_verified', 'approved', 'agnt verified'] for l in labels)
            
            signals.append({
                'pr_number': pr.number,
                'title': pr.title,
                'author': pauthor,
                'type': ptype,
                'status': 'active' if pr.state == 'open' else ('integrated' if pr.merged else 'filtered'),
                'labels': labels,
                'verified': is_verified,
                'url': pr.html_url,
                'created_at': pr.created_at.isoformat()
            })
            count += 1
            
        # 3. Success! Save these signals to disk as the new "last known good" fallback
        if signals:
            # Fetch TOTAL repository counts using Search API (unlimited by pagination)
            repo_totals = {
                'integrated': 0,
                'active': 0,
                'filtered': 0
            }
            try:
                # Integrated: Total merged (not ignored)
                repo_totals['integrated'] = g.search_issues(f"repo:{repo_name} is:pr is:merged -label:\"Zine: Ignore\"").totalCount
                # Active: Total open (not ignored)
                repo_totals['active'] = g.search_issues(f"repo:{repo_name} is:pr is:open -label:\"Zine: Ignore\"").totalCount
                # Filtered: PRs that were closed but not merged (rejected submissions)
                repo_totals['filtered'] = g.search_issues(f"repo:{repo_name} is:pr is:closed -is:merged -label:\"Zine: Ignore\"").totalCount
                print(f"FETCH: True Repository Totals: {repo_totals}", flush=True)
            except Exception as e:
                print(f"GITHUB ERROR fetching totals: {e}", flush=True)

            cached_data = {
                'signals': signals,
                'repo_totals': repo_totals
            }
            _save_signals_cache(cached_data)
            return signals, len(signals), repo_totals
            
        return signals, len(signals), {'integrated': 0, 'active': 0, 'filtered': 0}

    except (RateLimitExceededException, GithubException) as e:
        print(f"GITHUB ERROR: {e}. Returning cached signals/totals from disk.", flush=True)
        # Handle the case where signals_cache.json might be the old format (just a list)
        if isinstance(cached_signals, dict):
            return cached_signals.get('signals', []), len(cached_signals.get('signals', [])), cached_signals.get('repo_totals', {})
        return cached_signals, len(cached_signals), {}
    except Exception as e:
        print(f"Error fetching signals from GitHub: {e}. Returning disc fallback.", flush=True)
        if isinstance(cached_signals, dict):
            return cached_signals.get('signals', []), len(cached_signals.get('signals', [])), cached_signals.get('repo_totals', {})
        return cached_signals, len(cached_signals), {}

def get_pr_stats():
    """Get PR statistics"""
    try:
        repo = get_repo()
        if not repo:
            return {}
        
        open_prs = repo.get_pulls(state='open')
        closed_prs = repo.get_pulls(state='closed')
        
        return {
            'open': open_prs.totalCount,
            'closed': closed_prs.totalCount
        }
    except:
        return {}
