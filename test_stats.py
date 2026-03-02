import urllib.request
from urllib.error import HTTPError

try:
    response = urllib.request.urlopen("http://127.0.0.1:5000/stats")
    print("STATUS:", response.getcode())
    print("BODY (first 500 chars):", response.read().decode()[:500])
except HTTPError as e:
    print(f"Error {e.code}:")
    print(e.read().decode()[:500])
