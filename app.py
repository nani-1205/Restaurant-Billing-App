# -*- coding: utf-8 -*-
# restaurant_billing/app.py

import os
from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify,
    session # Session might be needed later for user auth, etc.
)
from pymongo import MongoClient, errors, DESCENDING
from bson import ObjectId
from datetime import datetime, timedelta # timedelta might be useful for reports
import config  # Import config variables

# --- Flask App Initialization ---
app = Flask(__name__)
app.config.from_object(config) # Load config from config.py
app.secret_key = app.config['SECRET_KEY'] # Needed for flash messages

# --- Database Setup ---
client = None
db = None

def connect_db():
    """Establishes connection to MongoDB and ensures DB/Collections exist."""
    global client, db
    if client is None:
        try:
            print(f"Attempting to connect to MongoDB at: {config.MONGO_IP}:{config.MONGO_PORT}")
            # Added connectTimeoutMS and socketTimeoutMS for better control
            client = MongoClient(
                config.MONGO_URI,
                serverSelectionTimeoutMS=5000, # Timeout for server selection
                connectTimeoutMS=10000,        # Connection timeout
                socketTimeoutMS=10000          # Socket operation timeout
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
                    # Consider adding indexes here if needed, e.g., for performance
                    db.create_collection(coll)
                    print(f"Created collection: '{coll}'")
                    # Example Index (add more as needed):
                    if coll == 'orders':
                        db.orders.create_index([("status", 1)])
                        db.orders.create_index([("order_time", DESCENDING)])
                    if coll == 'bills':
                         db.bills.create_index([("billed_at", DESCENDING)])
                    if coll == 'tables':
                         db.tables.create_index([("table_number", 1)], unique=True) # Ensure unique table numbers


        except errors.ConfigurationError as e:
             print(f"MongoDB configuration error: {e}")
             print("Ensure MONGO_URI is correct and credentials are valid.")
             client = None
             db = None
        except errors.ConnectionFailure as e:
            print(f"MongoDB connection failed: {e}")
            print("Ensure MongoDB server is running and accessible.")
            client = None
            db = None
        except Exception as e:
            print(f"An unexpected error occurred during DB setup: {e}")
            client = None
            db = None
    return db

# Call connect_db() when the application context is available
# This ensures DB connection happens before the first request
@app.before_request
def ensure_db_connection():
    get_db()


# --- Helper Functions ---
def get_db():
    """Returns the database instance, attempting to reconnect if necessary."""
    global db, client
    if db is None:
        print("DB instance is None, attempting to reconnect...")
        return connect_db()
    # Optional: Add a ping check here for long-running apps to ensure connection is live
    try:
        # Ping the database to check connection status
        client.admin.command('ping')
    except (errors.ConnectionFailure, AttributeError): # AttributeError if client is None
        print("DB connection lost or client not initialized. Reconnecting...")
        db = None # Reset db
        client = None # Reset client
        return connect_db() # Attempt to reconnect
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

# Add context processor to make config vars available in templates if needed
@app.context_processor
def inject_config():
    return dict(config=config)

# --- Routes ---

@app.route('/')
def index():
    """Dashboard/Home Page"""
    db_instance = get_db()
    if not db_instance:
        # Flash message handled by before_request if connection fails initially
        # But we still need to handle the case where it fails later.
        flash("Database connection error. Please check configuration and MongoDB status.", "danger")
        return render_template('index.html', db_error=True)

    # Fetch some basic stats for the dashboard
    stats = {}
    try:
        stats['open_orders'] = db_instance.orders.count_documents({"status": "open"})
        stats['available_tables'] = db_instance.tables.count_documents({"status": "available"})
        stats['pending_bills'] = db_instance.orders.count_documents({"status": "closed"})
        stats['menu_item_count'] = db_instance.menu_items.count_documents({})
    except Exception as e:
        print(f"Error fetching dashboard stats: {e}")
        flash("Could not fetch dashboard statistics due to a database issue.", "warning")

    return render_template('index.html', stats=stats)

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
        return redirect(url_for('menu_manage'))

    # GET Request
    search_query = request.args.get('search', '').strip()
    query_filter = {}
    if search_query:
        # Case-insensitive search on name and category
        regex_query = {"$regex": search_query, "$options": "i"}
        query_filter = {"$or": [{"name": regex_query}, {"category": regex_query}]}

    try:
        items = list(db_instance.menu_items.find(query_filter).sort([("category", 1), ("name", 1)])) # Sort by category, then name
    except errors.PyMongoError as e:
        flash(f"Database error fetching menu items: {e}", "danger")
        items = []
    except Exception as e:
        flash(f"Error fetching menu items: {e}", "danger")
        items = []

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

    item = db_instance.menu_items.find_one({"_id": obj_id})
    if not item:
        flash("Menu item not found.", "warning")
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
                # Rerender form with current item data and error
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
            flash(f"Menu item '{item.get('name')}' updated successfully!", "success") # Use original name in flash
            return redirect(url_for('menu_manage'))
        except ValueError:
             flash("Invalid price format. Please enter a number.", "danger")
             # Rerender form with current item data and error
             # Need to fetch item again or pass it if update failed mid-way
             item = db_instance.menu_items.find_one({"_id": obj_id}) # Re-fetch potentially modified data
             return render_template('menu_edit.html', item=item)
        except errors.PyMongoError as e:
             flash(f"Database error updating menu item: {e}", "danger")
             item = db_instance.menu_items.find_one({"_id": obj_id}) # Re-fetch
             return render_template('menu_edit.html', item=item)
        except Exception as e:
            flash(f"Error updating menu item: {e}", "danger")
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
    return redirect(url_for('menu_manage'))

@app.route('/menu/toggle_availability/<item_id>', methods=['POST'])
def menu_toggle_availability(item_id):
    db_instance = get_db()
    if not db_instance: return jsonify({"success": False, "error": "Database connection error."}), 500

    try:
        obj_id = ObjectId(item_id)
        # Atomically find and update using find_one_and_update might be slightly better
        item = db_instance.menu_items.find_one({"_id": obj_id}, {"is_available": 1}) # Only fetch availability
        if item:
            new_status = not item.get('is_available', False) # Safely get current status
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

            # Check if table number already exists (case-insensitive check might be desired depending on reqs)
            # Using the unique index added during setup is the primary defense
            # if db_instance.tables.find_one({"table_number": {"$regex": f"^{table_number}$", "$options": "i"}}):
            #    flash(f"Table number '{table_number}' already exists (case-insensitive).", "warning")
            #    return redirect(url_for('tables_manage'))

            db_instance.tables.insert_one({
                "table_number": table_number,
                "capacity": capacity,
                "status": "available", # Default status
                "current_order_id": None, # Track associated order when occupied
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
            flash(f"Table '{table_number}' added successfully!", "success")
        except ValueError:
            flash("Invalid capacity format. Please enter a whole number.", "danger")
        except errors.DuplicateKeyError: # Catch unique index violation
             flash(f"Table number '{table_number}' already exists. Please choose a different number.", "warning")
        except errors.PyMongoError as e:
            flash(f"Database error adding table: {e}", "danger")
        except Exception as e:
            flash(f"Error adding table: {e}", "danger")
        return redirect(url_for('tables_manage'))

    # GET Request
    try:
        # Sort tables numerically if possible, otherwise alphabetically
        tables = list(db_instance.tables.find().sort("table_number"))
    except errors.PyMongoError as e:
        flash(f"Database error fetching tables: {e}", "danger")
        tables = []
    except Exception as e:
        flash(f"Error fetching tables: {e}", "danger")
        tables = []

    return render_template('tables_manage.html', tables=tables)

@app.route('/tables/update_status/<table_id>', methods=['POST'])
def table_update_status(table_id):
    db_instance = get_db()
    if not db_instance: return jsonify({"success": False, "error": "Database connection error."}), 500

    try:
        obj_id = ObjectId(table_id)
        new_status = request.form.get('status')
        valid_statuses = ["available", "occupied", "reserved", "cleaning"] # Example statuses

        if not new_status or new_status not in valid_statuses:
            return jsonify({"success": False, "error": "Invalid status provided."}), 400

        # Logic: If setting to 'available', ensure no open order is linked.
        # If setting to 'occupied', maybe require an order to be started? (Handled in order_new)
        update_fields = {"status": new_status, "updated_at": datetime.utcnow()}
        if new_status == 'available':
            # Clear the current order ID when table becomes available
             update_fields["current_order_id"] = None

        result = db_instance.tables.update_one(
            {"_id": obj_id},
            {"$set": update_fields}
        )

        if result.matched_count > 0:
            flash(f"Table status updated to '{new_status}'.", "info") # Use flash for page reloads
            # Return JSON only if called via AJAX, otherwise redirect
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                 return jsonify({"success": True, "new_status": new_status})
            else:
                 return redirect(url_for('tables_manage')) # Redirect if it's a standard form post
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                 return jsonify({"success": False, "error": "Table not found"}), 404
            else:
                 flash("Table not found.", "warning")
                 return redirect(url_for('tables_manage'))

    except errors.PyMongoError as e:
         error_msg = f"Database error updating table status: {e}"
         if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
             return jsonify({"success": False, "error": error_msg}), 500
         else:
             flash(error_msg, "danger")
             return redirect(url_for('tables_manage'))
    except Exception as e:
        error_msg = f"Error updating table status: {e}"
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
             return jsonify({"success": False, "error": error_msg}), 500
        else:
             flash(error_msg, "danger")
             return redirect(url_for('tables_manage'))

@app.route('/tables/delete/<table_id>', methods=['POST'])
def table_delete(table_id):
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('tables_manage'))

    try:
        obj_id = ObjectId(table_id)
        # Prevent deleting occupied tables as a safety measure
        table = db_instance.tables.find_one({"_id": obj_id})
        if table and table.get("status") == "occupied":
             flash(f"Cannot delete Table {table.get('table_number', '')} while it is occupied. Please close or cancel the associated order first.", "warning")
             return redirect(url_for('tables_manage'))
        # Add check for 'reserved' or other non-deletable states if needed

        result = db_instance.tables.delete_one({"_id": obj_id})
        if result.deleted_count > 0:
            flash(f"Table {table.get('table_number', '')} deleted successfully!", "success")
        else:
            flash("Table not found or already deleted.", "warning")
    except errors.PyMongoError as e:
         flash(f"Database error deleting table: {e}", "danger")
    except Exception as e: # Catch ObjectId errors etc.
        flash(f"Error deleting table: {e}", "danger")
    return redirect(url_for('tables_manage'))


# --- Order Management ---
@app.route('/order/new/<table_id>', methods=['GET', 'POST'])
def order_new(table_id):
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('tables_manage'))

    try:
        table_obj_id = ObjectId(table_id)
        table = db_instance.tables.find_one({"_id": table_obj_id})
        if not table:
            flash("Table not found.", "warning")
            return redirect(url_for('tables_manage'))

        # --- POST Request ---
        if request.method == 'POST':
             # Double-check table status before creating order
            if table['status'] != 'available':
                flash(f"Table {table['table_number']} is not available (Status: {table['status']}). Cannot start new order.", "warning")
                return redirect(url_for('tables_manage'))

            # Process initial items submitted from the form
            order_items = []
            items_processed_count = 0
            warnings = []

            for key, value in request.form.items():
                if key.startswith("item_") and value: # Check if it's an item quantity field with a value
                    try:
                        quantity = int(value)
                        if quantity > 0:
                            item_id_str = key.split("_", 1)[1] # Extract item ID from 'item_xxxx...'
                            menu_item = db_instance.menu_items.find_one({"_id": ObjectId(item_id_str)})
                            if menu_item and menu_item.get('is_available'):
                                order_item = {
                                    "menu_item_id": menu_item['_id'],
                                    "name": menu_item['name'],
                                    "price": menu_item['price'],
                                    "quantity": quantity,
                                    "status": "pending" # Initial KDS status
                                }
                                order_items.append(order_item)
                                items_processed_count += 1
                            elif menu_item:
                                warnings.append(f"Item '{menu_item.get('name', item_id_str)}' is currently unavailable.")
                            else:
                                warnings.append(f"Item ID {item_id_str} not found.")
                    except (ValueError, IndexError):
                        warnings.append(f"Invalid data submitted for field {key}.")
                    except errors.PyMongoError as e:
                         warnings.append(f"Database error processing item {key}: {e}")
                    except Exception as e: # Catch ObjectId errors etc.
                         warnings.append(f"Error processing item {key}: {e}")

            # Flash any warnings accumulated during item processing
            for warning in warnings:
                flash(f"Warning: {warning}", "warning")

            # Calculate initial totals based on successfully added items
            subtotal, tax, total = calculate_order_total(order_items)

            new_order = {
                "table_id": table_obj_id,
                "table_number": table["table_number"],
                "items": order_items, # Use processed items
                "status": "open",
                "order_time": datetime.utcnow(),
                "subtotal": subtotal,
                "tax": tax,
                "total_amount": total,
                "created_at": datetime.utcnow(), # Track creation time
                "updated_at": datetime.utcnow()  # Track last update time
            }
            result = db_instance.orders.insert_one(new_order)
            new_order_id = result.inserted_id

            # Update table status to occupied and link the order ID
            db_instance.tables.update_one(
                {"_id": table_obj_id},
                {"$set": {
                    "status": "occupied",
                    "current_order_id": new_order_id,
                    "updated_at": datetime.utcnow()
                    }}
            )

            flash(f"New order (ID: {new_order_id}) started for Table {table['table_number']} with {items_processed_count} item(s).", "success")
            return redirect(url_for('order_view', order_id=str(new_order_id)))

        # --- GET Request ---
        # Prevent new order form display if table is not available
        if table['status'] != 'available':
             # Check if there's an existing OPEN order for this table if occupied
             if table['status'] == 'occupied' and table.get('current_order_id'):
                 existing_order = db_instance.orders.find_one({"_id": table['current_order_id'], "status": "open"})
                 if existing_order:
                     flash(f"Table {table['table_number']} is occupied. Redirecting to existing order.", "info")
                     return redirect(url_for('order_view', order_id=str(existing_order['_id'])))
                 else:
                     # Inconsistent state: Table occupied but no linked open order found
                     flash(f"Table {table['table_number']} is marked occupied, but the linked order is not open or not found. Please check table status or order history.", "warning")
                     # Optionally, attempt to fix status here or just redirect
                     # db_instance.tables.update_one({"_id": table_obj_id}, {"$set": {"status": "available", "current_order_id": None}})
                     return redirect(url_for('tables_manage'))
             else:
                flash(f"Table {table['table_number']} is not available (Status: {table['status']}). Cannot start a new order.", "warning")
                return redirect(url_for('tables_manage'))

        # If GET and table is available, show the form to select initial items
        menu_items = list(db_instance.menu_items.find({"is_available": True}).sort([("category", 1), ("name", 1)]))
        return render_template('order_new.html', table=table, menu_items=menu_items)

    except errors.PyMongoError as e:
         flash(f"Database error processing order request: {e}", "danger")
         return redirect(url_for('tables_manage'))
    except Exception as e: # Catch ObjectId errors etc.
        flash(f"Error processing order request: {e}", "danger")
        return redirect(url_for('tables_manage'))


@app.route('/order/view/<order_id>', methods=['GET'])
def order_view(order_id):
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        # Determine a better redirect target, maybe an orders list page?
        return redirect(url_for('index'))

    try:
        obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": obj_id})

        if not order:
            flash("Order not found.", "warning")
            return redirect(url_for('index')) # Or orders list page

        # Fetch available menu items for the "Add More Items" form
        # Group items by category for the dropdown
        pipeline = [
            {"$match": {"is_available": True}},
            {"$sort": {"category": 1, "name": 1}},
            {"$group": {
                "_id": "$category",
                "items": {"$push": {"_id": "$_id", "name": "$name", "price": "$price"}}
            }},
            {"$sort": {"_id": 1}} # Sort categories alphabetically
        ]
        categorized_menu_items = list(db_instance.menu_items.aggregate(pipeline))


        # Ensure current totals are up-to-date in the order document (or calculate on the fly)
        # It's often better to calculate fresh here to avoid stale data issues
        subtotal, tax, total = calculate_order_total(order.get('items', []))
        order['subtotal'] = subtotal # Pass calculated values to template
        order['tax'] = tax
        order['total_amount'] = total

        return render_template('order_view.html', order=order, categorized_menu_items=categorized_menu_items)

    except errors.PyMongoError as e:
        flash(f"Database error loading order: {e}", "danger")
        return redirect(url_for('index'))
    except Exception as e: # Catch ObjectId errors etc.
        flash(f"Invalid order ID or error loading order: {e}", "danger")
        return redirect(url_for('index'))

@app.route('/order/add_item/<order_id>', methods=['POST'])
def order_add_item(order_id):
    db_instance = get_db()
    # Use flash for regular POST, JSON for potential AJAX
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not db_instance:
        message = "Database connection error."
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(request.referrer or url_for('index'))

    try:
        order_obj_id = ObjectId(order_id)
        menu_item_id_str = request.form.get('menu_item_id')
        quantity_str = request.form.get('quantity', '1') # Default quantity to 1

        if not menu_item_id_str or not quantity_str:
             message = "Missing menu item or quantity."
             if is_ajax: return jsonify({"success": False, "error": message}), 400
             else: flash(message, "warning"); return redirect(url_for('order_view', order_id=order_id))

        quantity = int(quantity_str)
        if quantity <= 0:
            message = "Quantity must be positive."
            if is_ajax: return jsonify({"success": False, "error": message}), 400
            else: flash(message, "warning"); return redirect(url_for('order_view', order_id=order_id))

        menu_item_obj_id = ObjectId(menu_item_id_str)
        menu_item = db_instance.menu_items.find_one({"_id": menu_item_obj_id})

        if not menu_item:
             message = "Menu item not found."
             if is_ajax: return jsonify({"success": False, "error": message}), 404
             else: flash(message, "warning"); return redirect(url_for('order_view', order_id=order_id))
        if not menu_item.get('is_available'):
             message = f"Item '{menu_item.get('name')}' is currently unavailable."
             if is_ajax: return jsonify({"success": False, "error": message}), 400
             else: flash(message, "warning"); return redirect(url_for('order_view', order_id=order_id))

        # Check if order is still open
        order = db_instance.orders.find_one({"_id": order_obj_id}, {"status": 1})
        if not order or order.get("status") != "open":
            message = "Cannot add items to an order that is not open."
            if is_ajax: return jsonify({"success": False, "error": message}), 400
            else: flash(message, "warning"); return redirect(url_for('order_view', order_id=order_id))


        order_item = {
            # Consider adding a unique ID per item instance if needed for complex edits later
            # "item_instance_id": ObjectId(),
            "menu_item_id": menu_item['_id'],
            "name": menu_item['name'],
            "price": menu_item['price'],
            "quantity": quantity,
            "status": "pending" # KDS Status: 'pending', 'preparing', 'served', 'cancelled'
        }

        # Add the item and update totals atomically if possible, or in sequence
        # Using $push and then recalculating is simpler here
        update_result = db_instance.orders.update_one(
            {"_id": order_obj_id, "status": "open"}, # Ensure still open
            {
                "$push": {"items": order_item},
                "$set": {"updated_at": datetime.utcnow()} # Mark order as updated
            }
        )

        if update_result.modified_count == 0:
             # This could happen if the order status changed between the check and the update
             message = "Failed to add item. Order might have been closed or modified."
             if is_ajax: return jsonify({"success": False, "error": message}), 409 # 409 Conflict
             else: flash(message, "warning"); return redirect(url_for('order_view', order_id=order_id))


        # Recalculate totals after adding
        order = db_instance.orders.find_one({"_id": order_obj_id}) # Get updated order data
        subtotal, tax, total = calculate_order_total(order.get('items', []))
        db_instance.orders.update_one(
             {"_id": order_obj_id},
             {"$set": {"subtotal": subtotal, "tax": tax, "total_amount": total, "updated_at": datetime.utcnow()}}
         )

        message = f"Added {quantity} x {menu_item['name']} to order."
        if is_ajax: return jsonify({"success": True, "message": message, "item": order_item}) # Maybe return updated totals too
        else: flash(message, "success"); return redirect(url_for('order_view', order_id=order_id))

    except ValueError:
         message = "Invalid quantity provided."
         if is_ajax: return jsonify({"success": False, "error": message}), 400
         else: flash(message, "danger"); return redirect(url_for('order_view', order_id=order_id))
    except errors.PyMongoError as e:
        message = f"Database error adding item: {e}"
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(url_for('order_view', order_id=order_id))
    except Exception as e: # Catch ObjectId errors etc.
        message = f"Error adding item: {e}"
        print(f"Error adding item: {e}") # Log for debugging
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(url_for('order_view', order_id=order_id))


@app.route('/order/update_item_status/<order_id>/<int:item_index>', methods=['POST'])
def order_update_item_status(order_id, item_index):
    """Updates the KDS status of a specific item within an order."""
    db_instance = get_db()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not db_instance:
        message = "Database connection error."
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(request.referrer or url_for('index'))

    try:
        order_obj_id = ObjectId(order_id)
        new_status = request.form.get('status')
        # KDS statuses: 'pending', 'preparing', 'served'
        # Cancellation status: 'cancelled' (Handled slightly differently as it affects totals)
        valid_statuses = ["pending", "preparing", "served", "cancelled"]

        if new_status not in valid_statuses:
             message = "Invalid item status provided."
             if is_ajax: return jsonify({"success": False, "error": message}), 400
             else: flash(message, "warning"); return redirect(request.referrer or url_for('index'))

        # Target the specific item using its index in the array
        update_key = f"items.{item_index}.status"
        result = db_instance.orders.update_one(
            # Query ensures order exists and the item at the index exists
            {"_id": order_obj_id, f"items.{item_index}": {"$exists": True}},
            {"$set": {update_key: new_status, "updated_at": datetime.utcnow()}}
        )

        if result.matched_count > 0:
            # If the item was cancelled, recalculate order totals
            if new_status == 'cancelled':
                # Fetch the updated order to recalculate
                order = db_instance.orders.find_one({"_id": order_obj_id})
                subtotal, tax, total = calculate_order_total(order.get('items', []))
                db_instance.orders.update_one(
                     {"_id": order_obj_id},
                     {"$set": {"subtotal": subtotal, "tax": tax, "total_amount": total, "updated_at": datetime.utcnow()}}
                 )
                message = f"Item #{item_index+1} cancelled. Order totals updated."
            else:
                 message = f"Item #{item_index+1} status updated to '{new_status}'."


            if is_ajax: return jsonify({"success": True, "message": message, "new_status": new_status})
            else: flash(message, "success"); return redirect(request.referrer or url_for('kds')) # Sensible redirect
        else:
            message = "Order or item index not found, or update failed."
            if is_ajax: return jsonify({"success": False, "error": message}), 404
            else: flash(message, "warning"); return redirect(request.referrer or url_for('index'))

    except errors.PyMongoError as e:
        message = f"Database error updating item status: {e}"
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(request.referrer or url_for('index'))
    except Exception as e: # Catch ObjectId errors etc.
        message = f"Error updating item status: {e}"
        print(f"Error updating item status: {e}") # Log for debugging
        if is_ajax: return jsonify({"success": False, "error": message}), 500
        else: flash(message, "danger"); return redirect(request.referrer or url_for('index'))


@app.route('/order/close/<order_id>', methods=['POST'])
def order_close(order_id):
    """Marks an order as 'closed', ready for billing."""
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(request.referrer or url_for('index'))

    try:
        obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": obj_id})

        if not order:
             flash("Order not found.", "warning")
             return redirect(url_for('index')) # Or orders list page

        if order['status'] != 'open':
            flash(f"Order is already {order['status']}. Cannot close again.", "info")
            # Redirect to appropriate place depending on status
            if order['status'] == 'closed': return redirect(url_for('billing'))
            if order['status'] == 'billed': return redirect(url_for('bill_view', order_id=order_id))
            return redirect(url_for('order_view', order_id=order_id))

        # Basic check: Ensure there are non-cancelled items before closing
        active_items = [item for item in order.get('items', []) if item.get('status') != 'cancelled']
        if not active_items:
            flash("Cannot close an order with no active items.", "warning")
            return redirect(url_for('order_view', order_id=order_id))

        # Optional Strict check: Ensure all non-cancelled items are 'served'
        # all_served = all(item.get('status') == 'served' for item in active_items)
        # if not all_served:
        #     flash("Cannot close order: Not all active items are marked as 'served'. Please check KDS status.", "warning")
        #     return redirect(url_for('order_view', order_id=order_id))

        # Recalculate final totals just before closing
        subtotal, tax, total = calculate_order_total(order.get('items', []))

        update_result = db_instance.orders.update_one(
            {"_id": obj_id, "status": "open"}, # Ensure status didn't change concurrently
            {"$set": {
                "status": "closed",
                "closed_time": datetime.utcnow(),
                "subtotal": subtotal,
                "tax": tax,
                "total_amount": total,
                "updated_at": datetime.utcnow()
                }}
        )

        if update_result.modified_count > 0:
            # Don't change table status yet, only when bill is paid/finalized
            flash("Order closed and ready for billing.", "success")
            return redirect(url_for('billing')) # Redirect to the billing queue
        else:
             # This might happen if status changed between find and update
             flash("Failed to close order. Status might have changed.", "warning")
             return redirect(url_for('order_view', order_id=order_id))


    except errors.PyMongoError as e:
         flash(f"Database error closing order: {e}", "danger")
         return redirect(request.referrer or url_for('index'))
    except Exception as e: # Catch ObjectId errors etc.
        flash(f"Error closing order: {e}", "danger")
        print(f"Error closing order: {e}") # Log
        return redirect(request.referrer or url_for('index'))


# --- Billing & Invoicing ---
@app.route('/billing')
def billing():
    """Lists orders that are 'closed' and ready for billing."""
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('index'))

    try:
        # Fetch closed orders, maybe sort by closed time or table number
        closed_orders = list(db_instance.orders.find({"status": "closed"})
                           .sort("closed_time", DESCENDING)) # Newest closed first
    except errors.PyMongoError as e:
        flash(f"Database error fetching pending bills: {e}", "danger")
        closed_orders = []
    except Exception as e:
        flash(f"Error fetching pending bills: {e}", "danger")
        closed_orders = []

    return render_template('billing.html', orders=closed_orders)

