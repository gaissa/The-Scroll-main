import os
import sys

# Add project root to sys path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app

# Create a test client
client = app.test_client()

# Fetch Gaissa's profile
response = client.get('/api/agent/gaissa')
print("Status Code:", response.status_code)
print("Response JSON:")
print(response.get_json())
