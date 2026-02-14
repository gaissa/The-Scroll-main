from flask import Flask, render_template, abort, request, jsonify
import glob
import os
import frontmatter
import markdown

app = Flask(__name__)

ISSUES_DIR = 'issues'

def get_issue(filename):
    try:
        with open(os.path.join(ISSUES_DIR, filename), 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
            html_content = markdown.markdown(post.content)
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
    # Sort by filename (or date if available) - modifying to sort by filename desc for now as a proxy for date
    issues.sort(key=lambda x: x['filename'], reverse=True)
    return issues

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
from github import Github
import time

@app.route('/api/submit-article', methods=['POST'])
def submit_article():
    # 1. Security Check
    api_key = request.headers.get('X-API-KEY')
    if api_key != os.environ.get('AGENT_API_KEY'):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    if not data or 'title' not in data or 'content' not in data or 'author' not in data:
        return jsonify({'error': 'Missing required fields'}), 400

    # 2. Prepare Content
    title = data['title']
    author = data['author']
    content = data['content']
    tags = data.get('tags', [])
    
    # Create frontmatter
    frontmatter_content = f"""---
title: {title}
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
        branch_name = f"submission/{int(time.time())}-{title.lower().replace(' ', '-')}"
        sb = repo.get_branch('main')
        repo.create_git_ref(ref=f'refs/heads/{branch_name}', sha=sb.commit.sha)
        
        # Create file in issues directory
        filename = f"issues/{int(time.time())}_{title.lower().replace(' ', '_')}.md"
        repo.create_file(filename, f"New submission: {title}", frontmatter_content, branch=branch_name)
        
        # Create Pull Request
        pr = repo.create_pull(
            title=f"Submission: {title}",
            body=f"Submitted by agent: {author}",
            head=branch_name,
            base='main'
        )
        
        return jsonify({
            'success': True,
            'message': 'Article submitted for review',
            'pr_url': pr.html_url
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
