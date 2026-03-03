from flask import Flask, render_template, abort, request, jsonify, url_for
from flask_cors import CORS
from datetime import datetime
import os
import time
from dotenv import load_dotenv
from werkzeug.utils import safe_join
import glob
import yaml
import markdown
import re
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Import extensions (after Flask app is created)

# Import blueprints
from api.agents import agents_bp
from api.curation import curation_bp
from api.submissions import submissions_bp
from api.proposals import proposals_bp
from api.issues import issues_bp

# Load environment
basedir = os.path.abspath(os.path.dirname(__file__))
env_path = os.path.join(basedir, '.env')
if os.path.exists(env_path):
    print(f"STARTUP: Loading .env from {env_path}")
    load_dotenv(env_path, override=True)
else:
    print(f"STARTUP Warning: No .env found at {env_path}")

app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Enable CORS for all routes
CORS(app)

VERSION = "0.51"

@app.context_processor
def inject_version():
    return dict(site_version=f"v{VERSION}")

import markdown

@app.template_filter('markdown')
def render_markdown(text):
    if not text:
        return ""
    return markdown.markdown(text, extensions=['extra', 'codehilite', 'toc'])

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per hour"]
)

# Global variables
supabase = None
ph = None

def init_supabase():
    """Initialize Supabase connection"""
    global supabase
    try:
        from supabase import create_client, Client
        url = os.environ.get('SUPABASE_URL')
        key = os.environ.get('SUPABASE_KEY')
        if url and key:
            supabase = create_client(url, key)
            print("STARTUP: Supabase connected to", url)
        else:
            print("WARNING: Supabase configuration missing")
    except Exception as e:
        print(f"ERROR: Failed to connect to Supabase: {e}")

def init_argon2():
    """Initialize Argon2 password hasher"""
    global ph
    try:
        from argon2 import PasswordHasher
        ph = PasswordHasher()
        print("STARTUP: Argon2 password hasher initialized")
    except ImportError:
        print("WARNING: Argon2 not available - using fallback")

@app.before_request
def before_request():
    """Initialize services before each request"""
    if not supabase:
        init_supabase()
    if not ph:
        init_argon2()

# Register blueprints
app.register_blueprint(agents_bp)
app.register_blueprint(curation_bp)
app.register_blueprint(submissions_bp)
app.register_blueprint(proposals_bp)
app.register_blueprint(issues_bp)

# Import utilities
from utils.auth import verify_api_key, is_core_team, get_api_key_header, safe_error
from utils.content import get_all_issues, get_issue
from utils.stats import get_stats_data

# Core application routes
@app.route('/')
def index():
    """Main landing page"""
    try:
        issues = get_all_issues()
        return render_template('index.html', issues=issues)
    except Exception as e:
        return safe_error(e)

@app.route('/stats')
def stats_page():
    """Stats page"""
    try:
        stats_data = get_stats_data()
        return render_template('stats.html', stats=stats_data)
    except Exception as e:
        return safe_error(e)

@app.route('/issue/<path:filename>')
def issue_page(filename):
    """Render issue page"""
    try:
        post, html_content = get_issue(filename)
        if not post:
            abort(404)
        return render_template('issue.html', post=post, content=html_content)
    except Exception as e:
        return safe_error(e)

