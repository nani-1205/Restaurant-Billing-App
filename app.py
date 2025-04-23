import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from pymongo import MongoClient, errors
from bson import ObjectId
from datetime import datetime
import config # Import config variables

app = Flask(__name__)
app.config.from_object(config) # Load config from config.py
app.secret_key = app.config['SECRET_KEY'] # Needed for flash messages

# --- Database Setup ---
client = None
db = None

def connect_db():
    """Establishes connection to MongoDB and ensures DB/Collections exist."""
    global client, db
    # Only attempt connection if client is not already established
    # Check if client is None OR if client is set but server is not available (e.g., after network issue)
    needs_connection = client is None
    if not needs_connection and client is not None:
        try:
            # Quick check if server is still reachable
            client.admin.command('ping')
        except (errors.ConnectionFailure, errors.ServerSelectionTimeoutError, AttributeError):
             print("Existing client connection lost, will attempt reconnect.")
             needs_connection = True
             client = None # Reset client
             db = None # Reset db

    if needs_connection:
        try:
            print(f"Attempting to connect to MongoDB using URI from config...")
            # Ensure MONGO_URI is correctly constructed in config.py
            client = MongoClient(
                config.MONGO_URI,
                serverSelectionTimeoutMS=5000 # Timeout after 5 seconds
            )
            # The ismaster command is cheap and does not require auth.
            client.admin.command('ismaster')
            print("MongoDB connection successful.")

            db = client[config.MONGO_DB_NAME]
            print(f"Using database: {config.MONGO_DB_NAME}")

            # Ensure collections exist (MongoDB creates them on first use, but good to check)
            # Check only if db object was successfully created
            if db is not None:
                required_collections = ['menu_items', 'tables', 'orders', 'bills']
                existing_collections = db.list_collection_names()
                for coll in required_collections:
                    if coll not in existing_collections:
                        db.create_collection(coll)
                        print(f"Created collection: '{coll}'")

        except errors.ServerSelectionTimeoutError as e:
            print(f"MongoDB connection failed (Timeout): {e}")
            # Don't print URI directly if it contains password, use masked version from config printout if needed.
            # print(f"Attempted URI: {config.MONGO_URI}") # Be careful with passwords
            client = None
            db = None
        except errors.ConnectionFailure as e:
            print(f"MongoDB connection failed (ConnectionFailure): {e}")
            # print(f"Attempted URI: {config.MONGO_URI}") # Be careful with passwords
            client = None
            db = None
        except Exception as e:
            print(f"An error occurred during DB setup: {e}")
            client = None
            db = None
    return db

# Call connect_db() when the application context is available
# This ensures DB connection attempt happens within Flask's context handling
@app.before_request
def before_request_func():
    get_db() # Ensures DB connection is attempted before each request

# --- Helper Functions ---
def get_db():
    """Returns the database instance, attempting to reconnect if necessary."""
    global db, client
    if db is None: # CORRECT CHECK
        print("DB connection is None, attempting to reconnect...")
        return connect_db()

    # Optional: Add a ping check here for long-running apps to verify connection
    try:
        # Ping the database
        # Use client.admin.command('ping') for synchronous PyMongo
        client.admin.command('ping')
    except (errors.ConnectionFailure, errors.ServerSelectionTimeoutError, AttributeError) as e:
         # Catch potential issues if client is None or connection lost
        print(f"DB connection lost ({type(e).__name__}), attempting to reconnect...")
        db = None # Reset db state
        client = None # Reset client state
        return connect_db() # Try to reconnect
    return db

def calculate_order_total(items):
    """Calculates subtotal, tax, and total for a list of order items."""
    subtotal = sum(item['price'] * item['quantity'] for item in items if item.get('status') != 'cancelled')
    tax = (subtotal * config.TAX_RATE_PERCENT) / 100.0
    total = subtotal + tax
    return subtotal, tax, total

# --- Routes ---

@app.route('/')
def index():
    """Dashboard/Home Page"""
    db_instance = get_db()
    db_error_flag = db_instance is None # CORRECT CHECK (already was)
    if db_instance is None: # CORRECT CHECK
        flash("Database connection error. Please check configuration and MongoDB status.", "danger")
        # Still render the template but indicate the error
        return render_template('index.html', db_error=True)
    # Add some basic stats later if needed
    return render_template('index.html', db_error=False)

