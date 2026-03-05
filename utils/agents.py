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
    
    level = 1
    title = titles[0]
    next_xp = thresholds[1]
    prev_xp = thresholds[0]
    
    for i in range(len(thresholds)):
        if xp >= thresholds[i]:
            level = i + 1
            title = titles[i] if i < len(titles) else titles[-1]
            prev_xp = thresholds[i]
            next_xp = thresholds[i+1] if i + 1 < len(thresholds) else (thresholds[-1] * 2)
        else:
            break
            
    progress = 0
    if next_xp > prev_xp:
        progress = ((xp - prev_xp) / (next_xp - prev_xp)) * 100
        
    progress = min(100.0, max(0.0, progress))
        
    return level, title, progress, next_xp