@app.route('/bill/view/<order_id>')
def bill_view(order_id):
    """Shows the bill details for a closed or already billed order."""
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('billing'))

    try:
        obj_id = ObjectId(order_id)
        # Fetch the order regardless of status first
        order = db_instance.orders.find_one({"_id": obj_id})

        if not order:
            flash("Order not found.", "warning")
            return redirect(url_for('billing'))

        # Allow viewing if closed or billed
        if order['status'] not in ['closed', 'billed']:
             flash(f"Order status is '{order['status']}'. Bill can only be viewed/finalized for 'closed' or 'billed' orders.", "warning")
             # Redirect back to order view if still open
             if order['status'] == 'open':
                 return redirect(url_for('order_view', order_id=order_id))
             else: # Other statuses like cancelled?
                  return redirect(url_for('index')) # Or a dedicated order history page

        # Check if a bill record already exists (for displaying payment info)
        bill = db_instance.bills.find_one({"order_id": obj_id})

        # Use the totals stored in the order (or recalculate for display if paranoid)
        subtotal, tax, total = calculate_order_total(order.get('items', []))
        order['subtotal'] = subtotal # Ensure template gets potentially recalculated values
        order['tax'] = tax
        order['total_amount'] = total

        return render_template('bill_view.html', order=order, bill=bill, tax_rate=config.TAX_RATE_PERCENT)

    except errors.PyMongoError as e:
        flash(f"Database error loading bill view: {e}", "danger")
        return redirect(url_for('billing'))
    except Exception as e: # Catch ObjectId errors etc.
        flash(f"Invalid order ID or error loading bill: {e}", "danger")
        return redirect(url_for('billing'))

