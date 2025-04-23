import os
import urllib.parse # <-- Added import
from dotenv import load_dotenv

# Load environment variables from a .env file if it exists
load_dotenv()

# --- Database Configuration ---
MONGO_USERNAME = os.environ.get("MONGO_USERNAME", "your_mongo_username")
MONGO_PASSWORD = os.environ.get("MONGO_PASSWORD", "your_mongo_password")
MONGO_IP = os.environ.get("MONGO_IP", "127.0.0.1") # Default to localhost if not set
MONGO_PORT = int(os.environ.get("MONGO_PORT", 27017))
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "restaurant_db")
MONGO_AUTH_DB = os.environ.get("MONGO_AUTH_DB", "admin") # DB for authentication

# --- Encode username and password ---
# This handles special characters like '@', ':', '/' etc. in credentials
encoded_username = urllib.parse.quote_plus(MONGO_USERNAME)
encoded_password = urllib.parse.quote_plus(MONGO_PASSWORD)

# --- Construct the MongoDB URI ---
# Use the encoded username and password
MONGO_URI = f"mongodb://{encoded_username}:{encoded_password}@{MONGO_IP}:{MONGO_PORT}/?authSource={MONGO_AUTH_DB}"


# --- Flask Configuration ---
SECRET_KEY = os.environ.get("SECRET_KEY", "a_very_insecure_secret_key_for_dev_only_change_me")
FLASK_ENV = os.environ.get('FLASK_ENV', 'production') # Default to production
DEBUG = FLASK_ENV == 'development'


# --- Application Specific ---
TAX_RATE_PERCENT = float(os.environ.get("TAX_RATE_PERCENT", 5.0)) # Example Tax Rate


# --- Optional: Print loaded config values during startup (for debugging) ---
if DEBUG: # Only print in debug mode
    print("\n--- Configuration Values (Debug Mode) ---")
    print(f"DEBUG Mode: {DEBUG}")
    print(f"MONGO_IP: {MONGO_IP}")
    print(f"MONGO_PORT: {MONGO_PORT}")
    print(f"MONGO_DB_NAME: {MONGO_DB_NAME}")
    print(f"MONGO_AUTH_DB: {MONGO_AUTH_DB}")
    print(f"MONGO_USERNAME (Original): {MONGO_USERNAME}")
    # Avoid printing password directly: print(f"MONGO_PASSWORD: {'*' * len(MONGO_PASSWORD) if MONGO_PASSWORD else 'Not Set'}")
    # Print the final URI with password masked
    print(f"MONGO_URI: mongodb://{encoded_username}:******@{MONGO_IP}:{MONGO_PORT}/?authSource={MONGO_AUTH_DB}")
    print(f"TAX_RATE_PERCENT: {TAX_RATE_PERCENT}")
    print("--------------------------\n")
elif os.environ.get('PRINT_CONFIG_ON_START') == 'true': # Or use another flag for production but be careful
    # Optionally print non-sensitive info on production start if needed
    print("\n--- Configuration Loaded ---")
    print(f"MONGO_IP: {MONGO_IP}")
    print(f"MONGO_PORT: {MONGO_PORT}")
    print(f"MONGO_DB_NAME: {MONGO_DB_NAME}")
    print(f"MONGO_AUTH_DB: {MONGO_AUTH_DB}")
    print("--------------------------\n")