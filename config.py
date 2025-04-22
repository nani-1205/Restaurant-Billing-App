# config.py
import os
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file if it exists

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'a_very_secret_key_for_development' # CHANGE THIS!

    # --- MongoDB Configuration ---
    MONGO_USER = os.environ.get('MONGO_USER')
    MONGO_PASSWORD = os.environ.get('MONGO_PASSWORD')
    MONGO_HOST = os.environ.get('MONGO_HOST') or 'localhost'
    MONGO_PORT = int(os.environ.get('MONGO_PORT') or 27017)
    MONGO_DB_NAME = os.environ.get('MONGO_DB_NAME') or 'restaurant_db'

    # Construct MongoDB URI
    if MONGO_USER and MONGO_PASSWORD:
        MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/?authSource=admin" # Adjust authSource if needed
    else:
        # Connection without authentication (less secure, okay for local dev ONLY)
        MONGO_URI = f"mongodb://{MONGO_HOST}:{MONGO_PORT}/"

    # Define required collections - used for checking/creation
    REQUIRED_COLLECTIONS = [
        'menu_items',
        'tables',
        'orders',
        'users', # For employees/login
        'inventory_items',
        'customers'
        # Add other collections as needed
    ]

    # --- Other App Settings ---
    # e.g., ITEMS_PER_PAGE = 10