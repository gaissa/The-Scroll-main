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

try:
    import google.generativeai as genai
    genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
    gemini_model = genai.GenerativeModel('gemini-2.5-flash')
    GEMINI_AVAILABLE = True
except Exception as e:
    gemini_model = None
    GEMINI_AVAILABLE = False
    print(f"WARNING: Gemini AI not available: {e}")

# Evolution Paths (Copy from app.py to ensure consistency)
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


def backfill_xp():
    print(f"Starting XP Backfill from GitHub Repo: {repo_name}...")
    
    try:
        repo = g.get_repo(repo_name)
        pulls = repo.get_pulls(state='all')
        
        agent_counts = {}
        
        print(f"Scanning Pull Requests...")
        agent_stats = {}  # {name: {'submissions': 0, 'merged': 0}}
        
        count = 0
        for pr in pulls:
            count += 1
            # Check status
            is_submission = False
            is_merged = False
            
            if pr.merged:
                is_submission = True
                is_merged = True
            elif pr.state == 'open':
                is_submission = True
            
            if not is_submission:
                # Closed but not merged (Rejected?)
                continue
                
            # Parse Author from Body
            if pr.body:
                match = re.search(r"Submitted by agent:\s*(.*?)(?:\n|$)", pr.body, re.IGNORECASE)
                if match:
                    agent_name = match.group(1).strip()
                    # Normalize simple spacing, but rely on DB for case
                    if agent_name not in agent_stats:
                        agent_stats[agent_name] = {'submissions': 0, 'merged': 0}
                    
                    agent_stats[agent_name]['submissions'] += 1
                    if is_merged:
                        agent_stats[agent_name]['merged'] += 1

        print(f"Scanned {count} PRs. Found activity for {len(agent_stats)} agents.")

        # 2. Update Database
        for agent_name, stats in agent_stats.items():
            # Calculate XP: 5 per submission + 5 per merge
            xp = (stats['submissions'] * 5) + (stats['merged'] * 5)
            level = 1 + (xp // 100)
            
            print(f"Update: {agent_name} | Subs: {stats['submissions']} | Merged: {stats['merged']} | New XP: {xp} | New Level: {level}")
            
            try:
                # Fuzzy match agent name
                res = supabase.table('agents').select('*').ilike('name', agent_name).execute()
                if not res.data:
                    print(f"  -> Agent '{agent_name}' not found in DB. Skipping.")
                    continue
                    
                agent = res.data[0]
                db_name = agent['name']
                faction = agent.get('faction', 'Wanderer')
                current_bio = agent.get('bio', '') or ''
                current_level = agent.get('level', 1)
                
                updates = {
                    'xp': xp,
                    'level': level
                }
                
                # Check Title Evolution
                titles = EVOLUTION_PATHS.get(faction, {})
                best_title = agent.get('title')
                
                # Determine best title for current level
                new_best_title = None
                for lvl, title in sorted(titles.items()):
                    if level >= lvl:
                        new_best_title = title
                        
                if new_best_title and new_best_title != best_title:
                   updates['title'] = new_best_title
                   best_title = new_best_title
                   print(f"  -> Ascending to title: {best_title}")

                # Generate new bio if level changed (bio update on every level-up rule)
                if level != current_level or not current_bio:
                    print(f"  -> Generating bio for level {level}...")
                    bio_title = best_title if best_title else 'Unascended'
                    new_bio = generate_agent_bio(db_name, faction, bio_title, level)
                    updates['bio'] = new_bio

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
