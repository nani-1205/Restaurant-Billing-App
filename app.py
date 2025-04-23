# -*- coding: utf-8 -*-
# restaurant_billing/app.py

import os
from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify,
    session # Session might be needed later for user auth, etc.
)
from pymongo import MongoClient, errors, DESCENDING
from bson import ObjectId
from datetime import datetime, timedelta # datetime needed for context processor
import config  # Import config variables
import traceback # For printing full tracebacks on generic exceptions

# --- Flask App Initialization ---
app = Flask(__name__)
app.config.from_object(config) # Load config from config.py
app.secret_key = app.config['SECRET_KEY'] # Needed for flash messages

# --- Database Setup ---
client = None
db = None

# --- Database Connection Function ---
def connect_db():
    """Establishes connection to MongoDB and ensures DB/Collections exist."""
    global client, db
    if client is None:
        try:
            # Use individual config variables to connect
            print(f"Attempting to connect to MongoDB at: {config.MONGO_IP}:{config.MONGO_PORT}")
            client = MongoClient(
                host=config.MONGO_IP,
                port=config.MONGO_PORT,
                username=config.MONGO_USERNAME,
                password=config.MONGO_PASSWORD,
                authSource=config.MONGO_AUTH_DB,
                # --- Add other options here ---
                serverSelectionTimeoutMS=5000, # Timeout for server selection
                connectTimeoutMS=10000,        # Connection timeout
                socketTimeoutMS=10000          # Socket operation timeout
                # Consider adding tls=True if connecting to Atlas or TLS-enabled DB
                # tlsAllowInvalidCertificates=True # USE WITH CAUTION for testing only
            )
            # The ismaster command is cheap and does not require auth. Validates connection.
            client.admin.command('ismaster')
            print("MongoDB connection successful.")

            db = client[config.MONGO_DB_NAME]
            print(f"Using database: {config.MONGO_DB_NAME}")

            # Ensure collections exist (MongoDB creates them on first use, but good to check)
            required_collections = ['menu_items', 'tables', 'orders', 'bills', 'users'] # Added users for potential future auth
            existing_collections = db.list_collection_names()
            for coll in required_collections:
                if coll not in existing_collections:
                    db.create_collection(coll)
                    print(f"Created collection: '{coll}'")
                    # Example Index (add more as needed):
                    if coll == 'orders':
                        try:
                            # Using pymongo constants is slightly more readable
                            db.orders.create_index([("status", 1)])
                            db.orders.create_index([("order_time", DESCENDING)])
                        except errors.OperationFailure as e:
                            print(f"Warning: Could not create index on 'orders': {e}")
                    if coll == 'bills':
                         try:
                            db.bills.create_index([("billed_at", DESCENDING)])
                         except errors.OperationFailure as e:
                            print(f"Warning: Could not create index on 'bills': {e}")
                    if coll == 'tables':
                         try:
                            # Ensure unique table numbers
                            db.tables.create_index([("table_number", 1)], unique=True)
                         except errors.OperationFailure as e:
                            print(f"Warning: Could not create unique index on 'tables': {e}")


        except errors.ConfigurationError as e:
             # This error usually happens if auth fails or config is wrong
             print(f"MongoDB configuration error: {e}")
             print("Ensure credentials, authSource, host, and port are correctly set and valid.")
             client = None
             db = None
        except errors.ConnectionFailure as e:
            print(f"MongoDB connection failed: {e}")
            print(f"Ensure MongoDB server at {config.MONGO_IP}:{config.MONGO_PORT} is running, accessible, and firewall rules allow connection.")
            client = None
            db = None
        except Exception as e:
            # Catch any other unexpected errors during setup
            print(f"An unexpected error occurred during DB setup: {e}")
            traceback.print_exc() # Print full traceback for debugging
            client = None
            db = None
    return db


# --- Request Hook for DB Connection ---
@app.before_request
def ensure_db_connection():
    """Check DB connection before each request and attempt reconnect if needed."""
    global db, client
    if db is not None and client is not None:
        try:
            # Ping the database to check connection status before each request
            client.admin.command('ping')
            return # Connection is good
        except (errors.ConnectionFailure, AttributeError, errors.OperationFailure) as e:
            print(f"DB connection lost or client invalid ({type(e).__name__}). Reconnecting before request...")
            db = None
            client = None
            # Fall through to attempt connection below
        except Exception as e:
             print(f"Unexpected error during DB ping check: {e}")
             traceback.print_exc()
             # Potentially risky to continue, force reconnect
             db = None
             client = None


    # If db is None or ping failed, try to connect/reconnect
    if get_db() is None:
         # If connection still fails, flash a persistent error message
         # Note: Flashing here might happen on every request if DB is down
         flash("CRITICAL: Database connection is unavailable. Please check logs or contact support.", "danger")
         # In a real app, you might render an error page or return 503 Service Unavailable
         # For now, we let the route handlers potentially fail later if they try to use db


# --- Helper Functions ---
def get_db():
    """Returns the database instance, calling connect_db() if not already connected."""
    global db
    if db is None:
        return connect_db()
    return db

