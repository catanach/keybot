"""
Vercel serverless function handler for Starlette ASGI app.
This file is automatically detected by Vercel's Python runtime.
"""

from app.main import app as asgi_app

# Vercel will automatically detect this as the ASGI app
app = asgi_app
