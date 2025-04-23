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
# Load from environment variables, providing sensible defaults for development if needed
MONGO_USERNAME = os.environ.get("MONGO_USERNAME", "default_user")
MONGO_PASSWORD = os.environ.get("MONGO_PASSWORD", "default_password")
MONGO_IP = os.environ.get("MONGO_IP", "127.0.0.1")
# Ports are typically integers, so cast it
MONGO_PORT = int(os.environ.get("MONGO_PORT", 27017))
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "restaurant_db_dev") # Maybe use diff name for dev
MONGO_AUTH_DB = os.environ.get("MONGO_AUTH_DB", "admin")

# Construct the MongoDB URI using f-string
# Ensure username/password are URL-encoded if they contain special characters
# (pymongo usually handles basic encoding, but be mindful)
MONGO_URI = f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@{MONGO_IP}:{MONGO_PORT}/?authSource={MONGO_AUTH_DB}"

# --- Flask Configuration ---
# Load secret key from environment or use a default (INSECURE FOR PRODUCTION)
SECRET_KEY = os.environ.get("SECRET_KEY", "a_very_insecure_default_secret_key_for_dev_only")
if SECRET_KEY == "a_very_insecure_default_secret_key_for_dev_only":
     print("\nWARNING: Using default Flask SECRET_KEY. Set a strong SECRET_KEY in your .env file for production!\n")


# Set debug mode based on environment variable (e.g., FLASK_DEBUG=1) or default to False for safety
# Flask automatically uses FLASK_DEBUG environment variable if set.
# Setting it here provides an explicit default if FLASK_DEBUG isn't set.
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1" # "1" means True

# --- Application Specific ---
# Load tax rate from environment or use a default
TAX_RATE_PERCENT = float(os.environ.get("TAX_RATE_PERCENT", 5.0))

# --- Print loaded config for verification (optional, careful with passwords in logs) ---
# print("--- Configuration Loaded ---")
# print(f"MONGO_IP: {MONGO_IP}")
# print(f"MONGO_PORT: {MONGO_PORT}")
# print(f"MONGO_DB_NAME: {MONGO_DB_NAME}")
# print(f"MONGO_USERNAME: {MONGO_USERNAME}")
# print(f"MONGO_URI: mongodb://{MONGO_USERNAME}:****@{MONGO_IP}:{MONGO_PORT}/?authSource={MONGO_AUTH_DB}") # Hide password
# print(f"DEBUG Mode: {DEBUG}")
# print(f"TAX_RATE_PERCENT: {TAX_RATE_PERCENT}")
# print("--------------------------")