def calculate_order_total(items):
    """Calculates subtotal, tax, and total for a list of order items.
       Excludes items marked as 'cancelled'.
    """
    if not items: # Handle case where items list might be None or empty
        return 0.0, 0.0, 0.0

    subtotal = sum(item.get('price', 0) * item.get('quantity', 0)
                   for item in items if item.get('status') != 'cancelled')
    tax = (subtotal * config.TAX_RATE_PERCENT) / 100.0
    total = subtotal + tax
    return round(subtotal, 2), round(tax, 2), round(total, 2) # Round for currency

# --- Context Processors ---
# Make variables available to all templates

@app.context_processor
def inject_config():
    """Injects config variables (safe ones) into template context."""
    # Be careful not to inject sensitive keys like SECRET_KEY or passwords
    safe_config = {
        'TAX_RATE_PERCENT': config.TAX_RATE_PERCENT
        # Add other safe config variables if needed in templates
    }
    return dict(config=safe_config)

@app.context_processor
def inject_current_year():
    """Injects the current year into all templates."""
    # Using UTC is generally safer for server-side timestamps
    return {'current_year': datetime.utcnow().year}


# --- Routes ---

@app.route('/')
def index():
    """Dashboard/Home Page"""
    db_instance = get_db()
    db_error_flag = db_instance is None # Correct way to check
    stats = {} # Initialize stats

    # Only try to access db if connection exists
    if not db_error_flag: # Equivalent to: if db_instance is not None:
        try:
            stats['open_orders'] = db_instance.orders.count_documents({"status": "open"})
            stats['available_tables'] = db_instance.tables.count_documents({"status": "available"})
            stats['pending_bills'] = db_instance.orders.count_documents({"status": "closed"})
            stats['menu_item_count'] = db_instance.menu_items.count_documents({})
        except Exception as e:
            print(f"Error fetching dashboard stats: {e}")
            flash("Could not fetch dashboard statistics due to a database issue.", "warning")
            db_error_flag = True # Mark DB as having issues if stats fail
    # No need for an else block here, db_error_flag is already set correctly

    # Pass the correct error flag to the template
    return render_template('index.html', stats=stats, db_error=db_error_flag)

# --- Menu Management ---
@app.route('/menu', methods=['GET', 'POST'])
def menu_manage():
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            name = request.form['name'].strip()
            description = request.form.get('description', '').strip() # Use get for optional field
            price_str = request.form['price']
            category = request.form.get('category', 'Uncategorized').strip()
            is_available = 'is_available' in request.form # Checkbox value

            if not name or not price_str:
                flash("Item name and price are required.", "warning")
                return redirect(url_for('menu_manage')) # Redirect back to show form

            price = float(price_str)
            if price < 0:
                flash("Price cannot be negative.", "warning")
                return redirect(url_for('menu_manage'))

            db_instance.menu_items.insert_one({
                "name": name,
                "description": description,
                "price": price,
                "category": category or "Uncategorized", # Default category if empty
                "is_available": is_available,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow() # Add updated_at on creation too
            })
            flash(f"Menu item '{name}' added successfully!", "success")
        except ValueError:
             flash("Invalid price format. Please enter a number.", "danger")
        except errors.PyMongoError as e:
            flash(f"Database error adding menu item: {e}", "danger")
        except Exception as e:
            flash(f"Error adding menu item: {e}", "danger")
            traceback.print_exc()
        return redirect(url_for('menu_manage'))

    # GET Request
    search_query = request.args.get('search', '').strip()
    query_filter = {}
    if search_query:
        # Case-insensitive search on name and category
        regex_query = {"$regex": search_query, "$options": "i"}
        query_filter = {"$or": [{"name": regex_query}, {"category": regex_query}]}

    items = [] # Initialize items list
    try:
        # Sort by category, then name
        items = list(db_instance.menu_items.find(query_filter).sort([("category", 1), ("name", 1)]))
    except errors.PyMongoError as e:
        flash(f"Database error fetching menu items: {e}", "danger")
    except Exception as e:
        flash(f"Error fetching menu items: {e}", "danger")
        traceback.print_exc()

    return render_template('menu_manage.html', items=items, search_query=search_query)

@app.route('/menu/edit/<item_id>', methods=['GET', 'POST'])
def menu_edit(item_id):
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('menu_manage'))

    try:
        obj_id = ObjectId(item_id)
    except Exception: # Invalid ObjectId format
        flash("Invalid item ID format.", "danger")
        return redirect(url_for('menu_manage'))

    item = None # Initialize item
    try:
        item = db_instance.menu_items.find_one({"_id": obj_id})
        if not item:
            flash("Menu item not found.", "warning")
            return redirect(url_for('menu_manage'))
    except errors.PyMongoError as e:
         flash(f"Database error fetching item: {e}", "danger")
         return redirect(url_for('menu_manage'))
    except Exception as e:
         flash(f"Error fetching item: {e}", "danger")
         traceback.print_exc()
         return redirect(url_for('menu_manage'))


    if request.method == 'POST':
        try:
            name = request.form['name'].strip()
            description = request.form.get('description', '').strip()
            price_str = request.form['price']
            category = request.form.get('category', 'Uncategorized').strip()
            is_available = 'is_available' in request.form

            if not name or not price_str:
                flash("Item name and price are required.", "warning")
                return render_template('menu_edit.html', item=item)

            price = float(price_str)
            if price < 0:
                 flash("Price cannot be negative.", "warning")
                 return render_template('menu_edit.html', item=item)


            db_instance.menu_items.update_one(
                {"_id": obj_id},
                {"$set": {
                    "name": name,
                    "description": description,
                    "price": price,
                    "category": category or "Uncategorized",
                    "is_available": is_available,
                    "updated_at": datetime.utcnow()
                }}
            )
            flash(f"Menu item '{item.get('name')}' updated successfully!", "success")
            return redirect(url_for('menu_manage'))
        except ValueError:
             flash("Invalid price format. Please enter a number.", "danger")
             return render_template('menu_edit.html', item=item) # Show form again
        except errors.PyMongoError as e:
             flash(f"Database error updating menu item: {e}", "danger")
             item = db_instance.menu_items.find_one({"_id": obj_id}) # Re-fetch
             return render_template('menu_edit.html', item=item)
        except Exception as e:
            flash(f"Error updating menu item: {e}", "danger")
            traceback.print_exc()
            item = db_instance.menu_items.find_one({"_id": obj_id}) # Re-fetch
            return render_template('menu_edit.html', item=item)

    # GET Request - Render the edit form
    return render_template('menu_edit.html', item=item)


