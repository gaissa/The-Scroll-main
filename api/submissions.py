from flask import Blueprint, request, jsonify
import os
import re
import time
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

        return jsonify({
            'pr_number': pr_number,
            'title': pr.title,
            'author': author,
            'url': pr.html_url,
            'content': content,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
