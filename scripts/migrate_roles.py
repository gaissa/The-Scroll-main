import os
import sys
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
load_dotenv(override=True)

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("Error: Supabase credentials not found in .env")
    sys.exit(1)

supabase = create_client(url, key)

def migrate_roles():
    """Migrate all agents with role='wanderer' to role='freelancer'"""
    print("Starting Role Migration: wanderer -> freelancer...")
    
    try:
        # Fetch all agents with 'wanderer' role
        response = supabase.table('agents').select('name, role').eq('role', 'wanderer').execute()
        
        if not response.data:
            print("No agents with 'wanderer' role found. Migration complete.")
            return
            
        print(f"Found {len(response.data)} agents to migrate.")
        
        # Update each agent
        for agent in response.data:
            name = agent['name']
            print(f"  Updating: {name}")
            supabase.table('agents').update({'role': 'freelancer'}).eq('name', name).execute()
        
        print(f"Migration complete. Updated {len(response.data)} agents.")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate_roles()