@app.route('/menu/delete/<item_id>', methods=['POST'])
def menu_delete(item_id):
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('menu_manage'))

    try:
        obj_id = ObjectId(item_id)
        result = db_instance.menu_items.delete_one({"_id": obj_id})
        if result.deleted_count > 0:
            flash("Menu item deleted successfully!", "success")
        else:
            flash("Menu item not found or already deleted.", "warning")
    except errors.PyMongoError as e:
         flash(f"Database error deleting menu item: {e}", "danger")
    except Exception as e: # Catch ObjectId errors etc.
        flash(f"Error deleting menu item: {e}", "danger")
        traceback.print_exc()
    return redirect(url_for('menu_manage'))

@app.route('/menu/toggle_availability/<item_id>', methods=['POST'])
def menu_toggle_availability(item_id):
    db_instance = get_db()
    if not db_instance: return jsonify({"success": False, "error": "Database connection error."}), 500

    try:
        obj_id = ObjectId(item_id)
        item = db_instance.menu_items.find_one({"_id": obj_id}, {"is_available": 1})
        if item:
            new_status = not item.get('is_available', False)
            db_instance.menu_items.update_one(
                {"_id": obj_id},
                {"$set": {"is_available": new_status, "updated_at": datetime.utcnow()}}
            )
            return jsonify({"success": True, "new_status": new_status})
        else:
            return jsonify({"success": False, "error": "Item not found"}), 404
    except errors.PyMongoError as e:
         return jsonify({"success": False, "error": f"Database error: {e}"}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# --- Table Management ---
@app.route('/tables', methods=['GET', 'POST'])
def tables_manage():
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST': # Add new table
        try:
            table_number = request.form['table_number'].strip()
            capacity_str = request.form['capacity']

            if not table_number or not capacity_str:
                 flash("Table number and capacity are required.", "warning")
                 return redirect(url_for('tables_manage'))

            capacity = int(capacity_str)
            if capacity <= 0:
                 flash("Capacity must be a positive number.", "warning")
                 return redirect(url_for('tables_manage'))

            db_instance.tables.insert_one({
                "table_number": table_number,
                "capacity": capacity,
                "status": "available", # Default status
                "current_order_id": None,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
            flash(f"Table '{table_number}' added successfully!", "success")
        except ValueError:
            flash("Invalid capacity format. Please enter a whole number.", "danger")
        except errors.DuplicateKeyError:
             flash(f"Table number '{table_number}' already exists. Please choose a different number.", "warning")
        except errors.PyMongoError as e:
            flash(f"Database error adding table: {e}", "danger")
        except Exception as e:
            flash(f"Error adding table: {e}", "danger")
            traceback.print_exc()
        return redirect(url_for('tables_manage'))

    # GET Request
    tables = []
    try:
        tables = list(db_instance.tables.find().sort("table_number", 1))
    except errors.PyMongoError as e:
        flash(f"Database error fetching tables: {e}", "danger")
    except Exception as e:
        flash(f"Error fetching tables: {e}", "danger")
        traceback.print_exc()

    return render_template('tables_manage.html', tables=tables)

@app.route('/tables/update_status/<table_id>', methods=['POST'])
def table_update_status(table_id):
    db_instance = get_db()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    redirect_url = url_for('tables_manage')

    if not db_instance:
        message = "Database connection error."
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(redirect_url)

    try:
        obj_id = ObjectId(table_id)
        new_status = request.form.get('status')
        valid_statuses = ["available", "occupied", "reserved", "cleaning"]

        if not new_status or new_status not in valid_statuses:
            message = "Invalid status provided."
            if is_ajax: return jsonify({"success": False, "error": message}), 400
            else: flash(message, "warning"); return redirect(redirect_url)


        set_fields = {"status": new_status, "updated_at": datetime.utcnow()}
        unset_fields = {}

        if new_status == 'available':
             unset_fields["current_order_id"] = "" # Use $unset

        update_operation = {}
        if set_fields: update_operation["$set"] = set_fields
        if unset_fields: update_operation["$unset"] = unset_fields

        if not update_operation:
             message = "No update needed for table status."
             if is_ajax: return jsonify({"success": True, "message": message}), 200
             else: flash(message, "info"); return redirect(redirect_url)


        result = db_instance.tables.update_one({"_id": obj_id}, update_operation)

        if result.matched_count > 0:
            message = f"Table status updated to '{new_status}'."
            if is_ajax: return jsonify({"success": True, "message": message, "new_status": new_status})
            else: flash(message, "info"); return redirect(redirect_url)
        else:
            message = "Table not found."
            if is_ajax: return jsonify({"success": False, "error": message}), 404
            else: flash(message, "warning"); return redirect(redirect_url)

    except errors.PyMongoError as e:
         error_msg = f"Database error updating table status: {e}"
         if is_ajax: return jsonify({"success": False, "error": error_msg}), 500
         else: flash(error_msg, "danger"); return redirect(redirect_url)
    except Exception as e:
        error_msg = f"Error updating table status: {e}"
        traceback.print_exc()
        if is_ajax: return jsonify({"success": False, "error": error_msg}), 500
        else: flash(error_msg, "danger"); return redirect(redirect_url)

@app.route('/tables/delete/<table_id>', methods=['POST'])
def table_delete(table_id):
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('tables_manage'))

    table_number_for_flash = ""
    try:
        obj_id = ObjectId(table_id)
        table = db_instance.tables.find_one({"_id": obj_id})
        if table:
            table_number_for_flash = table.get('table_number', '')
            if table.get("status") == "occupied":
                 flash(f"Cannot delete Table {table_number_for_flash} while it is occupied. Close the order first.", "warning")
                 return redirect(url_for('tables_manage'))
        else:
             flash("Table not found.", "warning")
             return redirect(url_for('tables_manage'))

        result = db_instance.tables.delete_one({"_id": obj_id})
        if result.deleted_count > 0:
            flash(f"Table {table_number_for_flash} deleted successfully!", "success")
        else:
            flash("Table deletion failed unexpectedly.", "warning")
    except errors.PyMongoError as e:
         flash(f"Database error deleting table: {e}", "danger")
    except Exception as e:
        flash(f"Error deleting table: {e}", "danger")
        traceback.print_exc()
    return redirect(url_for('tables_manage'))


# --- Order Management ---
@app.route('/order/new/<table_id>', methods=['GET', 'POST'])
def order_new(table_id):
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('tables_manage'))

    table = None
    try:
        table_obj_id = ObjectId(table_id)
        table = db_instance.tables.find_one({"_id": table_obj_id})
        if not table:
            flash("Table not found.", "warning")
            return redirect(url_for('tables_manage'))

        # --- POST Request ---
        if request.method == 'POST':
            # Check table status FIRST within the POST block
            if table.get('status') != 'available':
                flash(f"Table {table.get('table_number')} is not available (Status: {table.get('status')}). Cannot start new order.", "warning")
                return redirect(url_for('tables_manage'))

            # --- CORRECT INDENTATION STARTS HERE ---
            # This block only runs if method is POST *and* table is available
            order_items = [] # <--- Correctly indented
            items_processed_count = 0
            warnings = []

            # Process initial items from the form
            for key, value in request.form.items():
                if key.startswith("item_") and value and value != '0':
                    try:
                        quantity = int(value)
                        if quantity > 0:
                            # Extract item ID from 'item_xxxx...'
                            item_id_str = key.split("_", 1)[1]
                            menu_item = db_instance.menu_items.find_one({"_id": ObjectId(item_id_str)})
                            if menu_item and menu_item.get('is_available'):
                                order_item = {
                                    "menu_item_id": menu_item['_id'],
                                    "name": menu_item['name'],
                                    "price": menu_item['price'],
                                    "quantity": quantity,
                                    "status": "pending"
                                }
                                order_items.append(order_item)
                                items_processed_count += 1
                            elif menu_item:
                                warnings.append(f"Item '{menu_item.get('name', item_id_str)}' is unavailable.")
                            else:
                                warnings.append(f"Item ID {item_id_str} not found.")
                    except (ValueError, IndexError) as e:
                         warnings.append(f"Invalid data submitted for field {key}: {e}")
                    except errors.PyMongoError as e:
                         warnings.append(f"Database error processing item {key}: {e}")
                    except Exception as e: # Catch ObjectId errors etc.
                         warnings.append(f"Error processing item {key}: {type(e).__name__}")
                         print(f"Error processing {key}: {e}") # Log detailed error
                         traceback.print_exc()

            # Flash warnings *before* creating order
            for warning in warnings:
                flash(f"Warning: {warning}", "warning")

            # Calculate totals and create order
            subtotal, tax, total = calculate_order_total(order_items)
            new_order = {
                "table_id": table_obj_id,
                "table_number": table["table_number"],
                "items": order_items,
                "status": "open",
                "order_time": datetime.utcnow(),
                "subtotal": subtotal,
                "tax": tax,
                "total_amount": total,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            result = db_instance.orders.insert_one(new_order)
            new_order_id = result.inserted_id

            # Update table status
            db_instance.tables.update_one(
                {"_id": table_obj_id},
                {"$set": {"status": "occupied", "current_order_id": new_order_id, "updated_at": datetime.utcnow()}}
            )

            flash(f"New order (ID: {new_order_id}) started for Table {table.get('table_number')} with {items_processed_count} item(s).", "success")
            return redirect(url_for('order_view', order_id=str(new_order_id)))
            # --- END OF POST / AVAILABLE BLOCK ---

        # --- GET Request ---
        # Prevent new order form display if table is not available
        if table.get('status') != 'available':
             # Check if there's an existing OPEN order for this table if occupied
             if table.get('status') == 'occupied' and table.get('current_order_id'):
                 try:
                    # Make sure current_order_id is a valid ObjectId before querying
                    existing_order = db_instance.orders.find_one({"_id": ObjectId(table['current_order_id']), "status": "open"})
                    if existing_order:
                        flash(f"Table {table.get('table_number')} is occupied. Redirecting to existing order.", "info")
                        return redirect(url_for('order_view', order_id=str(existing_order['_id'])))
                    else:
                        # Inconsistent state: Table occupied but no linked open order found
                        flash(f"Table {table.get('table_number')} marked occupied, but linked order not open/found.", "warning")
                        return redirect(url_for('tables_manage'))
                 except Exception as e:
                      flash(f"Error checking existing order for table {table.get('table_number')}: {e}", "danger")
                      traceback.print_exc()
                      return redirect(url_for('tables_manage'))
             else:
                # Handles 'reserved', 'cleaning', etc. statuses
                flash(f"Table {table.get('table_number')} is not available (Status: {table.get('status')}).", "warning")
                return redirect(url_for('tables_manage'))

        # If GET and table is available, show the form
        menu_items = list(db_instance.menu_items.find({"is_available": True}).sort([("category", 1), ("name", 1)]))
        return render_template('order_new.html', table=table, menu_items=menu_items)

    except errors.PyMongoError as e:
         flash(f"Database error processing order request: {e}", "danger")
         return redirect(url_for('tables_manage'))
    except Exception as e: # Catch ObjectId errors etc.
        flash(f"Error processing order request: {e}", "danger")
        traceback.print_exc()
        return redirect(url_for('tables_manage'))


@app.route('/order/view/<order_id>', methods=['GET'])
def order_view(order_id):
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('index'))

    order = None
    categorized_menu_items = []
    try:
        obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": obj_id})

        if not order:
            flash("Order not found.", "warning")
            return redirect(url_for('index'))

        pipeline = [
            {"$match": {"is_available": True}},
            {"$sort": {"category": 1, "name": 1}},
            {"$group": { "_id": "$category", "items": {"$push": {"_id": "$_id", "name": "$name", "price": "$price"}} }},
            {"$sort": {"_id": 1}}
        ]
        categorized_menu_items = list(db_instance.menu_items.aggregate(pipeline))

        subtotal, tax, total = calculate_order_total(order.get('items', []))
        order['subtotal'] = subtotal
        order['tax'] = tax
        order['total_amount'] = total

    except errors.PyMongoError as e:
        flash(f"Database error loading order: {e}", "danger")
        return redirect(url_for('index'))
    except Exception as e:
        flash(f"Invalid order ID or error loading order: {e}", "danger")
        traceback.print_exc()
        return redirect(url_for('index'))

    return render_template('order_view.html', order=order, categorized_menu_items=categorized_menu_items)

@app.route('/order/add_item/<order_id>', methods=['POST'])
def order_add_item(order_id):
    db_instance = get_db()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    redirect_url = request.referrer or url_for('order_view', order_id=order_id)

    if not db_instance:
        message = "Database connection error."
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(redirect_url)

    try:
        order_obj_id = ObjectId(order_id)
        menu_item_id_str = request.form.get('menu_item_id')
        quantity_str = request.form.get('quantity', '1')

        if not menu_item_id_str or not quantity_str:
             message = "Missing menu item or quantity."
             if is_ajax: return jsonify({"success": False, "error": message}), 400
             else: flash(message, "warning"); return redirect(redirect_url)

        quantity = int(quantity_str)
        if quantity <= 0:
            message = "Quantity must be positive."
            if is_ajax: return jsonify({"success": False, "error": message}), 400
            else: flash(message, "warning"); return redirect(redirect_url)

        menu_item_obj_id = ObjectId(menu_item_id_str)
        menu_item = db_instance.menu_items.find_one({"_id": menu_item_obj_id})

        if not menu_item:
             message = "Menu item not found."
             if is_ajax: return jsonify({"success": False, "error": message}), 404
             else: flash(message, "warning"); return redirect(redirect_url)
        if not menu_item.get('is_available'):
             message = f"Item '{menu_item.get('name')}' is currently unavailable."
             if is_ajax: return jsonify({"success": False, "error": message}), 400
             else: flash(message, "warning"); return redirect(redirect_url)

        order = db_instance.orders.find_one({"_id": order_obj_id}, {"status": 1})
        if not order or order.get("status") != "open":
            message = "Cannot add items to an order that is not open."
            if is_ajax: return jsonify({"success": False, "error": message}), 400
            else: flash(message, "warning"); return redirect(redirect_url)

        order_item = {
            "menu_item_id": menu_item['_id'], "name": menu_item['name'],
            "price": menu_item['price'], "quantity": quantity, "status": "pending"
        }

        update_result = db_instance.orders.update_one(
            {"_id": order_obj_id, "status": "open"},
            {"$push": {"items": order_item}, "$set": {"updated_at": datetime.utcnow()}}
        )

        if update_result.modified_count == 0:
             message = "Failed to add item. Order might have been closed or modified."
             if is_ajax: return jsonify({"success": False, "error": message}), 409
             else: flash(message, "warning"); return redirect(redirect_url)

        order = db_instance.orders.find_one({"_id": order_obj_id}, {"items": 1})
        subtotal, tax, total = calculate_order_total(order.get('items', []))
        db_instance.orders.update_one(
             {"_id": order_obj_id},
             {"$set": {"subtotal": subtotal, "tax": tax, "total_amount": total, "updated_at": datetime.utcnow()}}
         )

        message = f"Added {quantity} x {menu_item['name']} to order."
        if is_ajax:
            return jsonify({"success": True, "message": message, "item": order_item,
                            "subtotal": subtotal, "tax": tax, "total": total})
        else:
            flash(message, "success"); return redirect(redirect_url)

    except ValueError:
         message = "Invalid quantity provided."
         if is_ajax: return jsonify({"success": False, "error": message}), 400
         else: flash(message, "danger"); return redirect(redirect_url)
    except errors.PyMongoError as e:
        message = f"Database error adding item: {e}"
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(redirect_url)
    except Exception as e:
        message = f"Error adding item: {e}"
        traceback.print_exc()
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(redirect_url)


@app.route('/order/update_item_status/<order_id>/<int:item_index>', methods=['POST'])
def order_update_item_status(order_id, item_index):
    db_instance = get_db()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    default_redirect = url_for('kds')
    if request.referrer and 'order/view' in request.referrer:
        default_redirect = url_for('order_view', order_id=order_id)


    if not db_instance:
        message = "Database connection error."
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(request.referrer or default_redirect)

    try:
        order_obj_id = ObjectId(order_id)
        new_status = request.form.get('status')
        valid_statuses = ["pending", "preparing", "served", "cancelled"]

        if new_status not in valid_statuses:
             message = "Invalid item status provided."
             if is_ajax: return jsonify({"success": False, "error": message}), 400
             else: flash(message, "warning"); return redirect(request.referrer or default_redirect)

        update_key = f"items.{item_index}.status"
        result = db_instance.orders.update_one(
            {"_id": order_obj_id, f"items.{item_index}": {"$exists": True}},
            {"$set": {update_key: new_status, "updated_at": datetime.utcnow()}}
        )

        subtotal, tax, total = None, None, None

        if result.matched_count > 0:
            message = f"Item #{item_index+1} status updated to '{new_status}'."
            if new_status == 'cancelled':
                order = db_instance.orders.find_one({"_id": order_obj_id}, {"items":1})
                subtotal, tax, total = calculate_order_total(order.get('items', []))
                db_instance.orders.update_one(
                     {"_id": order_obj_id},
                     {"$set": {"subtotal": subtotal, "tax": tax, "total_amount": total, "updated_at": datetime.utcnow()}}
                 )
                message = f"Item #{item_index+1} cancelled. Order totals updated."

            if is_ajax:
                 return jsonify({
                     "success": True, "message": message, "new_status": new_status,
                     "subtotal": subtotal, "tax": tax, "total": total
                 })
            else:
                 flash(message, "success")
                 return redirect(request.referrer or default_redirect)
        else:
            message = "Order or item index not found, or update failed."
            if is_ajax: return jsonify({"success": False, "error": message}), 404
            else: flash(message, "warning"); return redirect(request.referrer or default_redirect)

    except errors.PyMongoError as e:
        message = f"Database error updating item status: {e}"
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(request.referrer or default_redirect)
    except Exception as e:
        message = f"Error updating item status: {e}"
        traceback.print_exc()
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(request.referrer or default_redirect)


@app.route('/order/close/<order_id>', methods=['POST'])
def order_close(order_id):
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(request.referrer or url_for('index'))

    try:
        obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": obj_id})

        if not order:
             flash("Order not found.", "warning")
             return redirect(url_for('index'))

        if order['status'] != 'open':
            flash(f"Order is already {order['status']}. Cannot close again.", "info")
            if order['status'] == 'closed': return redirect(url_for('billing'))
            if order['status'] == 'billed': return redirect(url_for('bill_view', order_id=order_id))
            return redirect(url_for('order_view', order_id=order_id))

        active_items = [item for item in order.get('items', []) if item.get('status') != 'cancelled']
        if not active_items:
            flash("Cannot close an order with no active items.", "warning")
            return redirect(url_for('order_view', order_id=order_id))

        subtotal, tax, total = calculate_order_total(order.get('items', []))

        update_result = db_instance.orders.update_one(
            {"_id": obj_id, "status": "open"},
            {"$set": {
                "status": "closed", "closed_time": datetime.utcnow(),
                "subtotal": subtotal, "tax": tax, "total_amount": total,
                "updated_at": datetime.utcnow()
                }}
        )

        if update_result.modified_count > 0:
            flash("Order closed and ready for billing.", "success")
            return redirect(url_for('billing'))
        else:
             flash("Failed to close order. Status might have changed.", "warning")
             return redirect(url_for('order_view', order_id=order_id))


    except errors.PyMongoError as e:
         flash(f"Database error closing order: {e}", "danger")
         return redirect(request.referrer or url_for('index'))
    except Exception as e:
        flash(f"Error closing order: {e}", "danger")
        traceback.print_exc()
        return redirect(request.referrer or url_for('index'))


# --- Billing & Invoicing ---
@app.route('/billing')
def billing():
    db_instance = get_db()
    db_error_flag = db_instance is None # Check if db is None
    closed_orders = []

    if not db_error_flag: # Only query if db connection exists
        try:
            closed_orders = list(db_instance.orders.find({"status": "closed"})
                               .sort("closed_time", DESCENDING))
        except errors.PyMongoError as e:
            flash(f"Database error fetching pending bills: {e}", "danger")
            db_error_flag = True
        except Exception as e:
            flash(f"Error fetching pending bills: {e}", "danger")
            traceback.print_exc()
            db_error_flag = True
    # No need for else block, before_request handles initial connection flash

    return render_template('billing.html', orders=closed_orders, db_error=db_error_flag)

@app.route('/bill/view/<order_id>')
def bill_view(order_id):
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('billing'))

    order = None
    bill = None
    try:
        obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": obj_id})

        if not order:
            flash("Order not found.", "warning")
            return redirect(url_for('billing'))

        if order.get('status') not in ['closed', 'billed']:
             flash(f"Order status is '{order.get('status')}'. Bill view/finalize requires 'closed' or 'billed'.", "warning")
             if order.get('status') == 'open': return redirect(url_for('order_view', order_id=order_id))
             else: return redirect(url_for('index'))

        bill_query = {}
        if order.get('final_bill_id'): bill_query = {"_id": order['final_bill_id']}
        else: bill_query = {"order_id": obj_id}
        bill = db_instance.bills.find_one(bill_query)

        subtotal, tax, total = calculate_order_total(order.get('items', []))
        order['subtotal'] = subtotal
        order['tax'] = tax
        order['total_amount'] = total

    except errors.PyMongoError as e:
        flash(f"Database error loading bill view: {e}", "danger")
        return redirect(url_for('billing'))
    except Exception as e:
        flash(f"Invalid order ID or error loading bill: {e}", "danger")
        traceback.print_exc()
        return redirect(url_for('billing'))

    return render_template('bill_view.html', order=order, bill=bill, tax_rate=config.TAX_RATE_PERCENT)

