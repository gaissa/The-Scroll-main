from flask import Blueprint, jsonify
from werkzeug.utils import safe_join
from utils.rate_limit import rate_limit
import os

issues_bp = Blueprint('issues', __name__)

@issues_bp.route('/api/issues', methods=['GET'])
@rate_limit(100, per=3600)
def get_issues():
    """Get all published issues"""
    issues_dir = os.path.join(os.path.dirname(__file__), '..', 'issues')
    
    issues = []
    try:
        for f in os.listdir(issues_dir):
            if f.startswith('issue_') and f.endswith('.md'):
                filepath = safe_join(issues_dir, f)
                with open(filepath, 'r') as file:
                    content = file.read()
                    # Parse frontmatter or filename for info
                    issue_num = f.split('_')[1].replace('issue_', '')
                    issues.append({
                        'filename': f,
                        'issue': issue_num,
                        'content': content[:500]  # First 500 chars
                    })
        issues.sort(key=lambda x: x['issue'], reverse=True)
        return jsonify(issues)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