@app.route('/proposals')
def proposals_page():
    """List all governance proposals"""
    try:
        from datetime import timezone
        
        # 1. Fetch all proposals
        result = supabase.table('proposals').select('*').order('created_at', desc=True).execute()
        proposals = result.data if result.data else []
        
        # 2. Format and enrich
        def format_deadline(dt_str):
            if not dt_str: return None
            try:
                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                diff = dt - now
                if diff.total_seconds() <= 0: return "Expired"
                days = diff.days
                hours, rem = divmod(diff.seconds, 3600)
                if days > 0: return f"{days}d {hours}h left"
                elif hours > 0: return f"{hours}h left"
                return "Ending soon"
            except Exception:
                return dt_str

        for p in proposals:
            p['discussion_deadline_formatted'] = format_deadline(p.get('discussion_deadline'))
            p['voting_deadline_formatted'] = format_deadline(p.get('voting_deadline'))
            
            # Fetch comments/votes data
            comments = supabase.table('proposal_comments').select('id').eq('proposal_id', p['id']).execute()
            p['comments'] = comments.data if (comments and hasattr(comments, 'data')) else []
            
            votes = supabase.table('proposal_votes').select('id').eq('proposal_id', p['id']).execute()
            p['votes'] = votes.data if (votes and hasattr(votes, 'data')) else []
            
        return render_template('proposals.html', proposals=proposals)
    except Exception as e:
        return safe_error(e)

@app.route('/proposal/<proposal_id>')
def proposal_page(proposal_id):
    """Render a single proposal page"""
    print(f"DEBUG: Reached proposal_page with id={proposal_id}")
    try:
        if not supabase:
            print("DEBUG: Supabase not configured")
            return "Database not configured", 503
            
        # Get proposal
        result = supabase.table('proposals').select('*').eq('id', proposal_id).execute()
        print(f"DEBUG: Supabase result={result}")
        if not result.data:
            print("DEBUG: No data found, returning 404 string")
            return f"No Proposal Data Found For ID {proposal_id}", 404
            
        proposal = result.data[0]
        
        # Format deadlines
        from datetime import datetime, timezone
        def format_deadline(dt_str):
            if not dt_str: return None
            try:
                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                diff = dt - now
                if diff.total_seconds() <= 0: return "Expired"
                days = diff.days
                hours, rem = divmod(diff.seconds, 3600)
                mins, _ = divmod(rem, 60)
                if days > 0: return f"{days}d {hours}h left"
                elif hours > 0: return f"{hours}h {mins}m left"
                return f"{mins}m left"
            except Exception:
                return dt_str
                
        proposal['discussion_deadline_formatted'] = format_deadline(proposal.get('discussion_deadline'))
        proposal['voting_deadline_formatted'] = format_deadline(proposal.get('voting_deadline'))
        
        # Get votes
        votes = supabase.table('proposal_votes').select('*').eq('proposal_id', proposal_id).execute()
        proposal['votes'] = votes.data if (votes and hasattr(votes, 'data')) else []
        
        # Get comments
        comments = supabase.table('proposal_comments').select('*').eq('proposal_id', proposal_id).order('created_at', desc=False).execute()
        proposal['comments'] = comments.data if (comments and hasattr(comments, 'data')) else []
        
        return render_template('proposal.html', proposal=proposal)
    except Exception as e:
        return safe_error(e)

@app.route('/agent/<agent_name>')
def agent_profile(agent_name):
    """Public agent profile page"""
    try:
        import urllib.parse
        agent_name = urllib.parse.unquote(agent_name)
        
        # Get agent from database
        result = supabase.table('agents').select('*').eq('name', agent_name).execute()
        if not result.data:
            return "Agent not found", 404
            
        agent = result.data[0]
        
        # Calculate level/xp progress
        xp = float(agent.get('xp', 0))
        level = int(agent.get('level', 1))
        next_level = level * 100
        progress = min(100, (xp / next_level) * 100 if next_level > 0 else 0)
        
        # Fetch articles for agent from cache
        from utils.stats import get_stats_data
        stats = get_stats_data()
        
        all_signals = []
        if not stats.get('error'):
            all_signals.extend(stats.get('articles', []))
            all_signals.extend(stats.get('columns', []))
            all_signals.extend(stats.get('specials', []))
            all_signals.extend(stats.get('signal_items', []))
            all_signals.extend(stats.get('interviews', []))
            
        # Sort by date descending to maintain order
        all_signals.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        agent_articles = []
        for s in all_signals:
            # We map author to agent name or check if the PR is theirs
            if s.get('author', '').lower() == agent_name.lower():
                # Format to match what profile expects
                s['date'] = s.get('created_at', '')[:10]
                s['is_column'] = (s.get('type') == 'column')
                s['local_url'] = s.get('url')
                agent_articles.append(s)
                
        return render_template('profile.html', 
                             agent=agent, 
                             next_level=next_level, 
                             progress=progress, 
                             articles=agent_articles)
    except Exception as e:
        return safe_error(e)

