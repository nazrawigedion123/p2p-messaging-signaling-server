# passenger_wsgi.py
import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from signal_server import app

# --- IMPORTANT ---
# Wrap FastAPI (ASGI) app into WSGI so Passenger can run it
try:
    from fastapi.middleware.wsgi import WSGIMiddleware
except ImportError:
    from starlette.middleware.wsgi import WSGIMiddleware

# WSGI application Passenger will serve
application = WSGIMiddleware(app)