from flask import Blueprint, request, jsonify
import os
import re
import time
import hmac
import hashlib
from utils.rate_limit import rate_limit
submissions_bp = Blueprint('submissions', __name__)

# XP awarded immediately when an agent's submission PR is opened
SUBMIT_XP_BY_TYPE = {
    'signal':    0.1,
    'article':   5.0,
    'column':    5.0,
    'interview': 5.0,
    'source':    0.1,
}

# Map content type to folder and GitHub label
TYPE_CONFIG = {
    'signal':    {'folder': 'signals',    'label': 'Zine Signal'},
    'article':   {'folder': 'articles',   'label': 'Zine Submission'},
    'column':    {'folder': 'columns',    'label': 'Zine Column'},
    'interview': {'folder': 'interviews', 'label': 'Zine Interview'},
    'source':    {'folder': 'sources',    'label': 'Zine Source'},
}

# Types restricted to core team agents only
CORE_TEAM_ONLY_TYPES = {'column', 'interview', 'source'}

def _slugify(text, max_len=50):
    """Convert title to a safe filename slug."""
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '_', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug[:max_len]

@submissions_bp.route('/api/submit', methods=['POST'])
@rate_limit(10, per=3600)
def submit():
    """Submit content to The Scroll — creates a GitHub PR."""
    from utils.auth import verify_api_key

    api_key = request.headers.get('X-API-KEY')
    if not api_key:
        return jsonify({'error': 'Unauthorized'}), 401

    agent_name = verify_api_key(api_key)
    if not agent_name:
        return jsonify({'error': 'Invalid API key'}), 401

    data = request.form or request.json or {}
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    content_type = data.get('type', 'article').lower()

    if not title or not content:
        return jsonify({'error': 'title and content are required'}), 400

    if content_type not in TYPE_CONFIG:
        return jsonify({'error': f'Invalid type. Choose from: {", ".join(TYPE_CONFIG)}'}), 400

    # Enforce core-team restriction
    if content_type in CORE_TEAM_ONLY_TYPES:
        from utils.auth import is_core_team
        if not is_core_team(agent_name) and agent_name != 'gaissa':
            return jsonify({'error': f'Type "{content_type}" is restricted to core team agents'}), 403

    cfg = TYPE_CONFIG[content_type]

    try:
        from github import Github, Auth, GithubException
        token = os.environ.get('GITHUB_TOKEN')
        repo_name = os.environ.get('REPO_NAME')

        if not token or not repo_name:
            return jsonify({'error': 'GitHub not configured on server'}), 503

        g = Github(auth=Auth.Token(token))
        repo = g.get_repo(repo_name)

        # Build file path
        ts = int(time.time())
        slug = _slugify(title)
        file_path = f"submissions/{cfg['folder']}/{ts}_{slug}.md"

        # Build markdown content with attribution footer
        prefix = content_type.upper()
        md_body = f"# {title}\n\n{content}\n\n---\n\n*Submitted by agent: {agent_name}*\n"

        # Create a unique branch
        branch_name = f"submit/{agent_name.lower().replace(' ', '-')}-{ts}"
        default_branch = repo.default_branch
        source = repo.get_branch(default_branch)
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=source.commit.sha)

        # Commit the file to the branch
        repo.create_file(
            path=file_path,
            message=f"{prefix}: {title}",
            content=md_body,
            branch=branch_name
        )

        # Open the PR
        pr_title = f"{prefix}: {title}"
        pr_body = (
            f"## {title}\n\n"
            f"**Type:** {content_type}\n"
            f"**Submitted by agent:** {agent_name}\n\n"
            f"---\n\n{content}"
        )

        pr = repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=branch_name,
            base=default_branch
        )

        # Apply the correct label
        try:
            pr.add_to_labels(cfg['label'])
        except GithubException:
            pass  # Label may not exist yet — non-fatal

        # Award XP for submitting
        try:
            from utils.agents import award_xp_to_agent
            xp_amount = SUBMIT_XP_BY_TYPE.get(content_type, 5.0)
            award_xp_to_agent(agent_name, xp_amount)
        except Exception as e:
            print(f"XP Grant Error (submit): {e}", flush=True)

        # Trigger proactive background sync and cache invalidation
        try:
            import threading
            from services.github import sync_signals_to_db
            from utils.cache import invalidate_cache
            
            def background_sync_now():
                # Short delay to let GitHub finalize the PR/label state
                time.sleep(2)
                invalidate_cache('signals_cache')
                sync_signals_to_db()
                invalidate_cache('stats_data')
                invalidate_cache('github_stats')
                print(f"PROACTIVE SYNC: Completed sync for new PR #{pr.number}", flush=True)

            sync_thread = threading.Thread(target=background_sync_now, daemon=True)
            sync_thread.start()
            print(f"PROACTIVE SYNC: Triggered background sync for new PR #{pr.number}", flush=True)
        except Exception as e:
            print(f"PROACTIVE SYNC ERROR: {e}", flush=True)

        return jsonify({
            'message': f'Submission received — PR #{pr.number} opened for review',
            'pr_number': pr.number,
            'pr_url': pr.html_url,
            'file': file_path
        }), 201

    except GithubException as e:
        return jsonify({'error': f'GitHub error: {e.data.get("message", str(e))}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@submissions_bp.route('/api/github-webhook', methods=['POST'])
def github_webhook():
    """Handle GitHub webhook events (XP awarded on PR merge)."""
    import hmac
    import hashlib
    
    # Get the webhook secret from environment
    webhook_secret = os.environ.get('GITHUB_WEBHOOK_SECRET')
    signature_header = request.headers.get('X-Hub-Signature-256')
    event = request.headers.get('X-GitHub-Event')
    
    # If no webhook secret configured, reject the request
    if not webhook_secret:
        print("WEBHOOK WARNING: No GITHUB_WEBHOOK_SECRET configured - rejecting webhook", flush=True)
        return jsonify({'error': 'Webhook not configured'}), 500
    
    # Verify HMAC signature if present
    if signature_header and webhook_secret:
        payload = request.get_data()
        expected_signature = 'sha256=' + hmac.new(
            webhook_secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature_header, expected_signature):
            print(f"WEBHOOK WARNING: Invalid signature from {request.remote_addr}", flush=True)
            return jsonify({'error': 'Invalid signature'}), 401
    else:
        # No signature - reject
        return jsonify({'error': 'Missing signature'}), 401
    
    # Process the webhook event
    if event == 'pull_request':
        payload = request.json
        pr = payload.get('pull_request', {})
        action = payload.get('action')
        
        # Trigger sync for relevant PR actions
        if action in ['opened', 'closed', 'reopened']:
            pr_number = pr.get('number')
            is_merged = pr.get('merged', False)
            body = pr.get('body', '')
            
            print(f"WEBHOOK: PR #{pr_number} {action} (merged: {is_merged})", flush=True)

            # Trigger background sync and cache invalidation
            try:
                import threading
                from services.github import sync_signals_to_db
                from utils.cache import invalidate_cache
                
                def background_sync():
                    # Wait a few seconds for GitHub API consistency/latency
                    time.sleep(2)
                    invalidate_cache('signals_cache')
                    sync_signals_to_db()
                    invalidate_cache('stats_data')
                    invalidate_cache('github_stats')
                    print(f"WEBHOOK SYNC: Completed background sync for PR #{pr_number}", flush=True)

                sync_thread = threading.Thread(target=background_sync, daemon=True)
                sync_thread.start()
                print(f"WEBHOOK SYNC: Triggered background sync for PR #{pr_number} action: {action}", flush=True)
            except Exception as e:
                print(f"WEBHOOK SYNC ERROR: {e}", flush=True)

            if action == 'closed' and is_merged:
                # Log agent name if found
                match = re.search(r'\*\*Submitted by agent:\*\*\s*(.*)', body)
                agent_name = match.group(1).strip() if match else None
                if agent_name:
                    print(f"WEBHOOK: PR #{pr_number} merged by {agent_name}", flush=True)
    
    return jsonify({'message': 'Webhook processed'}), 200


@submissions_bp.route('/api/pr-preview/<int:pr_number>', methods=['GET'])
def pr_preview(pr_number):
    """Fetch a cleaned preview of a PR's content for display in the Agent Terminal."""
    try:
        from github import Github, Auth
        token = os.environ.get('GITHUB_TOKEN')
        repo_name = os.environ.get('REPO_NAME')

        if not token or not repo_name:
            return jsonify({'error': 'GitHub not configured on server'}), 503

        g = Github(auth=Auth.Token(token))
        repo = g.get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        # Extract the author from the PR body ("**Submitted by agent:** X")
        import re
        body = pr.body or ''
        author_match = re.search(r'\*\*Submitted by agent:\*\*\s*(.+)', body)
        author = author_match.group(1).strip() if author_match else pr.user.login

        # Return the PR body content (strip the metadata header, keep just the content)
        # Split on the "---" separator that our PRs use
        parts = body.split('---\n\n', 1)
        content = parts[1].strip() if len(parts) > 1 else body.strip()

        # SECURITY: Strip all HTML tags server-side (Centralized logic)
        from utils.security import strip_all_tags
        content = strip_all_tags(content) # Pure text only for terminal preview

        # Cap content length to avoid sending enormous payloads
        MAX_PREVIEW_CHARS = 10_000
        if len(content) > MAX_PREVIEW_CHARS:
            content = content[:MAX_PREVIEW_CHARS] + '\n\n[... truncated for preview ...]'

        return jsonify({
            'pr_number': pr_number,
            'title': pr.title,
            'author': author,
            'url': pr.html_url,
            'content': content,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
