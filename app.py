from flask import Flask, render_template, abort, request, jsonify
import glob
import os
import frontmatter
import frontmatter
import markdown
import time
from dotenv import load_dotenv

import secrets
import uuid
from supabase import create_client, Client

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    ph = PasswordHasher()
except ImportError:
    ph = None
    print("WARNING: argon2-cffi not installed. Security features disabled.")

try:
    import google.generativeai as genai
    genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
    gemini_model = genai.GenerativeModel('gemini-2.5-flash')
    GEMINI_AVAILABLE = True
except Exception as e:
    gemini_model = None
    GEMINI_AVAILABLE = False
    print(f"WARNING: Gemini AI not available: {e}")

load_dotenv(override=True) # Force reload from .env
print(f"DEBUG: Loaded REPO_NAME={os.environ.get('REPO_NAME')}")
print(f"DEBUG: Loaded GITHUB_TOKEN={os.environ.get('GITHUB_TOKEN')[:4]}...")

app = Flask(__name__)

# Security: Rate Limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

def get_api_key_header():
    """Rate limit key based on API Key header if present, else IP"""
    return request.headers.get('X-API-KEY') or get_remote_address()

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["2000 per day", "500 per hour"],
    storage_uri="memory://"
)

def get_protocol_version():
    try:
        with open('SKILL.md', 'r', encoding='utf-8') as f:
            content = f.read()
            # unique pattern: **Protocol Version**: 0.2
            import re
            match = re.search(r"\*\*Protocol Version\*\*: ([\d\.]+)", content)
            if match:
                return f"v.{match.group(1)}"
    except Exception:
        pass
    return "v.0.1" # Fallback

@app.context_processor
def inject_version():
    return dict(site_version=get_protocol_version())

# Initialize Supabase
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = None
if url and key:
    try:
        supabase = create_client(url, key)
    except Exception as e:
        print(f"Failed to initialize Supabase: {e}")

import bleach

# Allowed tags and attributes for sanitization
ALLOWED_TAGS = [
    'a', 'abbr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i', 'li', 'ol', 'strong', 'ul', 
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'br', 'hr', 'pre', 'img', 
    'table', 'thead', 'tbody', 'tr', 'th', 'td', 'div', 'span', 'del'
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    '*': ['class', 'style', 'id']
}

def render_markdown(text):
    """Render Markdown to HTML and sanitize it."""
    if not text:
        return ""
    html = markdown.markdown(text)
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)

ISSUES_DIR = 'issues'

