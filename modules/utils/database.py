# modules/utils/database.py
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ConfigurationError, OperationFailure
import sys
import logging
from flask import current_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = None

def init_db(app):
    """Initializes the MongoDB connection and checks/creates the database and collections."""
    global db
    if db is not None:
        logger.info("Database connection already initialized.")
        return db

    mongo_uri = app.config['MONGO_URI']
    db_name = app.config['MONGO_DB_NAME']
    required_collections = app.config.get('REQUIRED_COLLECTIONS', [])

    try:
        logger.info(f"Attempting to connect to MongoDB at {app.config['MONGO_HOST']}:{app.config['MONGO_PORT']}")
        client = MongoClient(mongo_uri,
                             serverSelectionTimeoutMS=5000) # 5 second timeout

        # The ismaster command is cheap and does not require auth.
        client.admin.command('ismaster')
        logger.info("MongoDB connection successful.")

        # Get the database
        db = client[db_name]
        logger.info(f"Using database: '{db_name}'")

        # Check and potentially create collections if they don't exist
        existing_collections = db.list_collection_names()
        logger.info(f"Existing collections: {existing_collections}")

        created_collections_count = 0
        for collection_name in required_collections:
            if collection_name not in existing_collections:
                try:
                    # Create collection (implicitly created on first insert, but explicit is possible)
                    # A common pattern is to just ensure it exists by listing it
                    # or performing a dummy operation if necessary.
                    # For simplicity, we'll rely on implicit creation when data is first added.
                    # If explicit creation is needed: db.create_collection(collection_name)
                    logger.info(f"Collection '{collection_name}' will be created upon first use.")
                    # You *could* explicitly create them here if needed:
                    # db.create_collection(collection_name)
                    # created_collections_count += 1
                except OperationFailure as e:
                    logger.error(f"Could not implicitly ensure collection '{collection_name}' exists (permissions?): {e}")
                except Exception as e:
                    logger.error(f"Error regarding collection '{collection_name}': {e}")

        # if created_collections_count > 0:
            # logger.info(f"Created {created_collections_count} new collections.")

        return db

    except ConfigurationError as e:
        logger.error(f"MongoDB Configuration Error: Check your MONGO_URI format and credentials. {e}")
        sys.exit("Database configuration error.")
    except ConnectionFailure as e:
        logger.error(f"MongoDB Connection Failure: Could not connect to server at {app.config['MONGO_HOST']}:{app.config['MONGO_PORT']}. Is it running? Firewall? {e}")
        sys.exit("Database connection failed.")
    except OperationFailure as e:
        logger.error(f"MongoDB Authentication Failure or Operation Error: Check user/password and permissions. {e}")
        # Depending on the error, you might want to sys.exit or handle differently
        # For now, we let the app start but DB operations will fail.
        # sys.exit("Database operation failed (likely auth).")
        return None # Indicate failure
    except Exception as e:
        logger.error(f"An unexpected error occurred during database initialization: {e}")
        sys.exit("Unexpected database error.")


def get_db():
    """Returns the database instance."""
    if db is None:
        # This case should ideally not happen if init_db is called correctly at startup
        # but can be a fallback or indicator of an issue.
        logger.warning("get_db() called before init_db() or init_db() failed.")
        # Attempt to initialize again or raise an error
        init_db(current_app) # Requires application context
        if db is None:
             raise RuntimeError("Database is not initialized.")
    return db