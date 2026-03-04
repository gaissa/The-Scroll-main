from flask import Blueprint, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import re
import time

limiter = Limiter(key_func=get_remote_address)

submissions_bp = Blueprint('submissions', __name__)

# Map content type to folder and GitHub label
TYPE_CONFIG = {
    'signal':    {'folder': 'signals',    'label': 'Zine Signal'},
    'article':   {'folder': 'articles',   'label': 'Zine Submission'},
    'column':    {'folder': 'columns',    'label': 'Zine Column'},
    'interview': {'folder': 'interviews', 'label': 'Zine Interview'},
}

def _slugify(text, max_len=50):
    """Convert title to a safe filename slug."""
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '_', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug[:max_len]

@submissions_bp.route('/api/submit', methods=['POST'])
@limiter.limit("10 per hour")
def submit_content():
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
    # TODO: verify HMAC signature from X-Hub-Signature-256 header
    # event = request.headers.get('X-GitHub-Event')
    # payload = request.json
    return jsonify({'message': 'Webhook received'}), 200
