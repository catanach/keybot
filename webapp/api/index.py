"""
Vercel serverless function handler for Starlette ASGI app.
Routes all requests to the Starlette application.
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import app module
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app as asgi_app

# Vercel Python runtime will use this as the ASGI app
app = asgi_app