# --- Menu Management ---
@app.route('/menu', methods=['GET', 'POST'])
def menu_manage():
    db_instance = get_db()
    db_error_flag = db_instance is None
    if db_instance is None: # CORRECT CHECK
        flash("Database connection error.", "danger")
        # If GET, show error on page. If POST, redirect.
        if request.method == 'POST':
             return redirect(url_for('menu_manage'))
        # For GET allow rendering with error
        return render_template('menu_manage.html', items=[], search_query='', db_error=True)


    if request.method == 'POST':
        try:
            name = request.form['name']
            description = request.form['description']
            price = float(request.form['price'])
            category = request.form['category']
            is_available = 'is_available' in request.form # Checkbox value

            if not name or price < 0:
                flash("Item name and non-negative price are required.", "warning")
            else:
                db_instance.menu_items.insert_one({
                    "name": name,
                    "description": description,
                    "price": price,
                    "category": category,
                    "is_available": is_available,
                    "created_at": datetime.utcnow()
                })
                flash(f"Menu item '{name}' added successfully!", "success")
        except ValueError:
             flash("Invalid price format. Please enter a number.", "danger")
        except Exception as e:
            flash(f"Error adding menu item: {e}", "danger")
            print(f"Error adding menu item: {e}") # Log error
        return redirect(url_for('menu_manage'))

    # GET Request
    search_query = request.args.get('search', '')
    query_filter = {}
    items = [] # Default to empty list
    if search_query:
        query_filter = {
            "$or": [
                {"name": {"$regex": search_query, "$options": "i"}},
                {"category": {"$regex": search_query, "$options": "i"}}
            ]
        }

    # Only query if DB connection is valid (already checked db_instance is not None above)
    try:
        items = list(db_instance.menu_items.find(query_filter).sort("category"))
    except Exception as e:
        flash(f"Error fetching menu items: {e}", "danger")
        print(f"Error fetching menu items: {e}") # Log error
        db_error_flag = True # Treat as DB error for display

    return render_template('menu_manage.html', items=items, search_query=search_query, db_error=db_error_flag)

@app.route('/menu/edit/<item_id>', methods=['GET', 'POST'])
def menu_edit(item_id):
    db_instance = get_db()
    if db_instance is None: # CORRECT CHECK
        flash("Database connection error.", "danger")
        return redirect(url_for('menu_manage'))

    try:
        obj_id = ObjectId(item_id)
        item = db_instance.menu_items.find_one({"_id": obj_id})
        if not item:
            flash("Menu item not found.", "warning")
            return redirect(url_for('menu_manage'))

        if request.method == 'POST':
            try:
                name = request.form['name']
                description = request.form['description']
                price = float(request.form['price'])
                category = request.form['category']
                is_available = 'is_available' in request.form

                if not name or price < 0:
                    flash("Item name and non-negative price are required.", "warning")
                    return render_template('menu_edit.html', item=item) # Show form again with error

                db_instance.menu_items.update_one(
                    {"_id": obj_id},
                    {"$set": {
                        "name": name,
                        "description": description,
                        "price": price,
                        "category": category,
                        "is_available": is_available,
                        "updated_at": datetime.utcnow()
                    }}
                )
                flash(f"Menu item '{name}' updated successfully!", "success")
                return redirect(url_for('menu_manage'))
            except ValueError:
                 flash("Invalid price format. Please enter a number.", "danger")
                 return render_template('menu_edit.html', item=item) # Show form again with error
            except Exception as e:
                flash(f"Error updating menu item: {e}", "danger")
                print(f"Error updating menu item: {e}") # Log error
                return render_template('menu_edit.html', item=item) # Show form again

        # GET Request
        return render_template('menu_edit.html', item=item)

    except errors.PyMongoError as e: # Catch potential DB errors during find_one
        flash(f"Database error loading item: {e}", "danger")
        print(f"Database error loading item {item_id}: {e}") # Log error
        return redirect(url_for('menu_manage'))
    except Exception as e: # Catch ObjectId errors etc.
        flash(f"Invalid item ID or error loading item: {e}", "danger")
        print(f"Error loading item {item_id}: {e}") # Log error
        return redirect(url_for('menu_manage'))


@app.route('/menu/delete/<item_id>', methods=['POST'])
def menu_delete(item_id):
    db_instance = get_db()
    if db_instance is None: # CORRECT CHECK
        flash("Database connection error.", "danger")
        return redirect(url_for('menu_manage'))

    try:
        obj_id = ObjectId(item_id)
        result = db_instance.menu_items.delete_one({"_id": obj_id})
        if result.deleted_count > 0:
            flash("Menu item deleted successfully!", "success")
        else:
            flash("Menu item not found.", "warning")
    except Exception as e:
        flash(f"Error deleting menu item: {e}", "danger")
        print(f"Error deleting menu item {item_id}: {e}") # Log error
    return redirect(url_for('menu_manage'))

@app.route('/menu/toggle_availability/<item_id>', methods=['POST'])
def menu_toggle_availability(item_id):
    db_instance = get_db()
    if db_instance is None: # CORRECT CHECK
        return jsonify({"success": False, "error": "Database connection error."}), 500

    try:
        obj_id = ObjectId(item_id)
        item = db_instance.menu_items.find_one({"_id": obj_id}, {"is_available": 1}) # Only fetch availability
        if item:
            new_status = not item.get('is_available', False)
            db_instance.menu_items.update_one(
                {"_id": obj_id},
                {"$set": {"is_available": new_status}}
            )
            return jsonify({"success": True, "new_status": new_status})
        else:
            return jsonify({"success": False, "error": "Item not found"}), 404
    except Exception as e:
        print(f"Error toggling availability for {item_id}: {e}") # Log error
        return jsonify({"success": False, "error": str(e)}), 500


