# passenger_wsgi.py
import os
import sys
from a2wsgi import ASGIMiddleware

# 1. Add the current directory to the system path so Python can find signal_server.py
sys.path.insert(0, os.path.dirname(__file__))

# 2. Import your FastAPI app
# Note: We alias it to 'fastapi_app' to avoid confusion
from signal_server import app as fastapi_app

# 3. Wrap the ASGI app with the WSGI middleware
# Phusion Passenger looks for an object named 'application'
application = ASGIMiddleware(fastapi_app)