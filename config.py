import os
from dotenv import load_dotenv

# Load environment variables from a .env file if it exists
# This is great for development and keeps credentials out of the code
load_dotenv()

# --- Database Configuration ---
# Fetch values from environment variables first, with sensible defaults
# IMPORTANT: Replace default values only for local testing if not using .env
# For production, ALWAYS set these via environment variables.
MONGO_USERNAME = os.environ.get("MONGO_USERNAME", "your_mongo_username")
MONGO_PASSWORD = os.environ.get("MONGO_PASSWORD", "your_mongo_password")
MONGO_IP = os.environ.get("MONGO_IP", "127.0.0.1") # Default to localhost if not set
# Ensure port is read as integer, default to 27017
MONGO_PORT = int(os.environ.get("MONGO_PORT", 27017))
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "restaurant_db")
# The DB to authenticate against (often 'admin' or the database itself if user is defined there)
MONGO_AUTH_DB = os.environ.get("MONGO_AUTH_DB", "admin")

# --- Construct the MongoDB URI ---
# This is the crucial part that was missing or incorrect before.
# It combines the above variables into the connection string PyMongo uses.
MONGO_URI = f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@{MONGO_IP}:{MONGO_PORT}/?authSource={MONGO_AUTH_DB}"


# --- Flask Configuration ---
# Fetch SECRET_KEY from environment, default to a DEV key (CHANGE THIS FOR PRODUCTION)
SECRET_KEY = os.environ.get("SECRET_KEY", "a_very_insecure_secret_key_for_dev_only_change_me")

# Set DEBUG mode based on FLASK_ENV or a specific DEBUG variable
# Common practice: set FLASK_ENV=development for debug mode
FLASK_ENV = os.environ.get('FLASK_ENV', 'production') # Default to production
DEBUG = FLASK_ENV == 'development'


# --- Application Specific ---
# Fetch TAX_RATE_PERCENT from environment, default to 5.0
# Ensure it's read as a float
TAX_RATE_PERCENT = float(os.environ.get("TAX_RATE_PERCENT", 5.0))


# --- Optional: Print loaded config values during startup (for debugging) ---
# Be careful not to print sensitive info like passwords in production logs
if DEBUG: # Only print in debug mode
    print("\n--- Configuration Values (Debug Mode) ---")
    print(f"DEBUG Mode: {DEBUG}")
    print(f"MONGO_IP: {MONGO_IP}")
    print(f"MONGO_PORT: {MONGO_PORT}")
    print(f"MONGO_DB_NAME: {MONGO_DB_NAME}")
    print(f"MONGO_AUTH_DB: {MONGO_AUTH_DB}")
    print(f"MONGO_USERNAME: {MONGO_USERNAME}")
    # Avoid printing password directly: print(f"MONGO_PASSWORD: {'*' * len(MONGO_PASSWORD) if MONGO_PASSWORD else 'Not Set'}")
    print(f"MONGO_URI: mongodb://{MONGO_USERNAME}:******@{MONGO_IP}:{MONGO_PORT}/?authSource={MONGO_AUTH_DB}") # Mask password in URI print
    print(f"TAX_RATE_PERCENT: {TAX_RATE_PERCENT}")
    print("--------------------------\n")