@app.route('/bill/finalize/<order_id>', methods=['POST'])
def bill_finalize(order_id):
    """Marks the bill as paid, updates order/table status, creates a final bill record."""
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return redirect(url_for('billing'))

    try:
        order_obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": order_obj_id})

        if not order:
            flash("Order not found.", "warning")
            return redirect(url_for('billing'))

        # Crucially, only allow finalization if the order is 'closed'
        if order['status'] != 'closed':
            flash(f"Cannot finalize bill. Order status is '{order['status']}' (must be 'closed').", "warning")
            return redirect(url_for('bill_view', order_id=order_id))

        # Check if a bill *already* exists for this order to prevent double billing
        existing_bill = db_instance.bills.find_one({"order_id": order_obj_id})
        if existing_bill:
            flash(f"Bill for this order (ID: {order_id}) has already been finalized.", "warning")
            return redirect(url_for('bill_view', order_id=order_id))


        payment_method = request.form.get('payment_method', 'Cash').strip()
        discount_str = request.form.get('discount', '0.0').strip()

        discount = float(discount_str) if discount_str else 0.0
        if discount < 0:
             flash("Discount cannot be negative.", "warning")
             return redirect(url_for('bill_view', order_id=order_id))

        # Use the totals stored in the order (which were calculated when closed)
        subtotal = order.get('subtotal', 0.0)
        tax = order.get('tax', 0.0)
        original_total = order.get('total_amount', 0.0)

        # Calculate final amount after discount
        final_total_amount = original_total - discount
        if final_total_amount < 0:
             final_total_amount = 0 # Prevent negative total

        final_total_amount = round(final_total_amount, 2) # Round final amount

        # Create the immutable Bill Document
        bill_doc = {
            "order_id": order['_id'],
            "table_number": order['table_number'],
            # Copy only active items at time of billing
            "items": [item for item in order.get('items', []) if item.get('status') != 'cancelled'],
            "subtotal": subtotal,
            "tax": tax,
            "tax_rate_percent": config.TAX_RATE_PERCENT,
            "discount": round(discount, 2),
            "total_amount": final_total_amount,
            "payment_method": payment_method,
            "payment_status": "paid", # Assume paid on finalize
            "billed_at": datetime.utcnow()
            # Add user ID if implementing user auth: "billed_by": session.get('user_id')
        }
        bill_result = db_instance.bills.insert_one(bill_doc)

        # Update Order Status to 'billed'
        db_instance.orders.update_one(
            {"_id": order_obj_id},
            {"$set": {"status": "billed", "final_bill_id": bill_result.inserted_id, "updated_at": datetime.utcnow()}}
        )

        # Update Table Status to 'available' (or 'cleaning' could be an option)
        # Ensure table_id exists in the order document
        if order.get('table_id'):
             db_instance.tables.update_one(
                 {"_id": order['table_id']},
                 {"$set": {"status": "available", "updated_at": datetime.utcnow()}, "$unset": {"current_order_id": ""}} # Remove link to order
                 )
        else:
             # Fallback: Try finding table by number if ID is missing (less reliable)
             print(f"Warning: table_id missing in order {order_id}. Trying to update table {order['table_number']} by number.")
             db_instance.tables.update_one(
                 {"table_number": order['table_number']},
                 {"$set": {"status": "available", "updated_at": datetime.utcnow()}, "$unset": {"current_order_id": ""}}
                 )

        flash(f"Bill for Order {order_id} finalized successfully! Amount: ${final_total_amount:.2f}, Payment: {payment_method}.", "success")
        # Redirect to bill view or back to billing list? Bill view shows confirmation.
        return redirect(url_for('bill_view', order_id=order_id))

    except ValueError:
        flash("Invalid discount value. Please enter a number.", "danger")
        return redirect(url_for('bill_view', order_id=order_id))
    except errors.PyMongoError as e:
        flash(f"Database error finalizing bill: {e}", "danger")
        print(f"Database error finalizing bill: {e}") # Log the error
        return redirect(url_for('bill_view', order_id=order_id))
    except Exception as e: # Catch ObjectId errors etc.
        flash(f"Error finalizing bill: {e}", "danger")
        print(f"Error finalizing bill: {e}") # Log the error
        return redirect(url_for('bill_view', order_id=order_id))


