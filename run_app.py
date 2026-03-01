#!/usr/bin/env python3
import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    # Try to import the app module
    import app
    print("Starting The Scroll app...")
    app.app.run(debug=True, host='0.0.0.0', port=5000)
except ImportError as e:
    print(f"Import error: {e}")
    print("Missing dependencies. Please install required packages.")
except Exception as e:
    print(f"Error running app: {e}")