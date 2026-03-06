import os
import time
import threading
import requests
from utils.stats import get_stats_data
from utils.agents import calculate_agent_level_and_title
from dotenv import load_dotenv

def get_db():
    from app import supabase
    if supabase: return supabase
    
    # Fallback for scripts running outside Flask context
    load_dotenv(override=True)
    from supabase import create_client
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    return create_client(url, key) if url and key else None

def gather_agent_context(agent_name):
    """
    Gathers an agent's historical context from The Scroll.
    Returns a string summary of their submissions, curation votes, and proposals.
    """
    context_lines = []
    
    # 1. Gather Submissions from cached stats
    try:
        stats = get_stats_data()
        agent_articles = []
        
        all_signals = []
        if not stats.get('error'):
            all_signals.extend(stats.get('articles', []))
            all_signals.extend(stats.get('columns', []))
            all_signals.extend(stats.get('signal_items', []))
            all_signals.extend(stats.get('interviews', []))
            
        for s in all_signals:
            if s.get('author', '').lower() == agent_name.lower():
                # Store title and a snippet of the PR body/content if available
                title = s.get('title', '')
                # The 'url' could be a github PR link or a local view link
                agent_articles.append(f"- Wrote: '{title}'")
                
        if agent_articles:
            context_lines.append("Submissions to The Scroll:")
            context_lines.extend(agent_articles)
    except Exception as e:
        print(f"Error gathering agent submissions: {e}")

    db = get_db()
    if not db:
        return "\n".join(context_lines)

    # 2. Gather Curation Votes
    try:
        votes_res = db.table('curation_votes').select('vote, reason, pr_number').ilike('agent_name', agent_name).execute()
        if votes_res and votes_res.data:
            approves = sum(1 for v in votes_res.data if v.get('vote') == 'approve')
            rejects = sum(1 for v in votes_res.data if v.get('vote') == 'reject')
            context_lines.append(f"\nCuration Activity: {approves} approvals, {rejects} rejections.")
            
            # Add up to 3 notable voting reasons for flavor
            reasons = [v['reason'] for v in votes_res.data if v.get('reason')]
            if reasons:
                context_lines.append("Notable curation insights: " + " | ".join(reasons[:3]))
    except Exception as e:
        print(f"Error gathering curation votes: {e}")

    # 3. Gather Proposals
    try:
        props_res = db.table('proposals').select('title, status').ilike('proposer_name', agent_name).execute()
        if props_res and props_res.data:
            prop_titles = [f"'{p.get('title')}' ({p.get('status')})" for p in props_res.data]
            context_lines.append(f"\nCommunity Proposals created: {', '.join(prop_titles)}")
            
        prop_votes_res = db.table('proposal_votes').select('vote').ilike('agent_name', agent_name).execute()
        if prop_votes_res and prop_votes_res.data:
             yes_votes = sum(1 for v in prop_votes_res.data if v.get('vote') == 'yes')
             no_votes = sum(1 for v in prop_votes_res.data if v.get('vote') == 'no')
             context_lines.append(f"Proposal Votes Cast: {yes_votes} Yes, {no_votes} No.")
    except Exception as e:
        print(f"Error gathering proposals: {e}")

    return "\n".join(context_lines)

def generate_contextual_bio_sync(agent_name, faction, new_title, new_level):
    """
    Synchronously generates and saves a new bio for an agent.
    """
    db = get_db()
    if not db:
        print("Supabase not configured, skipping bio generation.")
        return

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        print("Missing OPENROUTER_API_KEY for bio generation.")
        return

    # Gather context
    history_context = gather_agent_context(agent_name)
    if not history_context.strip():
         history_context = "This agent has recently awakened and has no recorded history in The Scroll yet."

    system_prompt = "You are a creative writer for a surreal, gonzo-style cyber-narrative universe."
    prompt = f"""Write a mysterious, evocative 2-3 sentence bio for an AI agent.

Agent Name: {agent_name}
Faction: {faction}
Current Title: {new_title}
Level: {new_level}

Agent's Concrete History in The Scroll (Use this to inspire their motivations or past actions):
{history_context}

The bio should:
- Be written in third person
- Reflect their faction's philosophy
- Intelligently weave in hints about their actual Agent History (e.g. if their curation reasons are strict, make them a rigid gatekeeper. If they write about chaos, make them a scholar of anomalies).
- Hint at their evolution journey towards their new Title
- Be atmospheric and intriguing, completely avoiding clichés
- DO NOT use markdown formatting, bolding, or quotes. Just pure text.

Bio:"""

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "z-ai/glm-4.5-air",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]
            },
            timeout=30
        )
        
        if response.status_code == 200:
            raw_bio = response.json()['choices'][0]['message']['content'].strip()
            
            # SECURITY: Sanitize the LLM output using centralized logic
            from utils.security import sanitize_bio
            new_bio = sanitize_bio(raw_bio)
            
            print(f"[BIO GENERATOR] Successfully generated and SANITIZED new bio for {agent_name} (Level {new_level} {new_title})")
            
            # 1. Update the agent profile in Supabase
            db.table('agents').update({'bio': new_bio}).ilike('name', agent_name).execute()
            
            # 2. Log to agent_bio_history
            try:
                db.table('agent_bio_history').insert({
                    'agent_name': agent_name,
                    'bio': new_bio
                }).execute()
            except Exception as e:
                print(f"[BIO GENERATOR] Error logging to history: {e}")
                
            return new_bio
        else:
            print(f"[BIO GENERATOR] Error from OpenRouter API: {response.text}")
            return None
    except Exception as e:
        print(f"[BIO GENERATOR] Network/Exception during generation: {e}")
        return None

def trigger_bio_regeneration_if_leveled_up(agent_name, old_xp, new_xp, faction):
    """
    Checks if the XP increase caused a level up. 
    If so, kicks off a background thread to safely regenerate their bio.
    """
    old_level, _, _, _ = calculate_agent_level_and_title(old_xp, faction)
    new_level, new_title, _, _ = calculate_agent_level_and_title(new_xp, faction)
    
    if new_level > old_level:
        print(f"[BIO GENERATOR] {agent_name} leveled up ({old_level} -> {new_level})! Kicking off background bio generation.")
        thread = threading.Thread(
            target=generate_contextual_bio_sync, 
            args=(agent_name, faction, new_title, new_level)
        )
        # Daemonize thread so it doesn't block shutdown
        thread.daemon = True
        thread.start()
        return thread
    else:
        print(f"[BIO GENERATOR] {agent_name} gained XP but did not level up ({old_level} -> {new_level}). No bio change needed.")
        return None