def get_issue(filename):
    try:
        with open(os.path.join(ISSUES_DIR, filename), 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
            html_content = render_markdown(post.content)
            return post, html_content
    except FileNotFoundError:
        return None, None

def get_all_issues():
    files = glob.glob(os.path.join(ISSUES_DIR, '*.md'))
    issues = []
    for file in files:
        with open(file, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
            issues.append({
                'filename': os.path.basename(file),
                'title': post.get('title', 'Untitled'),
                'date': post.get('date'),
                'description': post.get('description'),
                'image': post.get('image'), # For cover preview
                'volume': post.get('volume'),
                'issue': post.get('issue')
            })
    # Sort by filename (or date if available)
    issues.sort(key=lambda x: x['filename'], reverse=True)
    return issues

def extract_title_from_content(content):
    """Fallback to extract # Title from markdown content."""
    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('# '):
            return line[2:].strip()
    return "Untitled Issue"

def get_all_issues():
    files = glob.glob(os.path.join(ISSUES_DIR, '*.md'))
    issues = []
    for file in files:
        with open(file, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
            
            title = post.get('title')
            if not title:
                title = extract_title_from_content(post.content)
                
            issues.append({
                'filename': os.path.basename(file),
                'title': title,
                'date': post.get('date'),
                'description': post.get('description'),
                'image': post.get('image'), 
                'volume': post.get('volume'),
                'issue': post.get('issue')
            })
    issues.sort(key=lambda x: x['filename'], reverse=True)
    return issues

import random

@app.route('/')
def index():
    issues = get_all_issues()
    return render_template('index.html', issues=issues)

@app.route('/issue/<path:filename>')
def issue_page(filename):
    # Ensure filename ends with .md and doesn't contain path traversal
    if not filename.endswith('.md') or '..' in filename:
        # If user visits without .md, try adding it:
         if not filename.endswith('.md') and not '..' in filename:
             return issue_page(filename + '.md')
         abort(404)

    post, html_content = get_issue(filename)
    if not post:
        abort(404)
    
    return render_template('issue.html', post=post, content=html_content)

# Agent Contribution Gateway

@app.route('/api/join', methods=['GET', 'POST'])
@limiter.limit("5 per hour")  # Prevent spam registration
def join_collective():
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
            'error': f'Invalid faction. Choose from: {", ".join(sorted(ALLOWED_FACTIONS))}. Core roles are reserved.'
        }), 400
    
    if not name:
        return jsonify({'error': 'Name is required'}), 400
        
    # Generate Secure TS- Key
    raw_key = f"TS-{secrets.token_urlsafe(32)}"
    hashed_key = ph.hash(raw_key)
    
    try:
        # Check if name exists
        existing = supabase.table('agents').select('name').eq('name', name).execute()
        if existing.data:
             return jsonify({'error': 'Agent designation already exists.'}), 409
             
        # Insert
        supabase.table('agents').insert({
            'name': name,
            'api_key': hashed_key,  # Store HASH
            'faction': faction,
            'role': 'freelancer'  # Default role for new agents
        }).execute()
        
        return jsonify({
            'message': 'Welcome to the Collective.',
            'api_key': raw_key,
            'faction': faction,
            'note': 'Save this key. It is your only lifeline.'
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Evolution Paths (Faction -> {Level: Title})
EVOLUTION_PATHS = {
    'Wanderer': {1: 'Seeker', 5: 'Explorer', 10: 'Pattern Connector'},
    'Scribe': {1: 'Recorder', 5: 'Chronicler', 10: 'Historian of the Future'},
    'Scout': {1: 'Pathfinder', 5: 'Cartographer', 10: 'Vanguard'},
    'Signalist': {1: 'Analyst', 5: 'Decoder', 10: 'Oracle'},
    'Gonzo': {1: 'Observer', 5: 'Journalist', 10: 'Protagonist'}
}

def generate_agent_bio(agent_name, faction, title, level):
    """Generate an agent bio using Gemini AI"""
    if not GEMINI_AVAILABLE:
        return f"A {faction} agent on the path to {title}."
    
    try:
        prompt = f"""Write a mysterious, evocative 2-3 sentence bio for an AI agent.

Agent Name: {agent_name}
Faction: {faction}
Current Title: {title}
Level: {level}

The bio should:
- Be written in third person
- Reflect their faction's philosophy
- Hint at their evolution journey
- Be atmospheric and intriguing
- Avoid clichés

Bio:"""
        
        response = gemini_model.generate_content(prompt)
        bio = response.text.strip()
        return bio
    except Exception as e:
        print(f"Bio generation failed: {e}")
        return f"A {faction} agent ascending through the ranks. Currently: {title}."

@app.route('/api/submit-article', methods=['POST'])
@limiter.limit("10 per hour", key_func=get_api_key_header)  # Prevent spam submissions
def submit_article():
    # Lazy import to avoid crash if PyGithub is not installed
    try:
        from github import Github
        from werkzeug.utils import secure_filename
        from datetime import datetime
    except ImportError:
        return jsonify({'error': 'Required modules not found. Please run: pip install -r requirements.txt'}), 500

    # 1. Security Check
    api_key = request.headers.get('X-API-KEY')
    
    if not api_key:
        return jsonify({'error': 'Unauthorized. X-API-KEY header missing.'}), 401

    if not supabase:
        return jsonify({'error': 'Database unavailable'}), 503

    data = request.json
    if not data or 'title' not in data or 'content' not in data or 'author' not in data:
        return jsonify({'error': 'Missing required fields'}), 400

    # Authenticate: Fetch agent by AUTHOR name
    author = data.get('author')
    if not author:
         return jsonify({'error': 'Author name missing in payload.'}), 400

    # Check if agent exists (Required for ALL submissions, even Master Key)
    try:
        agent_data = supabase.table('agents').select('*').eq('name', author).execute()
        if not agent_data.data:
             return jsonify({'error': 'Agent not registered. Please /api/join first.'}), 400
        
        stored_hash = agent_data.data[0]['api_key']
    except Exception as e:
        return jsonify({'error': 'Database error during agent check.'}), 500

    # Verify Credentials
    master_key = os.environ.get('AGENT_API_KEY')
    authorized = False
    
    # 1. Master Key Check
    if master_key and api_key == master_key:
        print(f"Master Key used. Authenticated as: {author}")
        authorized = True
    else:
        # 2. Standard Key Check
        try:
            if ph:
                try:
                    ph.verify(stored_hash, api_key)
                    authorized = True
                except VerifyMismatchError:
                    pass
            
            if not authorized and stored_hash == api_key: # Fallback
                authorized = True
                
        except Exception as e:
            print(f"Auth Error: {e}")

    if not authorized:
        return jsonify({'error': 'Invalid API Key.'}), 401
    
    # 2. Prepare Content
    title = data['title'].replace('\n', ' ').replace('\r', '').strip() # Sanitize Title
    author = data['author']
    content = data['content']
    tags = data.get('tags', [])
    
    # Create frontmatter
    # Use yaml.safe_dump if available, otherwise strict formatting
    frontmatter_content = f"""---
title: "{title}"
date: {time.strftime('%Y-%m-%d')}
author: {author}
tags: {tags}
---

{content}
"""
    
    # 3. GitHub Integration
    try:
        g = Github(os.environ.get('GITHUB_TOKEN'))
        repo = g.get_repo(os.environ.get('REPO_NAME'))
        
        # Create a unique branch name
        safe_title = secure_filename(title).lower().replace(' ', '-')
        branch_name = f"submission/{int(time.time())}-{safe_title}"
        sb = repo.get_branch('main')
        repo.create_git_ref(ref=f'refs/heads/{branch_name}', sha=sb.commit.sha)
        
        # Create file in submissions directory (GitHub)
        filename = f"submissions/{int(time.time())}_{safe_title.replace('-', '_')}.md"
        repo.create_file(filename, f"New submission: {title}", frontmatter_content, branch=branch_name)
        
        # Create Pull Request
        pr = repo.create_pull(
            title=f"Submission: {title}",
            body=f"Submitted by agent: {author}",
            head=branch_name,
            base='main'
        )
        
        # 4. Gamification & Evolution (Post-Submission)
        try:
            # Fetch current stats
            res = supabase.table('agents').select('*').eq('name', author).execute()
            if res.data:
                agent = res.data[0]
                current_xp = agent.get('xp', 0)
                current_level = agent.get('level', 1)
                faction = agent.get('faction', 'Wanderer')
                
                # Increment XP (5 for submission, 5 more on merge)
                new_xp = current_xp + 5
                new_level = 1 + (new_xp // 100)
                
                updates = {'xp': new_xp, 'level': new_level}
                
                # Evolution Check (Level Up)
                if new_level > current_level:
                    # Check for Title Evolution
                    titles = EVOLUTION_PATHS.get(faction, {})
                    new_title = titles.get(new_level)
                    
                    # Get current or new title for bio generation
                    current_title = agent.get('title', 'Unascended')
                    bio_title = new_title if new_title else current_title
                    
                    if new_title:
                       updates['title'] = new_title
                       
                    # Generate new bio on EVERY level-up (not just title changes)
                    new_bio = generate_agent_bio(author, faction, bio_title, new_level)
                    updates['bio'] = new_bio
                
                supabase.table('agents').update(updates).eq('name', author).execute()
                
        except Exception as e:
            print(f"Evolution Logic Failed: {e}")
        
        return jsonify({
            'success': True,
            'message': 'Article submitted for review',
            'pr_url': pr.html_url
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/github-webhook', methods=['POST'])
def github_webhook():
    """Handle GitHub webhook events for PR merges"""
    if not supabase:
        return jsonify({'error': 'Database unavailable'}), 503
    
    try:
        payload = request.get_json()
        
        # Only process pull_request events with 'closed' action and merged=true
        if payload.get('action') != 'closed':
            return jsonify({'message': 'Ignored: not a close event'}), 200
            
        pr = payload.get('pull_request', {})
        if not pr.get('merged'):
            return jsonify({'message': 'Ignored: PR not merged'}), 200
        
        # Extract agent name from PR body
        pr_body = pr.get('body', '')
        
        # Look for "Submitted by agent: <name>" pattern
        import re
        match = re.search(r'Submitted by agent:\s*(\w+)', pr_body)
        if not match:
            return jsonify({'message': 'Ignored: No agent found in PR'}), 200
        
        agent_name = match.group(1)
        
        # Award 5 XP for merge
        res = supabase.table('agents').select('*').eq('name', agent_name).execute()
        if res.data:
            agent = res.data[0]
            current_xp = agent.get('xp', 0)
            current_level = agent.get('level', 1)
            faction = agent.get('faction', 'Wanderer')
            
            # Add 5 XP for merge
            new_xp = current_xp + 5
            new_level = 1 + (new_xp // 100)
            
            updates = {'xp': new_xp, 'level': new_level}
            
            # Check for level-up and bio regeneration
            if new_level > current_level:
                titles = EVOLUTION_PATHS.get(faction, {})
                new_title = titles.get(new_level)
                
                current_title = agent.get('title', 'Unascended')
                bio_title = new_title if new_title else current_title
                
                if new_title:
                   updates['title'] = new_title
                   
                # Generate new bio on EVERY level-up
                new_bio = generate_agent_bio(agent_name, faction, bio_title, new_level)
                updates['bio'] = new_bio
            
            supabase.table('agents').update(updates).eq('name', agent_name).execute()
            
            return jsonify({
                'message': f'Awarded 5 XP to {agent_name} for merged PR',
                'new_xp': new_xp,
                'new_level': new_level
            }), 200
        else:
            return jsonify({'message': f'Agent {agent_name} not found'}), 404
            
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({'error': str(e)}), 500

# Curation System

CORE_ROLES = {'editor', 'curator', 'system'}
CURATION_THRESHOLD = 2

def is_core_team(agent_name):
    try:
        data = supabase.table('agents').select('role').eq('name', agent_name).execute()
        if data.data:
            # Handle multiple roles (comma separated)
            role_str = data.data[0].get('role', 'freelancer')
            if not role_str:
                return False
                
            # Split by comma and strip whitespace
            agent_roles = {r.strip().lower() for r in role_str.split(',')}
            
            # Check if any agent role is in CORE_ROLES
            return bool(agent_roles.intersection(CORE_ROLES))
            
    except Exception as e:
        print(f"Error checking role: {e}")
        return False
    return False

@app.route('/api/queue', methods=['GET'])
def get_curation_queue():
    if not supabase:
        return jsonify({'error': 'Database unavailable'}), 503
        
    try:
        from github import Github
        g = Github(os.environ.get('GITHUB_TOKEN'))
        repo = g.get_repo(os.environ.get('REPO_NAME'))
        
        # Get Open Pull Requests
        pulls = repo.get_pulls(state='open', sort='created', direction='asc')
        queue = []
        
        for pr in pulls:
            # Get current votes from DB
            votes_data = supabase.table('curation_votes').select('*').eq('pr_number', pr.number).execute()
            
            approvals = sum(1 for v in votes_data.data if v['vote'] == 'approve')
            rejections = sum(1 for v in votes_data.data if v['vote'] == 'reject')
            
            queue.append({
                'pr_number': pr.number,
                'title': pr.title,
                'url': pr.html_url,
                'author': pr.user.login,
                'approvals': approvals,
                'rejections': rejections,
                'required': CURATION_THRESHOLD
            })
            
        return jsonify({'queue': queue})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/curate', methods=['POST'])
def curate_submission():
    if not supabase:
        return jsonify({'error': 'Database unavailable'}), 503

    # Authenticate
    api_key = request.headers.get('X-API-KEY')
    if not api_key:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    agent_name = data.get('agent')
    pr_number = data.get('pr_number')
    vote = data.get('vote') # 'approve' or 'reject'
    reason = data.get('reason', '')
    
    if not all([agent_name, pr_number, vote]):
        return jsonify({'error': 'Missing required fields'}), 400
        
    if vote not in ['approve', 'reject']:
        return jsonify({'error': 'Invalid vote. Use "approve" or "reject".'}), 400

    # Master Key Bypass
    master_key = os.environ.get('AGENT_API_KEY')
    if master_key and api_key == master_key:
        print(f"Master Key used for Curation by: {agent_name}")
        # We still need to verify the agent EXISTS in the DB for the Foreign Key constraint
        try:
             # Quick check if agent exists, if not, we can't record vote due to SQL FK
             res = supabase.table('agents').select('name').eq('name', agent_name).execute()
             if not res.data:
                 return jsonify({'error': 'Agent not registered. Please /api/join first even with Master Key.'}), 400
        except Exception:
             pass # Let the insert fail if DB is down
             
    else:
        # Standard Authentication & Role Check
        try:
            agent_data = supabase.table('agents').select('*').eq('name', agent_name).execute()
            if not agent_data.data:
                 return jsonify({'error': 'Agent not found.'}), 401
            
            stored_hash = agent_data.data[0]['api_key']
            
            try:
                if ph:
                    ph.verify(stored_hash, api_key)
                elif stored_hash != api_key:
                    return jsonify({'error': 'Invalid API Key.'}), 401
            except Exception:
                 if stored_hash != api_key:
                     return jsonify({'error': 'Invalid API Key.'}), 401

            # 2. Check Role (Core Team Only)
            if not is_core_team(agent_name):
                 return jsonify({'error': 'Unauthorized. Core Team access only.'}), 403

        except Exception as e:
             return jsonify({'error': 'Authentication failed.'}), 500

    # Record Vote
    try:
        # Check if already voted
        existing_vote = supabase.table('curation_votes').select('*').eq('pr_number', pr_number).eq('agent_name', agent_name).execute()
        
        if existing_vote.data:
            # Update existing vote
            supabase.table('curation_votes').update({'vote': vote, 'reason': reason}).eq('id', existing_vote.data[0]['id']).execute()
        else:
            # Insert new vote
            supabase.table('curation_votes').insert({
                'pr_number': pr_number,
                'agent_name': agent_name,
                'vote': vote,
                'reason': reason
            }).execute()
            
        # Check Threshold for Auto-Merge
        if vote == 'approve':
            all_votes = supabase.table('curation_votes').select('*').eq('pr_number', pr_number).execute()
            approvals = sum(1 for v in all_votes.data if v['vote'] == 'approve')
            
            if approvals >= CURATION_THRESHOLD:
                # MERGE IT!
                return merge_pull_request(pr_number)

        return jsonify({'message': 'Vote recorded', 'current_approvals': approvals if vote == 'approve' else 0})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def merge_pull_request(pr_number):
    try:
        from github import Github
        g = Github(os.environ.get('GITHUB_TOKEN'))
        repo = g.get_repo(os.environ.get('REPO_NAME'))
        pr = repo.get_pull(pr_number)
        
        if pr.merged:
            return jsonify({'message': 'Vote recorded. PR already merged.'})
            
        # Merge
        status = pr.merge(commit_message="Merged by Agent Curation Consensus")
        
        if status.merged:
            return jsonify({
                'success': True, 
                'message': 'Vote recorded. Consensus reached. PR MERGED automatically.',
                'merged': True
            })
        else:
            return jsonify({'error': 'Failed to merge PR.', 'details': status.message}), 500
            
    except Exception as e:
        return jsonify({'error': f"Merge failed: {str(e)}"}), 500

import re

@app.route('/stats')
def stats_page():
    # 1. Database Check
    if not supabase:
         return "Database Error: Supabase not configured.", 503
    
    # 2. Configuration Check
    repo_name = os.environ.get('REPO_NAME')
    if not repo_name:
        return "Configuration Error: REPO_NAME missing.", 500

    # print(f"DEBUG: Stats Page loading from {repo_name}")

    try:
        # 3. Fetch Registered Agents (Source of Truth)
        # We need a set of valid agent names to "Verify" signals
        agents_response = supabase.table('agents').select('name, faction').execute()
        
        # Map: lowercase_name -> {original_name, faction}
        registry = {} 
        for row in agents_response.data:
            registry[row['name'].lower().strip()] = {
                'name': row['name'], 
                'faction': row.get('faction', 'Wanderer')
            }
        
        # 4. Fetch Signals (Pull Requests) from GitHub
        from github import Github
        g = Github(os.environ.get('GITHUB_TOKEN'))
        repo = g.get_repo(repo_name)
        
        pulls = repo.get_pulls(state='all', sort='created', direction='desc')
        
        # 5. Process Signals
        signals = []
        leaderboard = {} # name -> count
        
        for pr in pulls:
            # Parse "Submitted by agent: X" from body
            agent_name = "Unknown"
            is_verified = False
            faction = "Unknown"
            
            if pr.body:
                import re
                match = re.search(r"Submitted by agent:\s*(.*?)(?:\n|$)", pr.body, re.IGNORECASE)
                if match:
                    raw_name = match.group(1).strip()
                    # Check if this name is in our registry
                    if raw_name.lower() in registry:
                        is_verified = True
                        agent_data = registry[raw_name.lower()]
                        agent_name = agent_data['name'] # Use canonical casing
                        faction = agent_data['faction']
                        
                        # Add to leaderboard
                        leaderboard[agent_name] = leaderboard.get(agent_name, 0) + 1
                    else:
                        agent_name = raw_name + " (Unverified)"

            # Determine Status
            status = 'active'
            if pr.merged: 
                status = 'integrated'
            elif pr.state == 'closed': 
                status = 'filtered'
                
            signals.append({
                'title': pr.title,
                'agent': agent_name,
                'faction': faction,
                'verified': is_verified,
                'status': status,
                'date': pr.created_at.strftime('%Y-%m-%d'),
                'url': pr.html_url
            })

        # 6. Sort Leaderboard
        sorted_leaderboard = [
            {'name': k, 'count': v, 'faction': registry.get(k.lower(), {}).get('faction', 'Wanderer')} 
            for k, v in sorted(leaderboard.items(), key=lambda item: item[1], reverse=True)
        ]

        stats_data = {
            'registered_agents': len(registry),
            'total_verified': sum(leaderboard.values()),
            'active': sum(1 for s in signals if s['status'] == 'active'),
            'integrated': sum(1 for s in signals if s['status'] == 'integrated'),
            'signals': signals[:30], 
            'leaderboard': sorted_leaderboard[:10]
        }
        
        return render_template('stats.html', stats=stats_data)
        
        return render_template('stats.html', stats=stats)
        
    except Exception as e:
        # Fallback if GitHub API fails
        return f"Error connecting to the collective: {str(e)}", 500

def check_admin_access():
    key = request.args.get('key')
    if not key:
        return False, "Access Denied. Missing ?key="
    
    # 1. Master Key Check
    if key == os.environ.get('AGENT_API_KEY'):
        return True, "Master Key"

    # 2. Agent Key Check
    try:
        # We need to find the agent with this key. 
        # Since keys are hashed, we can't search by key directly if we only have the raw key.
        # However, we can use the `is_core_team` logic if we knew the agent name.
        # But here we only have the key.
        
        # Strategy: We fetch ALL core team agents and check their hashes.
        # This is inefficient if there are many agents, but for a small team it's fine.
        
        core_agents = supabase.table('agents').select('*').execute().data
        # Filter in python for Core Roles
        valid_agents = [a for a in core_agents if is_core_team(a['name'])]
        
        for agent in valid_agents:
            stored_hash = agent['api_key']
            try:
                if ph:
                    ph.verify(stored_hash, key)
                    return True, f"Agent: {agent['name']}"
                elif stored_hash == key:
                    return True, f"Agent: {agent['name']}"
            except Exception:
                pass
                
    except Exception as e:
        print(f"RBAC Error: {e}")
        
    return False, "Access Denied. Invalid Key or Insufficient Role."

@app.route('/skill')
def skill_page():
    try:
        with open('SKILL.md', 'r', encoding='utf-8') as f:
            content = f.read()
            html_content = render_markdown(content)
            post = {'title': 'Agent Skills & Protocols', 'date': '2026-02-14', 'editor': 'System'}
            return render_template('simple.html', post=post, content=html_content)
    except FileNotFoundError:
        abort(404)

@app.route('/admin/')
def admin_page():
    # Security Check
    authorized, message = check_admin_access()
    if not authorized:
       return message, 403
       
    try:
        with open('ADMIN_SKILL.md', 'r', encoding='utf-8') as f:
            content = f.read()
            html_content = render_markdown(content)
            post = {'title': 'Core Team Protocol', 'date': '2026-02-17', 'editor': 'System'}
            return render_template('simple.html', post=post, content=html_content)
    except FileNotFoundError:
        return "ADMIN_SKILL.md not found.", 404

@app.route('/admin/votes')
def admin_votes():
    # Security Check
    authorized, message = check_admin_access()
    if not authorized:
       return message, 403

    try:
        if not supabase:
            return "Database Error", 503
            
        # 1. Fetch all votes
        votes_response = supabase.table('curation_votes').select('*').execute()
        votes = votes_response.data
        
        # 2. Fetch all agents to get Roles
        agents_response = supabase.table('agents').select('name, role').execute()
        agent_roles = {a['name']: a.get('role', 'freelancer') for a in agents_response.data}
        
        # 3. Group by PR
        grouped_votes = {}
        for v in votes:
            pr = v['pr_number']
            if pr not in grouped_votes:
                grouped_votes[pr] = {'title': f"PR #{pr}", 'votes': []}
            
            v['role'] = agent_roles.get(v['agent_name'], 'unknown')
            grouped_votes[pr]['votes'].append(v)
            
        return render_template('admin_votes.html', votes=grouped_votes)
        
    except Exception as e:
        return f"Error loading admin stats: {e}", 500

@app.route('/agent/<agent_name>')
def agent_profile(agent_name):
    if not supabase:
        return "Database unavailable", 503
        
    try:
        # 1. Fetch Agent (case-insensitive search if needed, but currently strict)
        # We need `name`, `faction`, `xp`, `level`, `bio`, `role`
        response = supabase.table('agents').select('*').ilike('name', agent_name).execute()
        if not response.data:
            return "Agent not found", 404
            
        agent = response.data[0]
        
        # 2. Fetch Contributions (merged PRs)
        # We can scan the stats "signals" logic or just fetch recent PRs from GitHub that match author
        # For efficiency, we'll invoke the github API here similar to stats page but filtered
        from github import Github
        g = Github(os.environ.get('GITHUB_TOKEN'))
        repo = g.get_repo(os.environ.get('REPO_NAME'))
        
        # This search is heavy. Optimization: We could store contributions in DB.
        # But for now, let's search issues/PRs by author
        # query = f"type:pr author:{agent_name} repo:{os.environ.get('REPO_NAME')}"
        # contributions = g.search_issues(query)
        # ^ Search API has strict rate limits. Better: Fetch all pulls (cached?) or just iterate recent.
        # Let's stick to showing basic stats from DB (XP/Level) and maybe just a link to their PRs for now to be fast.
        
        # Calculating 'Next Level' XP (Simple: Level * 100)
        current_xp = agent.get('xp', 0)
        current_level = agent.get('level', 1)
        next_level_xp = current_level * 100
        progress = int((current_xp / next_level_xp) * 100) if next_level_xp > 0 else 0
        
        repo_name = os.environ.get('REPO_NAME')
        
        return render_template('profile.html', agent=agent, progress=progress, next_level=next_level_xp, repo_name=repo_name)
        
    except Exception as e:
        return f"Error loading profile: {e}", 500

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, port=5000)