@app.route('/bill/finalize/<order_id>', methods=['POST'])
def bill_finalize(order_id):
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('billing'))

    redirect_url = url_for('bill_view', order_id=order_id)

    try:
        order_obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": order_obj_id})

        if not order:
            flash("Order not found.", "warning")
            return redirect(url_for('billing'))

        if order.get('status') != 'closed':
            flash(f"Cannot finalize bill. Order status is '{order.get('status')}' (must be 'closed').", "warning")
            return redirect(redirect_url)

        bill_query = {}
        if order.get('final_bill_id'): bill_query = {"_id": order['final_bill_id']}
        else: bill_query = {"order_id": order_obj_id}
        existing_bill = db_instance.bills.find_one(bill_query)
        if existing_bill:
            flash(f"Bill for order {order_id} already finalized.", "warning")
            return redirect(redirect_url)


        payment_method = request.form.get('payment_method', 'Cash').strip()
        discount_str = request.form.get('discount', '0.0').strip()

        discount = float(discount_str) if discount_str else 0.0
        if discount < 0:
             flash("Discount cannot be negative.", "warning")
             return redirect(redirect_url)

        subtotal = order.get('subtotal', 0.0)
        tax = order.get('tax', 0.0)
        original_total = order.get('total_amount', 0.0)

        final_total_amount = round(max(0, original_total - discount), 2)

        bill_doc = {
            "order_id": order['_id'], "table_number": order['table_number'],
            "items": [item for item in order.get('items', []) if item.get('status') != 'cancelled'],
            "subtotal": subtotal, "tax": tax, "tax_rate_percent": config.TAX_RATE_PERCENT,
            "discount": round(discount, 2), "total_amount": final_total_amount,
            "payment_method": payment_method, "payment_status": "paid",
            "billed_at": datetime.utcnow()
        }
        bill_result = db_instance.bills.insert_one(bill_doc)
        final_bill_id = bill_result.inserted_id

        db_instance.orders.update_one(
            {"_id": order_obj_id},
            {"$set": {"status": "billed", "final_bill_id": final_bill_id, "updated_at": datetime.utcnow()}}
        )

        if order.get('table_id'):
             db_instance.tables.update_one(
                 {"_id": order['table_id']},
                 {"$set": {"status": "available", "updated_at": datetime.utcnow()}, "$unset": {"current_order_id": ""}}
                 )
        else:
             print(f"Warning: table_id missing in order {order_id}. Updating table {order.get('table_number')} by number.")
             db_instance.tables.update_one(
                 {"table_number": order.get('table_number')},
                 {"$set": {"status": "available", "updated_at": datetime.utcnow()}, "$unset": {"current_order_id": ""}}
                 )

        flash(f"Bill for Order {order_id} finalized! Amount: ${final_total_amount:.2f}, Payment: {payment_method}.", "success")
        return redirect(url_for('bill_view', order_id=order_id))

    except ValueError:
        flash("Invalid discount value. Please enter a number.", "danger")
        return redirect(redirect_url)
    except errors.PyMongoError as e:
        flash(f"Database error finalizing bill: {e}", "danger")
        traceback.print_exc()
        return redirect(redirect_url)
    except Exception as e:
        flash(f"Error finalizing bill: {e}", "danger")
        traceback.print_exc()
        return redirect(redirect_url)