# --- Table Management ---
@app.route('/tables', methods=['GET', 'POST'])
def tables_manage():
    db_instance = get_db()
    db_error_flag = db_instance is None
    if db_instance is None and request.method == 'POST': # CORRECT CHECK - Prevent POST if DB down
         flash("Database connection error. Cannot add table.", "danger")
         return redirect(url_for('tables_manage'))
    elif db_instance is None: # CORRECT CHECK - Allow GET render with error
        flash("Database connection error.", "danger")
        return render_template('tables_manage.html', tables=[], db_error=True)

    if request.method == 'POST': # Add new table
        try:
            table_number = request.form['table_number']
            capacity = int(request.form['capacity'])

            if not table_number or capacity <= 0:
                 flash("Valid table number and positive capacity are required.", "warning")
            # Check if table number already exists
            elif db_instance.tables.find_one({"table_number": table_number}):
                flash(f"Table number '{table_number}' already exists.", "warning")
            else:
                db_instance.tables.insert_one({
                    "table_number": table_number,
                    "capacity": capacity,
                    "status": "available", # Default status
                    "created_at": datetime.utcnow()
                })
                flash(f"Table '{table_number}' added successfully!", "success")
        except ValueError:
            flash("Invalid capacity format. Please enter a whole number.", "danger")
        except Exception as e:
            flash(f"Error adding table: {e}", "danger")
            print(f"Error adding table: {e}") # Log error
        return redirect(url_for('tables_manage'))

    # GET Request
    tables = []
    # Only query if DB instance is not None (already checked above)
    try:
        tables = list(db_instance.tables.find().sort("table_number"))
    except Exception as e:
        flash(f"Error fetching tables: {e}", "danger")
        print(f"Error fetching tables: {e}") # Log error
        db_error_flag = True # Treat as DB error for display

    return render_template('tables_manage.html', tables=tables, db_error=db_error_flag)

@app.route('/tables/update_status/<table_id>', methods=['POST'])
def table_update_status(table_id):
    db_instance = get_db()
    if db_instance is None: # CORRECT CHECK
        # Handle POST request even if DB connection fails - redirect back with error
        flash("Database connection error. Cannot update table status.", "danger")
        return redirect(url_for('tables_manage'))
        # For AJAX calls, return JSON error:
        # return jsonify({"success": False, "error": "Database connection error."}), 500

    try:
        obj_id = ObjectId(table_id)
        new_status = request.form.get('status')
        valid_statuses = ["available", "occupied", "reserved", "cleaning"] # Example statuses

        if not new_status or new_status not in valid_statuses:
             # For form submission:
             flash("Invalid status provided.", "warning")
             return redirect(url_for('tables_manage'))
             # For AJAX: return jsonify({"success": False, "error": "Invalid status provided."}), 400

        # Additional check: If setting to available, unset current_order_id
        update_doc = {"$set": {"status": new_status, "updated_at": datetime.utcnow()}}
        if new_status == "available":
            update_doc["$unset"] = {"current_order_id": ""}

        result = db_instance.tables.update_one({"_id": obj_id}, update_doc)

        if result.matched_count > 0:
            flash(f"Table status updated to '{new_status}'.", "success")
             # If setting to available, potentially check for associated open orders (more complex logic)
             # For AJAX: return jsonify({"success": True, "new_status": new_status})
        else:
            flash("Table not found.", "warning")
            # For AJAX: return jsonify({"success": False, "error": "Table not found"}), 404

    except Exception as e:
        flash(f"Error updating table status: {e}", "danger")
        print(f"Error updating table status for {table_id}: {e}") # Log error
        # For AJAX: return jsonify({"success": False, "error": str(e)}), 500

    return redirect(url_for('tables_manage')) # Redirect for standard form post


@app.route('/tables/delete/<table_id>', methods=['POST'])
def table_delete(table_id):
    db_instance = get_db()
    if db_instance is None: # CORRECT CHECK
        flash("Database connection error.", "danger")
        return redirect(url_for('tables_manage'))

    try:
        obj_id = ObjectId(table_id)
        # Prevent deleting occupied tables (optional safety check)
        table = db_instance.tables.find_one({"_id": obj_id})
        if table and table.get("status") == "occupied":
             flash("Cannot delete an occupied table. Please close the order first.", "warning")
             return redirect(url_for('tables_manage'))

        result = db_instance.tables.delete_one({"_id": obj_id})
        if result.deleted_count > 0:
            flash("Table deleted successfully!", "success")
        else:
            flash("Table not found.", "warning")
    except Exception as e:
        flash(f"Error deleting table: {e}", "danger")
        print(f"Error deleting table {table_id}: {e}") # Log error
    return redirect(url_for('tables_manage'))


