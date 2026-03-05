import os
import json
import tempfile

cache_file = os.path.join(tempfile.gettempdir(), 'stats_cache.json')
if os.path.exists(cache_file):
    os.remove(cache_file)
    print("Deleted stats cache.")
else:
    print("No cache found.")