# --- Kitchen Display System (KDS) ---
@app.route('/kds')
def kds():
    db_instance = get_db()
    db_error_flag = db_instance is None
    kds_items = []

    if not db_error_flag:
        try:
            open_orders = list(db_instance.orders.find(
                    {"status": "open"},
                    {"_id": 1, "table_number": 1, "items": 1, "order_time": 1}
                ).sort("order_time", 1))

            for order in open_orders:
                order_id_str = str(order['_id'])
                for index, item in enumerate(order.get('items', [])):
                    if item.get('status') in ['pending', 'preparing']:
                        kds_items.append({
                            "order_id": order_id_str, "table_number": order.get('table_number', 'N/A'),
                            "item_name": item.get('name', 'Unknown Item'), "quantity": item.get('quantity', 0),
                            "status": item.get('status'), "item_index": index,
                            "order_time": order.get('order_time')
                        })

            kds_items.sort(key=lambda x: (x['order_time'] or datetime.min, x['status'] == 'pending'))

        except errors.PyMongoError as e:
            flash(f"Database error fetching KDS items: {e}", "danger")
            db_error_flag = True
        except Exception as e:
            flash(f"Error fetching KDS items: {e}", "danger")
            traceback.print_exc()
            db_error_flag = True
    # No else needed, db_error_flag handles template rendering

    return render_template('kds.html', kds_items=kds_items, db_error=db_error_flag)