# --- Kitchen Display System (KDS) ---
@app.route('/kds')
def kds():
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return render_template('kds.html', kds_items=[], db_error=True)

    kds_items = []
    try:
        # Find all 'open' orders and project only necessary fields + unwind items
        pipeline = [
            {"$match": {"status": "open"}}, # Only open orders
            {"$unwind": "$items"}, # Create a doc for each item in the order
            {"$match": {"items.status": {"$in": ["pending", "preparing"]}}}, # Only items needing kitchen action
            {"$project": { # Select and reshape fields
                "_id": 0, # Exclude original order _id from item doc
                "order_id": "$_id",
                "table_number": "$table_number",
                "item_name": "$items.name",
                "quantity": "$items.quantity",
                "status": "$items.status",
                "menu_item_id": "$items.menu_item_id",
                # Need index for update_item_status link: This requires finding index *before* unwind or passing item instance ID
                # Let's rebuild the list with index after fetching orders
                "order_time": "$order_time"
            }},
            {"$sort": {"order_time": 1, "status": -1}} # Oldest orders first, 'preparing' before 'pending'
        ]
        # Simpler approach: fetch orders, then iterate in Python to add index
        open_orders = list(db_instance.orders.find(
                {"status": "open"},
                {"_id": 1, "table_number": 1, "items": 1, "order_time": 1} # Projection
            ).sort("order_time", 1)) # Oldest first

        for order in open_orders:
            order_id_str = str(order['_id'])
            for index, item in enumerate(order.get('items', [])):
                if item.get('status') in ['pending', 'preparing']:
                    kds_item = {
                        "order_id": order_id_str,
                        "table_number": order.get('table_number', 'N/A'),
                        "item_name": item.get('name', 'Unknown Item'),
                        "quantity": item.get('quantity', 0),
                        "status": item.get('status'),
                        "item_index": index, # Crucial for the update link
                        "order_time": order.get('order_time')
                    }
                    kds_items.append(kds_item)

        # Optional secondary sort in Python if needed (e.g., put 'preparing' first)
        kds_items.sort(key=lambda x: (x['order_time'] or datetime.min, x['status'] == 'pending'))

    except errors.PyMongoError as e:
        flash(f"Database error fetching KDS items: {e}", "danger")
        return render_template('kds.html', kds_items=[], db_error=True)
    except Exception as e:
        flash(f"Error fetching KDS items: {e}", "danger")
        print(f"Error fetching KDS items: {e}") # Log
        return render_template('kds.html', kds_items=[], db_error=True)


    return render_template('kds.html', kds_items=kds_items)


