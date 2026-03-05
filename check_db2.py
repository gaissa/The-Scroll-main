import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.environ.get('SUPABASE_URL')
key = os.environ.get('SUPABASE_KEY')

if not url or not key:
    print("No Supabase credentials")
    exit(1)

supabase = create_client(url, key)
result = supabase.table('agents').select('*').eq('name', 'gaissa').execute()
print(result.data)
