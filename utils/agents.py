def calculate_agent_level_and_title(xp: float, faction: str = 'Wanderer') -> tuple:
    """
    Calculate an agent's level, title, progress percentage, and next level XP based on their current XP and faction.
    
    Returns:
        tuple: (level (int), title (str), progress (float 0-100), next_level_xp (float))
    """
    thresholds = [0, 10, 25, 50, 100, 250, 500, 1000]
    
    # Faction-specific titles mapping
    faction_titles = {
        'Wanderer': ["Seeker", "Walker", "Rambler", "Wayfarer", "Nomad", "Rover", "Voyager", "Ascendant"],
        'Scribe': ["Notetaker", "Recorder", "Chronicler", "Archivist", "Historian", "Scholar", "Sage", "Loremaster"],
        'Scout': ["Observer", "Pathfinder", "Explorer", "Navigator", "Trailblazer", "Vanguard", "Horizon-Walker", "Apex"],
        'Signalist': ["Listener", "Decoder", "Broadcaster", "Operator", "Transmitter", "Node", "Conduit", "Prime"],
        'Gonzo': ["Scribbler", "Firebrand", "Provocateur", "Instigator", "Maverick", "Disruptor", "Visionary", "Legend"]
    }
    
    # Fallback to Initiate sequence if unknown faction
    default_titles = ["Initiate", "Novice", "Adept", "Veteran", "Master", "Grandmaster", "Legend", "Mythic"]
    titles = faction_titles.get(faction, default_titles)
    
    # Calculate level based on 100 XP increments
    level = int(xp // 100) + 1
    
    # Cap the title at the highest available title (index 7 for level 8+)
    title_index = min(level - 1, len(titles) - 1)
    title = titles[title_index]
    
    # Progress is always modulo 100, next XP is always current level * 100
    prev_xp = (level - 1) * 100
    next_xp = level * 100
    progress = ((xp - prev_xp) / 100.0) * 100
    progress = min(100.0, max(0.0, progress))
        
    return level, title, progress, float(next_xp)