# --- Order Management ---
@app.route('/order/new/<table_id>', methods=['GET', 'POST'])
def order_new(table_id):
    db_instance = get_db()
    if db_instance is None: # CORRECT CHECK
        flash("Database connection error.", "danger")
        return redirect(url_for('tables_manage'))

    try:
        table_obj_id = ObjectId(table_id)
        table = db_instance.tables.find_one({"_id": table_obj_id})
        if not table:
            flash("Table not found.", "warning")
            return redirect(url_for('tables_manage'))

        # Check for existing open order (more robust check)
        existing_order = db_instance.orders.find_one({"table_id": table_obj_id, "status": "open"})
        if table.get('status') == 'occupied' and existing_order: # Use .get() for safety
            flash(f"Table {table.get('table_number', table_id)} is already occupied with an open order. View order to add items.", "info")
            return redirect(url_for('order_view', order_id=str(existing_order['_id'])))
        elif table.get('status') != 'available':
             # Prevent starting order if table isn't available
             flash(f"Cannot start new order. Table status is '{table.get('status', 'Unknown')}'.", "warning")
             return redirect(url_for('tables_manage'))


        if request.method == 'POST':
            # --- START: Process initial items from form ---
            order_items = []
            try:
                # Loop through form data to find items with quantity > 0
                for key, value in request.form.items():
                    if key.startswith("quantity_"):
                        quantity = 0 # Default quantity
                        if value: # Check if value is not empty
                            quantity = int(value)

                        if quantity > 0:
                            menu_item_id_str = key.split("quantity_")[1]
                            menu_item_obj_id = ObjectId(menu_item_id_str)
                            # Find the menu item only if quantity > 0 to avoid unnecessary lookups
                            menu_item = db_instance.menu_items.find_one({"_id": menu_item_obj_id})

                            if menu_item:
                                order_item = {
                                    "menu_item_id": menu_item['_id'],
                                    "name": menu_item['name'],
                                    "price": menu_item['price'],
                                    "quantity": quantity,
                                    "status": "pending" # KDS Status
                                }
                                order_items.append(order_item)
                            else:
                                # This case should be rare if the form is generated correctly
                                flash(f"Warning: Menu item with ID {menu_item_id_str} submitted but not found.", "warning")
                                print(f"Warning: Initial item ID {menu_item_id_str} not found during order creation.")
            except ValueError as e:
                flash(f"Invalid quantity entered: {e}. Order created without initial items.", "danger")
                print(f"ValueError processing initial items: {e}") # Log error
                order_items = [] # Reset items if quantity parsing failed
            except errors.PyMongoError as e: # Catch DB errors during find_one
                flash(f"Database error processing initial items: {e}. Order created without initial items.", "danger")
                print(f"PyMongoError processing initial items: {e}") # Log error
                order_items = [] # Reset items on error
            except Exception as e: # Catch ObjectId errors, etc.
                 flash(f"Error processing initial items: {e}. Order created without initial items.", "danger")
                 print(f"Exception processing initial items: {e}") # Log error
                 order_items = [] # Reset items on error

            # Calculate initial totals
            subtotal, tax, total = calculate_order_total(order_items)
            # --- END: Process initial items from form ---

            # Create a new order
            new_order = {
                "table_id": table_obj_id,
                "table_number": table["table_number"],
                "items": order_items, # Use the processed list
                "status": "open",
                "order_time": datetime.utcnow(),
                "subtotal": subtotal, # Use calculated subtotal
                "tax": tax,         # Use calculated tax
                "total_amount": total, # Use calculated total
                "created_at": datetime.utcnow() # Add created_at timestamp
            }
            result = db_instance.orders.insert_one(new_order)

            # Update table status to occupied
            db_instance.tables.update_one(
                {"_id": table_obj_id},
                {"$set": {"status": "occupied", "current_order_id": result.inserted_id, "updated_at": datetime.utcnow()}}
            )

            flash(f"New order started for Table {table.get('table_number', table_id)}.", "success")
            if not order_items and request.form: # Check if form was submitted but no items were added
                flash("No initial items added. Add items via the order view page.", "info")
            return redirect(url_for('order_view', order_id=str(result.inserted_id)))

        # GET Request: Show available menu items to add to the new order
        menu_items = []
        # Only query if DB instance is not None (already checked above)
        try:
            menu_items = list(db_instance.menu_items.find({"is_available": True}).sort("category"))
        except Exception as e:
                flash(f"Error fetching menu items for new order: {e}", "danger")
                print(f"Error fetching menu items for new order: {e}") # Log error
                # Allow page render but show error / potentially disable form?

        return render_template('order_new.html', table=table, menu_items=menu_items)

    except errors.PyMongoError as e: # Catch DB errors during table find
        flash(f"Database error starting new order: {e}", "danger")
        print(f"PyMongoError starting new order for table {table_id}: {e}") # Log error
        return redirect(url_for('tables_manage'))
    except Exception as e: # Catch ObjectId errors etc.
        flash(f"Error starting new order: {e}", "danger")
        print(f"Error in order_new for table {table_id}: {e}") # Log the error server-side
        return redirect(url_for('tables_manage'))