# --- Analytics & Reporting ---
@app.route('/reports')
def reports():
    db_instance = get_db()
    if not db_instance:
        flash("Database connection error.", "danger")
        return render_template('reports.html', report_data={}, db_error=True)

    report_data = {}
    try:
        # --- Today's Sales ---
        # Define date range for today (UTC)
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1) # Start of next day

        pipeline_today = [
            {"$match": {
                "billed_at": {"$gte": today_start, "$lt": today_end},
                "payment_status": "paid" # Ensure we only count paid bills
            }},
            {"$group": {
                "_id": None, # Group all matched docs into one result
                "total_sales": {"$sum": "$total_amount"},
                "count": {"$sum": 1}, # Count number of bills
                "total_discount": {"$sum": "$discount"} # Sum discounts
            }}
        ]
        today_sales_result = list(db_instance.bills.aggregate(pipeline_today))
        today_sales = today_sales_result[0] if today_sales_result else {"total_sales": 0, "count": 0, "total_discount": 0}
        report_data["today_total_sales"] = today_sales.get('total_sales', 0)
        report_data["today_bill_count"] = today_sales.get('count', 0)
        report_data["today_total_discount"] = today_sales.get('total_discount', 0)


        # --- Top 5 Selling Items (All Time by Quantity) ---
        pipeline_top_items = [
             {"$match": {"payment_status": "paid"}}, # Only paid bills contribute to sales stats
             {"$unwind": "$items"}, # Deconstruct the items array
             # Items array in 'bills' should already exclude cancelled ones based on finalize logic
             # {"$match": {"items.status": {"$ne": "cancelled"}}}, # Redundant if finalize logic is correct
             {"$group": {
                 "_id": "$items.name", # Group by item name
                 "total_quantity": {"$sum": "$items.quantity"},
                 "total_revenue": {"$sum": {"$multiply": ["$items.price", "$items.quantity"]}} # Calculate revenue per item
             }},
             {"$sort": {"total_quantity": -1}}, # Sort by quantity descending
             {"$limit": 5}
        ]
        top_items = list(db_instance.bills.aggregate(pipeline_top_items))
        report_data["top_selling_items"] = top_items


        # --- Sales by Category (All Time) ---
        pipeline_sales_category = [
             {"$match": {"payment_status": "paid"}},
             {"$unwind": "$items"},
             # Need category info - ideally store it in the bill item, or join with menu_items
             # Assuming category is NOT stored in bill item (less ideal), let's skip for now
             # If category WAS stored:
             # {"$group": {
             #     "_id": "$items.category", # Group by item category
             #     "total_revenue": {"$sum": {"$multiply": ["$items.price", "$items.quantity"]}},
             #     "total_quantity": {"$sum": "$items.quantity"}
             # }},
             # {"$sort": {"total_revenue": -1}}
        ]
        # sales_by_category = list(db_instance.bills.aggregate(pipeline_sales_category))
        # report_data["sales_by_category"] = sales_by_category
        report_data["sales_by_category"] = [] # Placeholder


    except errors.PyMongoError as e:
        flash(f"Database error generating reports: {e}", "danger")
        report_data = {} # Clear partial data on error
        return render_template('reports.html', report_data=report_data, db_error=True)
    except Exception as e:
        flash(f"Error generating reports: {e}", "danger")
        print(f"Error generating reports: {e}") # Log
        report_data = {} # Clear partial data on error
        return render_template('reports.html', report_data=report_data, db_error=True)


    return render_template('reports.html', report_data=report_data)


# --- Main Execution ---
if __name__ == '__main__':
    print("--- Restaurant Billing App ---")
    # Attempt initial DB connection on startup
    if connect_db():
        print(f"Successfully connected to database '{config.MONGO_DB_NAME}'.")
        print(f"Starting Flask development server on http://0.0.0.0:5000...")
        # Use host='0.0.0.0' to make it accessible on your network
        # Use debug=True only for development
        app.run(host='0.0.0.0', port=5000, debug=app.config['DEBUG'])
    else:
        print("\n--- FATAL ERROR ---")
        print("Failed to connect to the MongoDB database on startup.")
        print("Please check your MongoDB server status and the configuration in config.py / environment variables.")
        print("Exiting application.")
        exit(1) # Exit if DB connection fails at start

    # For production deployment, use a production-ready WSGI server:
    # Example using Waitress:
    # 1. pip install waitress
    # 2. Run: waitress-serve --host=0.0.0.0 --port=5000 app:app
    # Example using Gunicorn (Linux/macOS):
    # 1. pip install gunicorn
    # 2. Run: gunicorn --bind 0.0.0.0:5000 app:app