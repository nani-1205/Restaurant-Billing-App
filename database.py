# database.py
import pymongo
from flask import current_app, g
from pymongo.errors import ConnectionFailure, OperationFailure
from decimal import Decimal # Import Decimal for potential use with specific types

# --- Corrected Import for Type Hinting ---
from pymongo.database import Database # Import the Database class specifically

# Consider using Type Hints for better code clarity if using Python 3.7+
from typing import Optional, List, Dict, Any

# Global variable to hold the client and db
mongo_client: Optional[pymongo.MongoClient] = None
# --- Corrected Type Hint ---
db: Optional[Database] = None

def init_db(app):
    """Initializes the MongoDB connection and checks/creates the database."""
    global mongo_client, db
    mongo_uri = app.config['MONGO_URI']
    db_name = app.config['MONGO_DBNAME']

    if not all([app.config['MONGO_HOST'], app.config['MONGO_PORT'], app.config['MONGO_DBNAME']]):
         print("FATAL: MongoDB connection details (HOST, PORT, DBNAME) are missing in the environment/config.")
         raise ValueError("Missing MongoDB configuration details.")

    try:
        print(f"Attempting to connect to MongoDB at: {app.config['MONGO_HOST']}:{app.config['MONGO_PORT']} DB: {db_name}")
        # Increase connection timeout, add server selection timeout
        client = pymongo.MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=5000, # Timeout after 5 seconds if no suitable server is found
            connectTimeoutMS=10000 # Wait up to 10 seconds for initial connection
        )
        # The ismaster command is cheap and does not require auth. Forces connection check.
        client.admin.command('ismaster')
        print("MongoDB connection successful.")

        mongo_client = client
        db = client[db_name] # Select the database

        # Ensure essential collections exist (MongoDB creates them on first use, but good practice to log)
        ensure_collections_exist(db)

        # Optional: Create Indexes (Good for performance)
        create_indexes(db)

    except ConnectionFailure as e:
        print(f"FATAL: MongoDB connection failed: {e}")
        mongo_client = None
        db = None
        # Re-raise the exception so the app knows connection failed
        raise ConnectionFailure(f"Could not connect to MongoDB: {e}")
    except OperationFailure as e:
        print(f"FATAL: MongoDB operation failed (Authentication Error?): {e}")
        mongo_client = None
        db = None
        raise OperationFailure(f"MongoDB authentication or operation error: {e}")
    except Exception as e:
        print(f"FATAL: An unexpected error occurred during DB initialization: {e}")
        mongo_client = None
        db = None
        raise e

# --- Corrected Type Hint in function signature ---
def ensure_collections_exist(database: Database):
    """Checks if essential collections exist, logging if they will be auto-created."""
    required_collections: List[str] = [
        'menu_items', 'tables', 'orders', 'users', 'customers',
        'inventory_items', 'employees', 'payments' # Added 'payments'
        ]
    try:
        existing_collections = database.list_collection_names()
        print(f"Existing collections in '{database.name}': {existing_collections}")
        for coll_name in required_collections:
            if coll_name not in existing_collections:
                print(f"INFO: Collection '{coll_name}' not found. It will be created on first use.")
    except OperationFailure as e:
        # This can happen if the user doesn't have listCollections permission
        print(f"WARNING: Could not list collections (permission issue?): {e}. Collections will be created implicitly.")

# --- Corrected Type Hint in function signature ---
def create_indexes(database: Database):
    """Creates recommended indexes for better performance."""
    print("INFO: Checking/creating database indexes...")
    try:
        # Menu Items
        database.menu_items.create_index([("name", pymongo.ASCENDING)], unique=True)
        database.menu_items.create_index([("category", pymongo.ASCENDING)])
        database.menu_items.create_index([("is_available", pymongo.ASCENDING)])

        # Tables
        database.tables.create_index([("number", pymongo.ASCENDING)], unique=True)
        database.tables.create_index([("status", pymongo.ASCENDING)])

        # Orders
        database.orders.create_index([("timestamp", pymongo.DESCENDING)])
        database.orders.create_index([("status", pymongo.ASCENDING)])
        database.orders.create_index([("table_id", pymongo.ASCENDING)])
        database.orders.create_index([("customer_id", pymongo.ASCENDING)], sparse=True) # If tracking customer orders

        # Inventory Items
        database.inventory_items.create_index([("name", pymongo.ASCENDING)], unique=True)
        # database.inventory_items.create_index([("adjustments_log.timestamp", pymongo.DESCENDING)]) # If logging adjustments

        # Customers
        database.customers.create_index([("name", pymongo.ASCENDING)])
        database.customers.create_index([("phone", pymongo.ASCENDING)], unique=True, sparse=True) # Unique phone, if present
        database.customers.create_index([("email", pymongo.ASCENDING)], unique=True, sparse=True) # Unique email, if present

        # Employees
        database.employees.create_index([("name", pymongo.ASCENDING)])
        database.employees.create_index([("email", pymongo.ASCENDING)], unique=True, sparse=True) # Unique email, if present
        database.employees.create_index([("is_active", pymongo.ASCENDING)])

        # Payments
        database.payments.create_index([("timestamp", pymongo.DESCENDING)])
        database.payments.create_index([("table_id", pymongo.ASCENDING)])

        print("INFO: Index creation process completed.")
    except OperationFailure as e:
         print(f"WARNING: Could not create indexes (permission issue?): {e}")
    except Exception as e:
         print(f"ERROR: Unexpected error during index creation: {e}")

# --- Corrected Type Hint for return value ---
def get_db() -> Database:
    """
    Returns the MongoDB database instance for the current application context.
    Raises an exception if the database is not initialized.
    """
    if db is None:
        print("ERROR: get_db() called but database is not initialized.")
        raise RuntimeError("Database is not initialized. Check application startup.")
    return db

def close_db(e=None):
    """Closes the MongoDB connection."""
    global mongo_client, db
    if mongo_client:
        print("INFO: Closing MongoDB connection.")
        mongo_client.close()
        mongo_client = None
        db = None # Clear the db reference as well

# Function to be registered with Flask app teardown
def teardown_db(exception: Optional[Exception] = None):
    """Closes the database connection at the end of the request/context."""
    close_db(exception)