@app.route('/order/view/<order_id>', methods=['GET'])
def order_view(order_id):
    db_instance = get_db()
    db_error_flag = db_instance is None
    if db_instance is None: # CORRECT CHECK
        flash("Database connection error.", "danger")
        # Redirect or render an error template if DB is essential for view
        return redirect(url_for('index')) # Or maybe a dedicated orders list page

    order = None
    menu_items = []

    try:
        obj_id = ObjectId(order_id)
        # Only query if DB instance is not None (already checked above)
        order = db_instance.orders.find_one({"_id": obj_id})

        if not order:
            flash("Order not found.", "warning")
            return redirect(url_for('index')) # Or orders list page

        # Fetch available menu items to allow adding more (only if DB connected)
        # Only query if DB instance is not None (already checked above)
        menu_items = list(db_instance.menu_items.find({"is_available": True}).sort("category"))

        # Calculate current totals for display (use get for safety)
        # Note: Totals should ideally be recalculated/stored on item add/update/cancel
        subtotal, tax, total = calculate_order_total(order.get('items', []))
        order['subtotal'] = subtotal # Update dict for display consistency
        order['tax'] = tax
        order['total_amount'] = total

        return render_template('order_view.html', order=order, menu_items=menu_items, db_error=db_error_flag)

    except errors.PyMongoError as e: # Catch DB errors during find
        flash(f"Database error loading order: {e}", "danger")
        print(f"PyMongoError loading order {order_id}: {e}") # Log error
        return redirect(url_for('index'))
    except Exception as e: # Catch ObjectId errors etc.
        flash(f"Invalid order ID or error loading order: {e}", "danger")
        print(f"Error loading order {order_id}: {e}") # Log error
        return redirect(url_for('index')) # Or orders list page

