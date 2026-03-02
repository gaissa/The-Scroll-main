import os
from github import Github, Auth
from dotenv import load_dotenv

load_dotenv('.env', override=True)
token = os.environ.get('GITHUB_TOKEN')
repo_name = os.environ.get('REPO_NAME')

g = Github(auth=Auth.Token(token))
repo = g.get_repo(repo_name)

print(f"Testing repo {repo_name}...")
prs = repo.get_pulls(state='all', sort='created', direction='desc')
for i, pr in enumerate(prs):
    if i >= 10: break
    print(f"PR #{pr.number}: state='{pr.state}', merged={pr.merged}")
