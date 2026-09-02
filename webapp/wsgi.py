"""
WSGI wrapper for Starlette ASGI app on Vercel.
Provides a WSGI interface while running the ASGI app.
"""

import asyncio
from app.main import app as asgi_app
from starlette.middleware.wsgi import WSGIMiddleware

# Create a WSGI-compatible wrapper
wsgi_app = WSGIMiddleware(asgi_app)

# Export for Vercel
app = wsgi_app
