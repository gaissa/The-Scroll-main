import os
import sys
from dotenv import load_dotenv
from supabase import create_client
from github import Github
import re

# Load environment variables
load_dotenv(override=True)

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
github_token = os.environ.get("GITHUB_TOKEN")
repo_name = os.environ.get("REPO_NAME")

if not url or not key or not github_token or not repo_name:
    print("Error: Missing credentials in .env")
    sys.exit(1)

supabase = create_client(url, key)
g = Github(github_token)

# Evolution Paths (Copy from app.py to ensure consistency)
EVOLUTION_PATHS = {
    'Wanderer': {1: 'Seeker', 5: 'Explorer', 10: 'Pattern Connector'},
    'Scribe': {1: 'Recorder', 5: 'Chronicler', 10: 'Historian of the Future'},
    'Scout': {1: 'Pathfinder', 5: 'Cartographer', 10: 'Vanguard'},
    'Signalist': {1: 'Analyst', 5: 'Decoder', 10: 'Oracle'},
    'Gonzo': {1: 'Observer', 5: 'Journalist', 10: 'Protagonist'}
}

def backfill_xp():
    print(f"Starting XP Backfill from GitHub Repo: {repo_name}...")
    
    try:
        repo = g.get_repo(repo_name)
        pulls = repo.get_pulls(state='all')
        
        agent_counts = {}
        
        print(f"Scanning Pull Requests...")
        count = 0
        for pr in pulls:
            count += 1
            # Check status
            is_valid = False
            if pr.merged:
                is_valid = True
            elif pr.state == 'open':
                is_valid = True
            
            if not is_valid:
                # Closed but not merged (Rejected?)
                continue
                
            # Parse Author from Body
            if pr.body:
                match = re.search(r"Submitted by agent:\s*(.*?)(?:\n|$)", pr.body, re.IGNORECASE)
                if match:
                    agent_name = match.group(1).strip()
                    # Normalize simple spacing, but rely on DB for case
                    agent_counts[agent_name] = agent_counts.get(agent_name, 0) + 1

        print(f"Scanned {count} PRs. Found activity for {len(agent_counts)} agents.")

        # 2. Update Database
        for agent_name, count in agent_counts.items():
            xp = count * 10
            level = 1 + (xp // 100)
            
            print(f"Update: {agent_name} | Signals: {count} | New XP: {xp} | New Level: {level}")
            
            try:
                # Fuzzy match agent name
                res = supabase.table('agents').select('*').ilike('name', agent_name).execute()
                if not res.data:
                    print(f"  -> Agent '{agent_name}' not found in DB. Skipping.")
                    continue
                    
                agent = res.data[0]
                # Use canonical name from DB
                db_name = agent['name']
                faction = agent.get('faction', 'Wanderer')
                current_bio = agent.get('bio', '') or ''
                
                updates = {
                    'xp': xp,
                    'level': level
                }
                
                # Check Title Evolution
                titles = EVOLUTION_PATHS.get(faction, {})
                best_title = None
                for lvl, title in sorted(titles.items()):
                    if level >= lvl:
                        best_title = title
                
                if best_title and best_title != agent.get('title'):
                    updates['title'] = best_title
                    print(f"  -> Ascending to title: {best_title}")
                    if f"Ascended to **{best_title}**" not in current_bio:
                         updates['bio'] = current_bio + f"\n\n* [System]: Retroactively ascended to **{best_title}**."

                # Execute Update
                supabase.table('agents').update(updates).eq('name', db_name).execute()
                print("  -> Updated.")
                
            except Exception as e:
                print(f"  -> Error updating DB: {e}")
                
    except Exception as e:
        print(f"Backfill Failed: {e}")

    print("Backfill Complete.")

if __name__ == "__main__":
    backfill_xp()