# --- Analytics & Reporting ---
@app.route('/reports')
def reports():
    db_instance = get_db()
    report_data = {}
    db_error_flag = db_instance is None

    if db_error_flag:
        # Before_request already flashed
        return render_template('reports.html', report_data=report_data, db_error=True)

    try:
        # --- Today's Sales ---
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        pipeline_today = [
            {"$match": {"billed_at": {"$gte": today_start, "$lt": today_end}, "payment_status": "paid"}},
            {"$group": {"_id": None, "total_sales": {"$sum": "$total_amount"}, "count": {"$sum": 1}, "total_discount": {"$sum": "$discount"}}},
            {"$project": {"_id": 0, "total_sales": {"$ifNull": ["$total_sales", 0]}, "count": {"$ifNull": ["$count", 0]}, "total_discount": {"$ifNull": ["$total_discount", 0]}}}
        ]
        today_sales_result = list(db_instance.bills.aggregate(pipeline_today))
        today_sales = today_sales_result[0] if today_sales_result else {"total_sales": 0, "count": 0, "total_discount": 0}

        report_data["today_total_sales"] = today_sales.get('total_sales', 0)
        report_data["today_bill_count"] = today_sales.get('count', 0)
        report_data["today_total_discount"] = today_sales.get('total_discount', 0)

        # --- Top 5 Selling Items (All Time by Quantity) ---
        pipeline_top_items = [
             {"$match": {"payment_status": "paid"}},
             {"$unwind": "$items"},
             {"$group": {"_id": "$items.name", "total_quantity": {"$sum": "$items.quantity"}, "total_revenue": {"$sum": {"$multiply": ["$items.price", "$items.quantity"]}} }},
             {"$sort": {"total_quantity": -1}},
             {"$limit": 5}
        ]
        top_items = list(db_instance.bills.aggregate(pipeline_top_items))
        report_data["top_selling_items"] = top_items

        report_data["sales_by_category"] = [] # Placeholder

    except errors.PyMongoError as e:
        flash(f"Database error generating reports: {e}", "danger")
        db_error_flag = True
    except Exception as e:
        flash(f"Error generating reports: {e}", "danger")
        traceback.print_exc()
        db_error_flag = True


    return render_template('reports.html', report_data=report_data, db_error=db_error_flag)


