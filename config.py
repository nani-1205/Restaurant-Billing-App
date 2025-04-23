# restaurant_billing/config.py

import os
from dotenv import load_dotenv

# Determine the base directory of the project
# This ensures .env is found even if config.py is run from a different directory
basedir = os.path.abspath(os.path.dirname(__file__))
dotenv_path = os.path.join(basedir, '.env')

# Load environment variables from .env file
# If the .env file exists, load_dotenv returns True, otherwise False
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
    print("Loaded environment variables from .env file.")
else:
    print("Warning: .env file not found. Using system environment variables or defaults.")


# --- Database Configuration ---
# Load individual components from environment variables.
# MongoClient in app.py will use these directly.
# Provide sensible defaults mainly for local development if .env is missing.

MONGO_USERNAME = os.environ.get("MONGO_USERNAME", "default_user")
MONGO_PASSWORD = os.environ.get("MONGO_PASSWORD", "default_password")
MONGO_IP = os.environ.get("MONGO_IP", "127.0.0.1")
# Ports are typically integers, so cast it
MONGO_PORT = int(os.environ.get("MONGO_PORT", 27017))
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "restaurant_db_dev") # Maybe use diff name for dev
MONGO_AUTH_DB = os.environ.get("MONGO_AUTH_DB", "admin") # The database to authenticate against

# --- Flask Configuration ---
# Load secret key from environment or use a default (INSECURE FOR PRODUCTION)
SECRET_KEY = os.environ.get("SECRET_KEY", "a_very_insecure_default_secret_key_for_dev_only")
if SECRET_KEY == "a_very_insecure_default_secret_key_for_dev_only":
     print("\nWARNING: Using default Flask SECRET_KEY. Set a strong SECRET_KEY in your .env file for production!\n")


# Set debug mode based on environment variable (e.g., FLASK_DEBUG=1) or default to False for safety
# Flask automatically uses FLASK_DEBUG environment variable if set.
# Setting it here provides an explicit default if FLASK_DEBUG isn't set.
# Common practice: Set DEBUG based on an environment variable like FLASK_ENV=development
FLASK_ENV = os.environ.get('FLASK_ENV', 'production') # Default to production for safety
DEBUG = FLASK_ENV == 'development' # Set DEBUG to True only if FLASK_ENV is 'development'

# --- Application Specific ---
# Load tax rate from environment or use a default
try:
    TAX_RATE_PERCENT = float(os.environ.get("TAX_RATE_PERCENT", 5.0))
except ValueError:
    print("Warning: Invalid TAX_RATE_PERCENT in environment. Using default 5.0")
    TAX_RATE_PERCENT = 5.0


# --- Optional: Print loaded config for verification (careful with sensitive info) ---
print("--- Configuration Values ---")
print(f"FLASK_ENV: {FLASK_ENV}")
print(f"DEBUG Mode: {DEBUG}")
print(f"MONGO_IP: {MONGO_IP}")
print(f"MONGO_PORT: {MONGO_PORT}")
print(f"MONGO_DB_NAME: {MONGO_DB_NAME}")
print(f"MONGO_AUTH_DB: {MONGO_AUTH_DB}")
print(f"MONGO_USERNAME: {MONGO_USERNAME}")
# Avoid printing password in logs:
# print(f"MONGO_PASSWORD: {'*' * len(MONGO_PASSWORD) if MONGO_PASSWORD else 'Not Set'}")
print(f"TAX_RATE_PERCENT: {TAX_RATE_PERCENT}")
print("--------------------------")

# --- Sanity Checks (Optional but recommended) ---
if not SECRET_KEY or SECRET_KEY == "a_very_insecure_default_secret_key_for_dev_only":
    # This check is redundant with the warning above, but emphasizes importance
    print("CRITICAL WARNING: Flask SECRET_KEY is not set or is insecure.")

if not MONGO_USERNAME or not MONGO_PASSWORD:
    print("Warning: MongoDB username or password might be missing.")