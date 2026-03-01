#!/usr/bin/env python3
import sys, os
from supabase import create_client

# Load environment
from dotenv import load_dotenv
load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_KEY')

supabase = create_client(supabase_url, supabase_key)

# Fetch uncurated submissions
result = supabase.table('submissions').select('*').eq('curated', False).execute()
submissions = result.data

print(f"Found {len(submissions)} uncurated submissions.")

# For each submission, we can inspect content and make a decision. For now, just mark as curated automatically.
if submissions:
    for sub in submissions:
        # Optionally inspect: print(sub.get('title'), sub.get('status'), sub.get('author'), sub.get('content')[:100])
        # Update curated flag
        supabase.table('submissions').update({'curated': True}).eq('id', sub['id']).execute()
        print(f"Curated: {sub.get('title', 'Untitled')} (ID {sub['id']})")
else:
    print("No uncurated submissions.")

print("Done.")