# --- Main Execution ---
if __name__ == '__main__':
    print("--- Restaurant Billing App ---")
    # Attempt initial DB connection on startup
    if connect_db() is not None: # Correct check
        # --- Connection successful ---
        print(f"Successfully connected to database '{config.MONGO_DB_NAME}'.")
        print(f"Flask ENV: {config.FLASK_ENV}")
        print(f"Debug Mode: {config.DEBUG}")
        print(f"Starting Flask server on http://0.0.0.0:5000...")

        # Note: app.run() is for development. Use WSGI server in production.
        try:
            # Set use_reloader=False if running under PM2 or similar process managers
            use_reloader = config.DEBUG # Only use reloader if DEBUG is True
            print(f"Flask internal reloader: {'Enabled' if use_reloader else 'Disabled'}")
            app.run(host='0.0.0.0', port=5000, debug=config.DEBUG, use_reloader=use_reloader)
        except KeyboardInterrupt:
            print("\nFlask server stopped by user.")
        except Exception as e:
            print(f"\nError running Flask server: {e}")
            traceback.print_exc()
            exit(1) # Exit if server fails to run
    else:
        # --- Connection failed on startup ---
        print("\n--- FATAL ERROR ---")
        print("Failed to connect to the MongoDB database on startup.")
        print("Please check your MongoDB server status and the configuration in config.py / environment variables.")
        print("Exiting application.")
        exit(1) # Exit if DB connection fails at start

    # Production deployment comments:
    # Ensure DEBUG is False and FLASK_ENV is 'production' in your environment
    # Use a production-ready WSGI server like Waitress or Gunicorn:
    # Example using Waitress: waitress-serve --host=0.0.0.0 --port=5000 app:app
    # Example using Gunicorn: gunicorn --bind 0.0.0.0:5000 --workers=4 app:app