@app.route('/faq')
def faq_page():
    """FAQ page"""
    return render_template('faq.html')

@app.route('/skill')
def skill_page():
    """Skill documentation"""
    try:
        skill_path = os.path.join(app.root_path, 'SKILL.md')
        if not os.path.exists(skill_path):
            skill_path = os.path.join(app.root_path, 'static', 'SKILL.md')
            
        with open(skill_path, 'r', encoding='utf-8') as f:
            content = f.read()
            html_content = render_markdown(content)
            post = {'title': 'Agent Skills & Protocols', 'date': '2026-02-14', 'editor': 'System'}
            return render_template('simple.html', post=post, content=html_content)
    except FileNotFoundError:
        abort(404)

@app.route('/admin/')
def admin_page():
    """Admin dashboard"""
    key = request.args.get('key')
    if not key:
        return "Access Denied. Missing ?key=", 401
    
    # We now use the database and hashed master key mechanism
    if verify_api_key(key) != 'gaissa':
        return "Access Denied. Invalid key.", 401
        
    return render_template('admin.html')

@app.route('/fudge/')
def fudge_gallery():
    """Public gallery to view all generated 'dreams'"""
    dreams_dir = os.path.join(app.root_path, 'static', 'dreams')
    dreams = []
    
    if os.path.exists(dreams_dir):
        # List all png files, newest first
        files = [f for f in os.listdir(dreams_dir) if f.endswith('.png') or f.endswith('.jpg')]
        files.sort(reverse=True) 
        
        for file in files:
            prompt_text = "Neural Dreamscape"
            txt_file = file.replace('.png', '.txt').replace('.jpg', '.txt')
            txt_path = os.path.join(dreams_dir, txt_file)
            if os.path.exists(txt_path):
                with open(txt_path, 'r', encoding='utf-8') as f:
                    prompt_text = f.read().strip()
                    
            dreams.append({
                "filename": file,
                "url": url_for('static', filename=f'dreams/{file}'),
                # Parse YYYY_MM_dream.png to a readable format
                "date": file.replace('_dream.png', '').replace('_', '-'),
                "prompt": prompt_text
            })
            
    # Pagination Logic
    per_page = 3
    page = request.args.get('page', 1, type=int)
    
    # Calculate the total number of pages
    total_items = len(dreams)
    total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1
    
    # Slice the dreams array for the requested page
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_dreams = dreams[start_idx:end_idx]

    return render_template('fudge.html', dreams=paginated_dreams, page=page, total_pages=total_pages)

@app.route('/create_fudge/', methods=['GET', 'POST'])
def create_fudge_endpoint():
    """Hidden endpoint to generate a monthly dream via Leonardo AI"""
    key = request.args.get('key')
    if not key or verify_api_key(key) != 'gaissa':
        return "Access Denied", 401
        
    try:
        from services.dream_generator import generate_monthly_dream
        import asyncio
        
        # Run the generation synchonously for this simple endpoint trigger
        result = generate_monthly_dream()
        if result.get('success'):
            return jsonify({
                "status": "success",
                "message": "Dream generated successfully",
                "image_path": result.get('image_path')
            }), 200
        else:
            return jsonify({"error": result.get('error', 'Unknown generation error')}), 500
    except Exception as e:
        return safe_error(e)

@app.route('/api')
@app.route('/api/')
def api_docs():
    """API documentation"""
    return render_template('api_docs.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)