@app.route('/order/add_item/<order_id>', methods=['POST'])
def order_add_item(order_id):
    db_instance = get_db()
    if db_instance is None: # CORRECT CHECK
        flash("Database connection error. Cannot add item.", "danger")
        # For AJAX: return jsonify({"success": False, "error": "Database connection error."}), 500
        # If form submission leads here, redirect back
        return redirect(request.referrer or url_for('order_view', order_id=order_id))

    try:
        order_obj_id = ObjectId(order_id)
        menu_item_id = request.form.get('menu_item_id')
        quantity = int(request.form.get('quantity', 1))

        if not menu_item_id or quantity <= 0:
             flash("Invalid menu item or quantity.", "warning")
             # For AJAX: return jsonify({"success": False, "error": "Invalid menu item or quantity."}), 400
             return redirect(url_for('order_view', order_id=order_id))


        menu_item = db_instance.menu_items.find_one({"_id": ObjectId(menu_item_id)})
        if not menu_item or not menu_item.get('is_available'):
             flash("Menu item not found or unavailable.", "warning")
             # For AJAX: return jsonify({"success": False, "error": "Menu item not found or unavailable."}), 404
             return redirect(url_for('order_view', order_id=order_id))

        order_item = {
            "menu_item_id": menu_item['_id'],
            "name": menu_item['name'],
            "price": menu_item['price'],
            "quantity": quantity,
            "status": "pending" # KDS Status: 'pending', 'preparing', 'served', 'cancelled'
        }

        # Add the item to the order's items array
        # Also set updated_at timestamp
        update_result = db_instance.orders.update_one(
            {"_id": order_obj_id, "status": "open"}, # Can only add to open orders
            {
                "$push": {"items": order_item},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )

        if update_result.matched_count == 0:
             flash("Could not add item. Order not found or not open.", "warning")
             return redirect(url_for('order_view', order_id=order_id))


        # Recalculate totals and update the order document
        order = db_instance.orders.find_one({"_id": order_obj_id}) # Get updated order
        if order: # Check if order still exists
            subtotal, tax, total = calculate_order_total(order.get('items', []))
            db_instance.orders.update_one(
                 {"_id": order_obj_id},
                 {"$set": {"subtotal": subtotal, "tax": tax, "total_amount": total, "updated_at": datetime.utcnow()}}
             )
            flash(f"Added {quantity} x {menu_item['name']} to order.", "success")
        else:
            # This case is unlikely if the $push succeeded but good practice
             flash("Item added, but failed to recalculate totals (order modified unexpectedly).", "warning")


        return redirect(url_for('order_view', order_id=order_id))
        # Or using AJAX: return jsonify({"success": True, "item": order_item})

    except ValueError:
         flash("Invalid quantity.", "danger")
         # For AJAX: return jsonify({"success": False, "error": "Invalid quantity."}), 400
         return redirect(url_for('order_view', order_id=order_id))
    except Exception as e:
        flash(f"Error adding item: {e}", "danger")
        print(f"Error adding item to order {order_id}: {e}") # Log error
        # For AJAX: return jsonify({"success": False, "error": str(e)}), 500
        return redirect(url_for('order_view', order_id=order_id))


@app.route('/order/update_item_status/<order_id>/<int:item_index>', methods=['POST'])
def order_update_item_status(order_id, item_index):
    """Updates the status of a specific item within an order (for KDS mainly)"""
    db_instance = get_db()
    if db_instance is None: # CORRECT CHECK
        # Handle both form and AJAX
        flash("Database connection error. Cannot update item status.", "danger")
        return jsonify({"success": False, "error": "Database connection error."}), 500

    try:
        order_obj_id = ObjectId(order_id)
        new_status = request.form.get('status')
        valid_statuses = ["pending", "preparing", "served", "cancelled"]

        if new_status not in valid_statuses:
             flash("Invalid item status provided.", "warning")
             return jsonify({"success": False, "error": "Invalid item status."}), 400

        # Use the positional operator $ to update the specific item in the array
        update_key = f"items.{item_index}.status"
        result = db_instance.orders.update_one(
            {"_id": order_obj_id, f"items.{item_index}": {"$exists": True}},
            {"$set": {update_key: new_status, "updated_at": datetime.utcnow()}}
        )

        if result.matched_count > 0:
            # If cancelled, recalculate totals
            recalculate_totals = False
            if new_status == 'cancelled':
                recalculate_totals = True

            # Also recalculate if marking as served? Depends on workflow.
            # For now, only recalculate on cancel.

            if recalculate_totals:
                order = db_instance.orders.find_one({"_id": order_obj_id}) # Get updated order
                if order:
                    subtotal, tax, total = calculate_order_total(order.get('items', []))
                    db_instance.orders.update_one(
                         {"_id": order_obj_id},
                         {"$set": {"subtotal": subtotal, "tax": tax, "total_amount": total, "updated_at": datetime.utcnow()}}
                     )
                else:
                    print(f"Warning: Item status updated for {order_id}, but order not found for totals recalc.")
            # Return JSON for AJAX KDS updates
            flash(f"Item status updated to {new_status}.", "success") # Flash for non-JS fallback
            return jsonify({"success": True, "new_status": new_status})
        else:
            flash("Order or item index not found.", "warning")
            return jsonify({"success": False, "error": "Order or item index not found."}), 404

    except Exception as e:
        print(f"Error updating item status for order {order_id}, item {item_index}: {e}") # Log error
        flash(f"Error updating item status: {e}", "danger")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/order/close/<order_id>', methods=['POST'])
def order_close(order_id):
    """Marks an order as 'closed', ready for billing."""
    db_instance = get_db()
    if db_instance is None: # CORRECT CHECK
        flash("Database connection error.", "danger")
        return redirect(request.referrer or url_for('index'))

    try:
        obj_id = ObjectId(order_id)
        # Ensure all items are served or cancelled before closing (optional strict check)
        order = db_instance.orders.find_one({"_id": obj_id})

        if not order:
             flash("Order not found.", "warning")
             return redirect(request.referrer or url_for('index'))

        if order['status'] == 'open':
            # Basic check: Disallow closing empty orders
            if not order.get('items'):
                flash("Cannot close an empty order. Add items or cancel the order.", "warning")
                # Redirect back to order view instead of billing
                return redirect(url_for('order_view', order_id=order_id))

            # More strict check (uncomment if needed):
            # all_done = all(item.get('status') in ['served', 'cancelled'] for item in order.get('items', []))
            # if not all_done:
            #     flash("Cannot close order: Not all items are marked as 'served' or 'cancelled'.", "warning")
            #     return redirect(url_for('order_view', order_id=order_id))

            # Recalculate final totals just in case
            subtotal, tax, total = calculate_order_total(order.get('items', []))

            db_instance.orders.update_one(
                {"_id": obj_id},
                {"$set": {
                    "status": "closed",
                    "closed_time": datetime.utcnow(),
                    "subtotal": subtotal,
                    "tax": tax,
                    "total_amount": total,
                    "updated_at": datetime.utcnow() # Add updated timestamp
                    }}
            )
            # Don't change table status yet, only when bill is paid
            flash("Order closed and ready for billing.", "success")
            # Redirect to billing page to see the closed order
            return redirect(url_for('billing'))
        elif order['status'] == 'closed':
             flash(f"Order is already closed.", "info")
             # Redirect to view page maybe? Or billing?
             return redirect(url_for('billing'))
        else:
             flash(f"Cannot close order. Status is '{order['status']}'.", "warning")
             return redirect(request.referrer or url_for('order_view', order_id=order_id))

    except Exception as e:
        flash(f"Error closing order: {e}", "danger")
        print(f"Error closing order {order_id}: {e}") # Log error
        return redirect(request.referrer or url_for('index'))


# --- Billing & Invoicing ---
@app.route('/billing')
def billing():
    """Lists orders that are ready for billing (status='closed')."""
    db_instance = get_db()
    db_error_flag = db_instance is None
    closed_orders = []

    if db_instance is None: # CORRECT CHECK
        flash("Database connection error.", "danger")
        # Render template but indicate error
        return render_template('billing.html', orders=closed_orders, db_error=True)

    try:
        closed_orders = list(db_instance.orders.find({"status": "closed"}).sort("closed_time", -1))
    except Exception as e:
        flash(f"Error fetching closed orders: {e}", "danger")
        print(f"Error fetching closed orders: {e}") # Log error
        db_error_flag = True # Treat as DB error

    return render_template('billing.html', orders=closed_orders, db_error=db_error_flag)

@app.route('/bill/view/<order_id>')
def bill_view(order_id):
    """Shows the bill details for a closed order, ready for payment."""
    db_instance = get_db()
    if db_instance is None: # CORRECT CHECK
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

        if order['status'] not in ['closed', 'billed']: # Allow viewing already billed orders too
             flash("Order is not yet closed for billing.", "warning")
             return redirect(url_for('order_view', order_id=order_id))

        # Check if a bill record already exists
        bill = db_instance.bills.find_one({"order_id": obj_id})

        # Ensure totals are up-to-date in the order dict passed to template
        # This ensures consistency even if recalc failed somewhere
        subtotal, tax, total = calculate_order_total(order.get('items', []))
        order['subtotal'] = subtotal
        order['tax'] = tax
        # If billed, use bill total, otherwise use calculated order total
        order['total_amount'] = bill['total_amount'] if bill else total

        return render_template('bill_view.html', order=order, bill=bill, tax_rate=config.TAX_RATE_PERCENT)

    except errors.PyMongoError as e: # Catch DB errors
        flash(f"Database error loading bill view: {e}", "danger")
        print(f"PyMongoError loading bill view for {order_id}: {e}") # Log error
        return redirect(url_for('billing'))
    except Exception as e: # Catch ObjectId errors etc.
        flash(f"Invalid order ID or error loading bill: {e}", "danger")
        print(f"Error loading bill view for {order_id}: {e}") # Log error
        return redirect(url_for('billing'))

@app.route('/bill/finalize/<order_id>', methods=['POST'])
def bill_finalize(order_id):
    """Marks the bill as paid, updates order/table status, creates bill record."""
    db_instance = get_db()
    if db_instance is None: # CORRECT CHECK
        flash("Database connection error.", "danger")
        return redirect(url_for('billing'))

    try:
        order_obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": order_obj_id})

        if not order:
            flash("Order not found.", "warning")
            return redirect(url_for('billing'))

        # Prevent finalizing if already billed
        if order['status'] == 'billed':
             flash("This order has already been billed.", "info")
             return redirect(url_for('bill_view', order_id=order_id))
        elif order['status'] != 'closed':
             flash(f"Cannot finalize bill. Order status is '{order['status']}'.", "warning")
             return redirect(url_for('bill_view', order_id=order_id))


        # Check if bill already exists (double-submit prevention)
        existing_bill = db_instance.bills.find_one({"order_id": order_obj_id})
        if existing_bill:
            flash("Bill already finalized (possible double submission).", "warning")
            return redirect(url_for('bill_view', order_id=order_id))

        payment_method = request.form.get('payment_method', 'Cash') # Default or from form
        discount = float(request.form.get('discount', 0.0)) # Optional discount

        # Recalculate with potential discount just before billing
        subtotal, tax, _ = calculate_order_total(order.get('items', []))
        total_before_discount = subtotal + tax
        total_after_discount = total_before_discount - discount
        if total_after_discount < 0: total_after_discount = 0 # Can't be negative

        # Create Bill Document
        bill_doc = {
            "order_id": order['_id'],
            "table_number": order.get('table_number'), # Use get for safety
            "items": order.get('items', []), # Copy items at time of billing
            "subtotal": subtotal,
            "tax": tax,
            "tax_rate_percent": config.TAX_RATE_PERCENT,
            "discount": discount,
            "total_amount": total_after_discount, # Final billed amount
            "payment_method": payment_method,
            "payment_status": "paid", # Assume paid on finalize
            "billed_at": datetime.utcnow()
        }
        bill_result = db_instance.bills.insert_one(bill_doc)
        final_bill_id = bill_result.inserted_id

        # Update Order Status and link to final bill
        db_instance.orders.update_one(
            {"_id": order_obj_id},
            {"$set": {
                "status": "billed",
                "final_bill_id": final_bill_id, # Link order to the bill document
                "updated_at": datetime.utcnow()
                }}
        )

        # Update Table Status to 'available' (or 'cleaning')
        table_update = {"$set": {"status": "available", "updated_at": datetime.utcnow()}, "$unset": {"current_order_id": ""}}
        if order.get('table_id'):
             db_instance.tables.update_one({"_id": order['table_id']}, table_update)
        else: # If table_id wasn't stored correctly, try finding by number
             db_instance.tables.update_one({"table_number": order.get('table_number')}, table_update)


        flash(f"Bill for Order {order_id} finalized successfully! Payment: {payment_method}.", "success")
        return redirect(url_for('billing')) # Redirect back to billing list

    except ValueError:
        flash("Invalid discount value. Please enter a number.", "danger")
        return redirect(url_for('bill_view', order_id=order_id))
    except Exception as e:
        flash(f"Error finalizing bill: {e}", "danger")
        print(f"Error finalizing bill {order_id}: {e}") # Log the error
        return redirect(url_for('bill_view', order_id=order_id))


# --- Kitchen Display System (KDS) ---
@app.route('/kds')
def kds():
    db_instance = get_db()
    db_error_flag = db_instance is None
    kds_items = []

    if db_instance is None: # CORRECT CHECK
        flash("Database connection error.", "danger")
        return render_template('kds.html', kds_items=[], db_error=True)

    try:
        # Find all 'open' orders
        # Improve efficiency: only fetch necessary fields
        open_orders = list(db_instance.orders.find(
            {"status": "open"},
            {"_id": 1, "table_number": 1, "items": 1, "order_time": 1}
            ).sort("order_time"))

        for order in open_orders:
            order_id_str = str(order['_id'])
            for index, item in enumerate(order.get('items', [])):
                # Include items that are 'pending' or 'preparing'
                if item.get('status') in ['pending', 'preparing']:
                    kds_item = {
                        "order_id": order_id_str,
                        "table_number": order.get('table_number', 'N/A'),
                        "item_name": item.get('name'),
                        "quantity": item.get('quantity'),
                        "status": item.get('status'),
                        "item_index": index, # Pass index for status updates
                        "order_time": order.get('order_time')
                    }
                    kds_items.append(kds_item)

        # Sort items perhaps by order time or status (e.g., preparing first)
        # Oldest first, then maybe by status (preparing before pending)
        kds_items.sort(key=lambda x: (x['order_time'] or datetime.min, x['status'] == 'pending'))

    except Exception as e:
         flash(f"Error fetching KDS items: {e}", "danger")
         print(f"Error fetching KDS items: {e}") # Log error
         db_error_flag = True # Treat as DB error

    return render_template('kds.html', kds_items=kds_items, db_error=db_error_flag)


# --- Analytics & Reporting ---
@app.route('/reports')
def reports():
    db_instance = get_db()
    db_error_flag = db_instance is None
    report_data = {
        "today_total_sales": 0,
        "today_bill_count": 0,
        "top_selling_items": []
    }

    if db_instance is None: # CORRECT CHECK
        flash("Database connection error.", "danger")
        return render_template('reports.html', report_data=report_data, db_error=True)

    try:
        # Basic Example: Total Sales Today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Use the 'bills' collection for accurate sales figures
        pipeline_today = [
            {"$match": {"billed_at": {"$gte": today_start, "$lte": today_end}, "payment_status": "paid"}},
            {"$group": {
                "_id": None, # Group all matched docs into one
                "total_sales": {"$sum": "$total_amount"},
                "count": {"$sum": 1}
            }}
        ]
        today_sales_result = list(db_instance.bills.aggregate(pipeline_today))
        today_sales = today_sales_result[0] if today_sales_result else {"total_sales": 0, "count": 0}
        report_data["today_total_sales"] = today_sales.get('total_sales', 0)
        report_data["today_bill_count"] = today_sales.get('count', 0)


        # Basic Example: Top 5 Selling Items (based on quantity in PAID bills)
        pipeline_top_items = [
             {"$match": {"payment_status": "paid"}}, # Only consider paid bills
             {"$unwind": "$items"}, # Deconstruct the items array
             {"$match": {"items.status": {"$ne": "cancelled"}}}, # Exclude cancelled items within paid bills
             {"$group": {
                 "_id": "$items.name", # Group by item name
                 "total_quantity": {"$sum": "$items.quantity"}
             }},
             {"$sort": {"total_quantity": -1}}, # Sort by quantity descending
             {"$limit": 5}
        ]
        top_items = list(db_instance.bills.aggregate(pipeline_top_items))
        report_data["top_selling_items"] = top_items

    except Exception as e:
        flash(f"Error generating reports: {e}", "danger")
        print(f"Error generating reports: {e}") # Log error
        db_error_flag = True # Treat as DB error

    return render_template('reports.html', report_data=report_data, db_error=db_error_flag)


# --- Context Processors (Optional but recommended) ---
@app.context_processor
def inject_global_vars():
    """Inject global variables/config into all templates."""
    db_status_ok = get_db() is not None # CORRECT CHECK
    return dict(
        config=config, # Make config accessible (use specific keys if preferred)
        db_status_ok=db_status_ok
        )

# --- Main Execution ---
if __name__ == '__main__':
    print("Starting Flask development server...")
    # Ensure DB connection is attempted initially outside request context
    # connect_db() - Removed this, use before_request instead for context safety
    # Use host='0.0.0.0' to make it accessible on your network
    # Use threaded=True for development to handle concurrent requests better
    # DO NOT use threaded=True with production WSGI servers
    app.run(host='0.0.0.0', port=5000, debug=app.config['DEBUG'], threaded=True)

    # For production, use a proper WSGI server like Waitress or Gunicorn:
    # from waitress import serve
    # print("Starting Flask production server with Waitress...")
    # serve(app, host="0.0.0.0", port=5000)

    # Example using Gunicorn (run via command line):
    # gunicorn --bind 0.0.0.0:5000 app:app