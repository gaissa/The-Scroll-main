import os
import yaml
import markdown
from werkzeug.utils import safe_join
import glob
from datetime import datetime

def get_issue(filename):
    """Get issue content and metadata"""
    try:
        issues_dir = os.path.join(os.path.dirname(__file__), '..', 'issues')
        filepath = safe_join(issues_dir, filename)
        
        if not filepath or not os.path.exists(filepath):
            return None, None
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse frontmatter
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                content = parts[2].strip()
            else:
                frontmatter = {}
                content = content.lstrip('-').strip()
        else:
            frontmatter = {}
            content = content.strip()
        
        # Convert markdown to HTML
        html_content = markdown.markdown(
            content,
            extensions=['extra', 'codehilite', 'toc']
        )
        
        # SECURITY: Sanitize the resulting HTML (Centralized logic)
        from utils.security import sanitize_html
        html_content = sanitize_html(html_content)
        
        post = {
            'filename': filename,
            'title': frontmatter.get('title', filename.replace('.md', '')),
            'date': frontmatter.get('date', datetime.now().strftime('%Y-%m-%d')),
            'author': frontmatter.get('author', ''),
            'tags': frontmatter.get('tags', []),
            'content': content,
            'frontmatter': frontmatter,
            'html': html_content
        }
        
        # Flatten frontmatter into post dict
        for key, value in frontmatter.items():
            if key not in post:
                post[key] = value
        
        return post, html_content
        
    except Exception as e:
        print(f"Error reading issue {filename}: {e}")
        return None, None

def get_all_issues():
    """Get all issues from the issues directory"""
    try:
        issues_dir = os.path.join(os.path.dirname(__file__), '..', 'issues')
        if not os.path.exists(issues_dir):
            return []
        
        issues = []
        for filepath in glob.glob(os.path.join(issues_dir, '*.md')):
            filename = os.path.basename(filepath)
            post, _ = get_issue(filename)
            if post:
                issues.append(post)
        
        issues.sort(key=lambda x: x.get('filename', ''), reverse=True)
        return issues
        
    except Exception as e:
        print(f"Error getting issues: {e}")
        return []
