# config.py
import os
from dotenv import load_dotenv
import secrets # For generating default secret key
from urllib.parse import quote_plus # <<< Import quote_plus

# Load environment variables from .env file
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(16)
    STATIC_FOLDER = 'static'
    TEMPLATES_FOLDER = 'templates'

    # Database Configuration
    MONGO_HOST = os.environ.get('MONGO_HOST', 'localhost') # Default to localhost if not set
    MONGO_PORT = int(os.environ.get('MONGO_PORT', 27017)) # Default port if not set
    MONGO_USERNAME = os.environ.get('MONGO_USER')
    MONGO_PASSWORD = os.environ.get('MONGO_PASS')
    MONGO_DBNAME = os.environ.get('MONGO_DB_NAME', 'restaurant_db') # Default DB name
    MONGO_AUTH_DB = os.environ.get('MONGO_AUTH_DB', 'admin') # Default auth DB

    # Construct MongoDB URI
    if MONGO_USERNAME and MONGO_PASSWORD:
        # --- Encode username and password ---
        escaped_username = quote_plus(MONGO_USERNAME)
        escaped_password = quote_plus(MONGO_PASSWORD)
        # --- Use encoded values in the URI ---
        MONGO_URI = f"mongodb://{escaped_username}:{escaped_password}@{MONGO_HOST}:{MONGO_PORT}/{MONGO_DBNAME}?authSource={MONGO_AUTH_DB}"
        print("INFO: Using MongoDB connection string WITH authentication (credentials escaped).")
    else:
        # Connection string without authentication
        MONGO_URI = f"mongodb://{MONGO_HOST}:{MONGO_PORT}/{MONGO_DBNAME}"
        print("INFO: Using MongoDB connection string WITHOUT authentication.") # Changed from WARNING

    # --- Application Specific Settings (Add more as needed) ---
    KDS_REFRESH_RATE = int(os.environ.get('KDS_REFRESH_RATE', 15)) # Allow override via env