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
    # Check if client is None OR if client is set but server is not available
    needs_connection = client is None
    if not needs_connection and client is not None:
        try:
            client.admin.command('ping') # Quick check if server is still reachable
        except (errors.ConnectionFailure, errors.ServerSelectionTimeoutError, AttributeError):
             print("Existing client connection lost, will attempt reconnect.")
             needs_connection = True
             client = None # Reset client
             db = None # Reset db

    if needs_connection:
        try:
            print(f"Attempting to connect to MongoDB using URI from config...")
            client = MongoClient(
                config.MONGO_URI,
                serverSelectionTimeoutMS=5000 # Timeout after 5 seconds
            )
            client.admin.command('ismaster') # Verify connection works
            print("MongoDB connection successful.")

            db = client[config.MONGO_DB_NAME]
            print(f"Using database: {config.MONGO_DB_NAME}")

            # Ensure collections exist only if db connection succeeded
            if db is not None:
                required_collections = ['menu_items', 'tables', 'orders', 'bills']
                try:
                    existing_collections = db.list_collection_names()
                    for coll in required_collections:
                        if coll not in existing_collections:
                            db.create_collection(coll)
                            print(f"Created collection: '{coll}'")
                except errors.OperationFailure as e:
                    # Handle cases where user might not have listCollections permission
                    print(f"Warning: Could not list/create collections (permissions?): {e}")
                    # Application might still work if collections exist or are created on first write

        except errors.ServerSelectionTimeoutError as e:
            print(f"MongoDB connection failed (Timeout): {e}")
            client = None
            db = None
        except errors.ConnectionFailure as e:
            print(f"MongoDB connection failed (ConnectionFailure): {e}")
            client = None
            db = None
        except errors.OperationFailure as e: # Catch auth errors during initial connection test
             print(f"MongoDB operation failed (Authentication Error?): {e}")
             client = None
             db = None
        except Exception as e:
            print(f"An error occurred during DB setup: {e}")
            client = None
            db = None
    return db

# Use before_request to ensure DB connection attempt before handling
@app.before_request
def before_request_func():
    get_db()

# --- Helper Functions ---
def get_db():
    """Returns the database instance, attempting to reconnect if necessary."""
    global db, client
    if db is None:
        print("DB object is None, attempting to reconnect...")
        return connect_db()
    if client is None: # If db exists but client is somehow None, reconnect
        print("DB client is None, attempting to reconnect...")
        db = None
        return connect_db()

    # Verify connection with ping
    try:
        client.admin.command('ping')
    except (errors.ConnectionFailure, errors.ServerSelectionTimeoutError, AttributeError) as e:
        print(f"DB connection check failed ({type(e).__name__}), attempting to reconnect...")
        db = None
        client = None
        return connect_db()
    return db

def calculate_order_total(items):
    """Calculates subtotal, tax, and total for a list of order items."""
    subtotal = sum(item['price'] * item['quantity'] for item in items if item.get('status') != 'cancelled')
    tax = (subtotal * config.TAX_RATE_PERCENT) / 100.0
    total = subtotal + tax
    return subtotal, tax, total

# --- Routes ---

# --- UPDATED Index Route for Dashboard Metrics ---
@app.route('/')
def index():
    """Dashboard/Home Page"""
    db_instance = get_db()
    db_error_flag = db_instance is None

    tables_metrics = {"total": 0, "available": 0}
    orders_metrics = {"active": 0, "pending_bills": 0, "total": 0} # Total orders might be complex to define perfectly here
    sales_metrics = {"today": 0.0, "count": 0}
    kds_preview = []

    if db_instance is not None:
        try:
            # Table Metrics
            tables_metrics["total"] = db_instance.tables.count_documents({})
            tables_metrics["available"] = db_instance.tables.count_documents({"status": "available"})

            # Order Metrics
            orders_metrics["active"] = db_instance.orders.count_documents({"status": "open"})
            orders_metrics["pending_bills"] = db_instance.orders.count_documents({"status": "closed"})
            # Estimate total tables as potential orders base for progress bar % (adjust if needed)
            orders_metrics["total"] = tables_metrics["total"] if tables_metrics["total"] > 0 else 1 # Avoid division by zero

            # Sales Metrics (Today)
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start.replace(hour=23, minute=59, second=59, microsecond=999999)
            pipeline_today = [
                {"$match": {"billed_at": {"$gte": today_start, "$lte": today_end}, "payment_status": "paid"}},
                {"$group": {
                    "_id": None,
                    "total_sales": {"$sum": "$total_amount"},
                    "count": {"$sum": 1}
                }}
            ]
            today_sales_result = list(db_instance.bills.aggregate(pipeline_today))
            today_sales_data = today_sales_result[0] if today_sales_result else {"total_sales": 0, "count": 0}
            sales_metrics["today"] = today_sales_data.get('total_sales', 0)
            sales_metrics["count"] = today_sales_data.get('count', 0)

            # KDS Preview (e.g., first 3 items)
            open_orders = list(db_instance.orders.find(
                {"status": "open"},
                {"_id": 1, "table_number": 1, "items": 1, "order_time": 1}
            ).sort("order_time").limit(5)) # Limit orders checked

            preview_count = 0
            max_preview = 3 # Max items in preview
            for order in open_orders:
                if preview_count >= max_preview:
                    break
                for item in order.get('items', []):
                    if item.get('status') in ['pending', 'preparing']:
                        kds_item = {
                            "table_number": order.get('table_number', 'N/A'),
                            "item_name": item.get('name'),
                            "quantity": item.get('quantity'),
                            "status": item.get('status'),
                            "order_time": order.get('order_time')
                        }
                        kds_preview.append(kds_item)
                        preview_count += 1
                        if preview_count >= max_preview:
                            break

        except errors.PyMongoError as e: # Catch specific DB errors
             print(f"Database error fetching dashboard metrics: {e}")
             flash("Could not load all dashboard metrics due to a database error.", "warning")
             db_error_flag = True # Indicate partial error / db issue
        except Exception as e:
             print(f"Unexpected error fetching dashboard metrics: {e}")
             flash("An unexpected error occurred while loading dashboard metrics.", "danger")
             db_error_flag = True

    else: # If db_instance is None
         flash("Database connection error. Please check configuration and MongoDB status.", "danger")

    # Pass db_error flag along with metrics
    return render_template('index.html',
                           db_error=db_error_flag, # Let template know if overall DB connection failed
                           tables_metrics=tables_metrics,
                           orders_metrics=orders_metrics,
                           sales_metrics=sales_metrics,
                           kds_preview=kds_preview
                           )
# --- END UPDATED Index Route ---

# --- Menu Management ---
@app.route('/menu', methods=['GET', 'POST'])
def menu_manage():
    db_instance = get_db()
    db_error_flag = db_instance is None
    if db_instance is None:
        flash("Database connection error.", "danger")
        if request.method == 'POST':
             return redirect(url_for('menu_manage'))
        return render_template('menu_manage.html', items=[], search_query='', db_error=True)

    if request.method == 'POST':
        try:
            name = request.form['name']
            description = request.form['description']
            price = float(request.form['price'])
            category = request.form['category']
            is_available = 'is_available' in request.form

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
            print(f"Error adding menu item: {e}")
        return redirect(url_for('menu_manage'))

    search_query = request.args.get('search', '')
    query_filter = {}
    items = []
    if search_query:
        query_filter = {
            "$or": [
                {"name": {"$regex": search_query, "$options": "i"}},
                {"category": {"$regex": search_query, "$options": "i"}}
            ]
        }

    try:
        items = list(db_instance.menu_items.find(query_filter).sort("category"))
    except Exception as e:
        flash(f"Error fetching menu items: {e}", "danger")
        print(f"Error fetching menu items: {e}")
        db_error_flag = True

    return render_template('menu_manage.html', items=items, search_query=search_query, db_error=db_error_flag)

@app.route('/menu/edit/<item_id>', methods=['GET', 'POST'])
def menu_edit(item_id):
    db_instance = get_db()
    if db_instance is None:
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
                    return render_template('menu_edit.html', item=item)

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
                 return render_template('menu_edit.html', item=item)
            except Exception as e:
                flash(f"Error updating menu item: {e}", "danger")
                print(f"Error updating menu item: {e}")
                return render_template('menu_edit.html', item=item)

        return render_template('menu_edit.html', item=item)

    except errors.PyMongoError as e:
        flash(f"Database error loading item: {e}", "danger")
        print(f"Database error loading item {item_id}: {e}")
        return redirect(url_for('menu_manage'))
    except Exception as e:
        flash(f"Invalid item ID or error loading item: {e}", "danger")
        print(f"Error loading item {item_id}: {e}")
        return redirect(url_for('menu_manage'))

@app.route('/menu/delete/<item_id>', methods=['POST'])
def menu_delete(item_id):
    db_instance = get_db()
    if db_instance is None:
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
        print(f"Error deleting menu item {item_id}: {e}")
    return redirect(url_for('menu_manage'))

@app.route('/menu/toggle_availability/<item_id>', methods=['POST'])
def menu_toggle_availability(item_id):
    db_instance = get_db()
    if db_instance is None:
        return jsonify({"success": False, "error": "Database connection error."}), 500

    try:
        obj_id = ObjectId(item_id)
        item = db_instance.menu_items.find_one({"_id": obj_id}, {"is_available": 1})
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
        print(f"Error toggling availability for {item_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# --- Table Management ---
@app.route('/tables', methods=['GET', 'POST'])
def tables_manage():
    db_instance = get_db()
    db_error_flag = db_instance is None
    if db_instance is None and request.method == 'POST':
         flash("Database connection error. Cannot add table.", "danger")
         return redirect(url_for('tables_manage'))
    elif db_instance is None:
        flash("Database connection error.", "danger")
        return render_template('tables_manage.html', tables=[], db_error=True)

    if request.method == 'POST':
        try:
            table_number = request.form['table_number']
            capacity = int(request.form['capacity'])

            if not table_number or capacity <= 0:
                 flash("Valid table number and positive capacity are required.", "warning")
            elif db_instance.tables.find_one({"table_number": table_number}):
                flash(f"Table number '{table_number}' already exists.", "warning")
            else:
                db_instance.tables.insert_one({
                    "table_number": table_number,
                    "capacity": capacity,
                    "status": "available",
                    "created_at": datetime.utcnow()
                })
                flash(f"Table '{table_number}' added successfully!", "success")
        except ValueError:
            flash("Invalid capacity format. Please enter a whole number.", "danger")
        except Exception as e:
            flash(f"Error adding table: {e}", "danger")
            print(f"Error adding table: {e}")
        return redirect(url_for('tables_manage'))

    tables = []
    try:
        tables = list(db_instance.tables.find().sort("table_number"))
    except Exception as e:
        flash(f"Error fetching tables: {e}", "danger")
        print(f"Error fetching tables: {e}")
        db_error_flag = True

    return render_template('tables_manage.html', tables=tables, db_error=db_error_flag)

@app.route('/tables/update_status/<table_id>', methods=['POST'])
def table_update_status(table_id):
    db_instance = get_db()
    if db_instance is None:
        flash("Database connection error. Cannot update table status.", "danger")
        return redirect(url_for('tables_manage'))

    try:
        obj_id = ObjectId(table_id)
        new_status = request.form.get('status')
        valid_statuses = ["available", "occupied", "reserved", "cleaning"]

        if not new_status or new_status not in valid_statuses:
             flash("Invalid status provided.", "warning")
             return redirect(url_for('tables_manage'))

        update_doc = {"$set": {"status": new_status, "updated_at": datetime.utcnow()}}
        if new_status == "available":
            update_doc["$unset"] = {"current_order_id": ""}

        result = db_instance.tables.update_one({"_id": obj_id}, update_doc)

        if result.matched_count > 0:
            flash(f"Table status updated to '{new_status}'.", "success")
        else:
            flash("Table not found.", "warning")

    except Exception as e:
        flash(f"Error updating table status: {e}", "danger")
        print(f"Error updating table status for {table_id}: {e}")

    return redirect(url_for('tables_manage'))

@app.route('/tables/delete/<table_id>', methods=['POST'])
def table_delete(table_id):
    db_instance = get_db()
    if db_instance is None:
        flash("Database connection error.", "danger")
        return redirect(url_for('tables_manage'))

    try:
        obj_id = ObjectId(table_id)
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
        print(f"Error deleting table {table_id}: {e}")
    return redirect(url_for('tables_manage'))


# --- Order Management ---
@app.route('/order/new/<table_id>', methods=['GET', 'POST'])
def order_new(table_id):
    db_instance = get_db()
    if db_instance is None:
        flash("Database connection error.", "danger")
        return redirect(url_for('tables_manage'))

    try:
        table_obj_id = ObjectId(table_id)
        table = db_instance.tables.find_one({"_id": table_obj_id})
        if not table:
            flash("Table not found.", "warning")
            return redirect(url_for('tables_manage'))

        existing_order = db_instance.orders.find_one({"table_id": table_obj_id, "status": "open"})
        if table.get('status') == 'occupied' and existing_order:
            flash(f"Table {table.get('table_number', table_id)} is already occupied with an open order. View order to add items.", "info")
            return redirect(url_for('order_view', order_id=str(existing_order['_id'])))
        elif table.get('status') != 'available':
             flash(f"Cannot start new order. Table status is '{table.get('status', 'Unknown')}'.", "warning")
             return redirect(url_for('tables_manage'))

        if request.method == 'POST':
            order_items = []
            try:
                for key, value in request.form.items():
                    if key.startswith("quantity_"):
                        quantity = 0
                        if value:
                            quantity = int(value)
                        if quantity > 0:
                            menu_item_id_str = key.split("quantity_")[1]
                            menu_item_obj_id = ObjectId(menu_item_id_str)
                            menu_item = db_instance.menu_items.find_one({"_id": menu_item_obj_id})
                            if menu_item:
                                order_item = {
                                    "menu_item_id": menu_item['_id'], "name": menu_item['name'],
                                    "price": menu_item['price'], "quantity": quantity,
                                    "status": "pending"
                                }
                                order_items.append(order_item)
                            else:
                                flash(f"Warning: Menu item ID {menu_item_id_str} submitted but not found.", "warning")
                                print(f"Warning: Initial item ID {menu_item_id_str} not found.")
            except ValueError as e:
                flash(f"Invalid quantity: {e}. Order created empty.", "danger")
                print(f"ValueError processing initial items: {e}")
                order_items = []
            except errors.PyMongoError as e:
                flash(f"DB error processing items: {e}. Order created empty.", "danger")
                print(f"PyMongoError processing initial items: {e}")
                order_items = []
            except Exception as e:
                 flash(f"Error processing items: {e}. Order created empty.", "danger")
                 print(f"Exception processing initial items: {e}")
                 order_items = []

            subtotal, tax, total = calculate_order_total(order_items)
            new_order = {
                "table_id": table_obj_id, "table_number": table["table_number"],
                "items": order_items, "status": "open", "order_time": datetime.utcnow(),
                "subtotal": subtotal, "tax": tax, "total_amount": total,
                "created_at": datetime.utcnow()
            }
            result = db_instance.orders.insert_one(new_order)
            db_instance.tables.update_one(
                {"_id": table_obj_id},
                {"$set": {"status": "occupied", "current_order_id": result.inserted_id, "updated_at": datetime.utcnow()}}
            )
            flash(f"New order started for Table {table.get('table_number', table_id)}.", "success")
            if not order_items and request.form:
                flash("No initial items added. Add items via the order view page.", "info")
            return redirect(url_for('order_view', order_id=str(result.inserted_id)))

        menu_items = []
        try:
            menu_items = list(db_instance.menu_items.find({"is_available": True}).sort("category"))
        except Exception as e:
                flash(f"Error fetching menu items for new order: {e}", "danger")
                print(f"Error fetching menu items for new order: {e}")

        return render_template('order_new.html', table=table, menu_items=menu_items)

    except errors.PyMongoError as e:
        flash(f"Database error starting new order: {e}", "danger")
        print(f"PyMongoError starting new order for table {table_id}: {e}")
        return redirect(url_for('tables_manage'))
    except Exception as e:
        flash(f"Error starting new order: {e}", "danger")
        print(f"Error in order_new for table {table_id}: {e}")
        return redirect(url_for('tables_manage'))

@app.route('/order/view/<order_id>', methods=['GET'])
def order_view(order_id):
    db_instance = get_db()
    db_error_flag = db_instance is None
    if db_instance is None:
        flash("Database connection error.", "danger")
        return redirect(url_for('index'))

    order = None
    menu_items = []
    try:
        obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": obj_id})
        if not order:
            flash("Order not found.", "warning")
            return redirect(url_for('index'))

        menu_items = list(db_instance.menu_items.find({"is_available": True}).sort("category"))
        subtotal, tax, total = calculate_order_total(order.get('items', []))
        order['subtotal'] = subtotal
        order['tax'] = tax
        order['total_amount'] = total

        return render_template('order_view.html', order=order, menu_items=menu_items, db_error=db_error_flag)

    except errors.PyMongoError as e:
        flash(f"Database error loading order: {e}", "danger")
        print(f"PyMongoError loading order {order_id}: {e}")
        return redirect(url_for('index'))
    except Exception as e:
        flash(f"Invalid order ID or error loading order: {e}", "danger")
        print(f"Error loading order {order_id}: {e}")
        return redirect(url_for('index'))

@app.route('/order/add_item/<order_id>', methods=['POST'])
def order_add_item(order_id):
    db_instance = get_db()
    if db_instance is None:
        flash("Database connection error. Cannot add item.", "danger")
        return redirect(request.referrer or url_for('order_view', order_id=order_id))

    try:
        order_obj_id = ObjectId(order_id)
        menu_item_id = request.form.get('menu_item_id')
        quantity = int(request.form.get('quantity', 1))

        if not menu_item_id or quantity <= 0:
             flash("Invalid menu item or quantity.", "warning")
             return redirect(url_for('order_view', order_id=order_id))

        menu_item = db_instance.menu_items.find_one({"_id": ObjectId(menu_item_id)})
        if not menu_item or not menu_item.get('is_available'):
             flash("Menu item not found or unavailable.", "warning")
             return redirect(url_for('order_view', order_id=order_id))

        order_item = {
            "menu_item_id": menu_item['_id'], "name": menu_item['name'],
            "price": menu_item['price'], "quantity": quantity,
            "status": "pending"
        }
        update_result = db_instance.orders.update_one(
            {"_id": order_obj_id, "status": "open"},
            {"$push": {"items": order_item}, "$set": {"updated_at": datetime.utcnow()}}
        )
        if update_result.matched_count == 0:
             flash("Could not add item. Order not found or not open.", "warning")
             return redirect(url_for('order_view', order_id=order_id))

        order = db_instance.orders.find_one({"_id": order_obj_id})
        if order:
            subtotal, tax, total = calculate_order_total(order.get('items', []))
            db_instance.orders.update_one(
                 {"_id": order_obj_id},
                 {"$set": {"subtotal": subtotal, "tax": tax, "total_amount": total, "updated_at": datetime.utcnow()}}
             )
            flash(f"Added {quantity} x {menu_item['name']} to order.", "success")
        else:
             flash("Item added, but failed to recalc totals.", "warning")

        return redirect(url_for('order_view', order_id=order_id))

    except ValueError:
         flash("Invalid quantity.", "danger")
         return redirect(url_for('order_view', order_id=order_id))
    except Exception as e:
        flash(f"Error adding item: {e}", "danger")
        print(f"Error adding item to order {order_id}: {e}")
        return redirect(url_for('order_view', order_id=order_id))

@app.route('/order/update_item_status/<order_id>/<int:item_index>', methods=['POST'])
def order_update_item_status(order_id, item_index):
    db_instance = get_db()
    if db_instance is None:
        flash("Database connection error. Cannot update item status.", "danger")
        return jsonify({"success": False, "error": "Database connection error."}), 500

    try:
        order_obj_id = ObjectId(order_id)
        new_status = request.form.get('status')
        valid_statuses = ["pending", "preparing", "served", "cancelled"]

        if new_status not in valid_statuses:
             flash("Invalid item status provided.", "warning")
             return jsonify({"success": False, "error": "Invalid item status."}), 400

        update_key = f"items.{item_index}.status"
        result = db_instance.orders.update_one(
            {"_id": order_obj_id, f"items.{item_index}": {"$exists": True}},
            {"$set": {update_key: new_status, "updated_at": datetime.utcnow()}}
        )

        if result.matched_count > 0:
            recalculate_totals = False
            if new_status == 'cancelled':
                recalculate_totals = True

            if recalculate_totals:
                order = db_instance.orders.find_one({"_id": order_obj_id})
                if order:
                    subtotal, tax, total = calculate_order_total(order.get('items', []))
                    db_instance.orders.update_one(
                         {"_id": order_obj_id},
                         {"$set": {"subtotal": subtotal, "tax": tax, "total_amount": total, "updated_at": datetime.utcnow()}}
                     )
                else:
                    print(f"Warning: Item status updated for {order_id}, but order not found for totals recalc.")

            flash(f"Item status updated to {new_status}.", "success")
            return jsonify({"success": True, "new_status": new_status})
        else:
            flash("Order or item index not found.", "warning")
            return jsonify({"success": False, "error": "Order or item index not found."}), 404

    except Exception as e:
        print(f"Error updating item status for order {order_id}, item {item_index}: {e}")
        flash(f"Error updating item status: {e}", "danger")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/order/close/<order_id>', methods=['POST'])
def order_close(order_id):
    db_instance = get_db()
    if db_instance is None:
        flash("Database connection error.", "danger")
        return redirect(request.referrer or url_for('index'))

    try:
        obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": obj_id})

        if not order:
             flash("Order not found.", "warning")
             return redirect(request.referrer or url_for('index'))

        if order['status'] == 'open':
            if not order.get('items'):
                flash("Cannot close an empty order. Add items or cancel the order.", "warning")
                return redirect(url_for('order_view', order_id=order_id))

            subtotal, tax, total = calculate_order_total(order.get('items', []))
            db_instance.orders.update_one(
                {"_id": obj_id},
                {"$set": {
                    "status": "closed", "closed_time": datetime.utcnow(),
                    "subtotal": subtotal, "tax": tax, "total_amount": total,
                    "updated_at": datetime.utcnow()
                    }}
            )
            flash("Order closed and ready for billing.", "success")
            return redirect(url_for('billing'))
        elif order['status'] == 'closed':
             flash(f"Order is already closed.", "info")
             return redirect(url_for('billing'))
        else:
             flash(f"Cannot close order. Status is '{order['status']}'.", "warning")
             return redirect(request.referrer or url_for('order_view', order_id=order_id))

    except Exception as e:
        flash(f"Error closing order: {e}", "danger")
        print(f"Error closing order {order_id}: {e}")
        return redirect(request.referrer or url_for('index'))

# --- Billing & Invoicing ---
@app.route('/billing')
def billing():
    db_instance = get_db()
    db_error_flag = db_instance is None
    closed_orders = []

    if db_instance is None:
        flash("Database connection error.", "danger")
        return render_template('billing.html', orders=closed_orders, db_error=True)

    try:
        closed_orders = list(db_instance.orders.find({"status": "closed"}).sort("closed_time", -1))
    except Exception as e:
        flash(f"Error fetching closed orders: {e}", "danger")
        print(f"Error fetching closed orders: {e}")
        db_error_flag = True

    return render_template('billing.html', orders=closed_orders, db_error=db_error_flag)

@app.route('/bill/view/<order_id>')
def bill_view(order_id):
    db_instance = get_db()
    if db_instance is None:
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

        if order['status'] not in ['closed', 'billed']:
             flash("Order is not yet closed for billing.", "warning")
             return redirect(url_for('order_view', order_id=order_id))

        bill = db_instance.bills.find_one({"order_id": obj_id})
        subtotal, tax, total = calculate_order_total(order.get('items', []))
        order['subtotal'] = subtotal
        order['tax'] = tax
        order['total_amount'] = bill['total_amount'] if bill else total

        # Pass tax_rate from config to template
        return render_template('bill_view.html', order=order, bill=bill, tax_rate=config.TAX_RATE_PERCENT)

    except errors.PyMongoError as e:
        flash(f"Database error loading bill view: {e}", "danger")
        print(f"PyMongoError loading bill view for {order_id}: {e}")
        return redirect(url_for('billing'))
    except Exception as e:
        flash(f"Invalid order ID or error loading bill: {e}", "danger")
        print(f"Error loading bill view for {order_id}: {e}")
        return redirect(url_for('billing'))

@app.route('/bill/finalize/<order_id>', methods=['POST'])
def bill_finalize(order_id):
    db_instance = get_db()
    if db_instance is None:
        flash("Database connection error.", "danger")
        return redirect(url_for('billing'))

    try:
        order_obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": order_obj_id})
        if not order:
            flash("Order not found.", "warning")
            return redirect(url_for('billing'))

        if order['status'] == 'billed':
             flash("This order has already been billed.", "info")
             return redirect(url_for('bill_view', order_id=order_id))
        elif order['status'] != 'closed':
             flash(f"Cannot finalize bill. Order status is '{order['status']}'.", "warning")
             return redirect(url_for('bill_view', order_id=order_id))

        existing_bill = db_instance.bills.find_one({"order_id": order_obj_id})
        if existing_bill:
            flash("Bill already finalized (possible double submission).", "warning")
            return redirect(url_for('bill_view', order_id=order_id))

        payment_method = request.form.get('payment_method', 'Cash')
        discount = float(request.form.get('discount', 0.0))

        subtotal, tax, _ = calculate_order_total(order.get('items', []))
        total_before_discount = subtotal + tax
        total_after_discount = total_before_discount - discount
        if total_after_discount < 0: total_after_discount = 0

        bill_doc = {
            "order_id": order['_id'], "table_number": order.get('table_number'),
            "items": order.get('items', []), "subtotal": subtotal, "tax": tax,
            "tax_rate_percent": config.TAX_RATE_PERCENT, "discount": discount,
            "total_amount": total_after_discount, "payment_method": payment_method,
            "payment_status": "paid", "billed_at": datetime.utcnow()
        }
        bill_result = db_instance.bills.insert_one(bill_doc)
        final_bill_id = bill_result.inserted_id

        db_instance.orders.update_one(
            {"_id": order_obj_id},
            {"$set": {
                "status": "billed", "final_bill_id": final_bill_id,
                "updated_at": datetime.utcnow()
                }}
        )

        table_update = {"$set": {"status": "available", "updated_at": datetime.utcnow()}, "$unset": {"current_order_id": ""}}
        if order.get('table_id'):
             db_instance.tables.update_one({"_id": order['table_id']}, table_update)
        else:
             db_instance.tables.update_one({"table_number": order.get('table_number')}, table_update)

        flash(f"Bill for Order {order_id} finalized successfully! Payment: {payment_method}.", "success")
        return redirect(url_for('billing'))

    except ValueError:
        flash("Invalid discount value. Please enter a number.", "danger")
        return redirect(url_for('bill_view', order_id=order_id))
    except Exception as e:
        flash(f"Error finalizing bill: {e}", "danger")
        print(f"Error finalizing bill {order_id}: {e}")
        return redirect(url_for('bill_view', order_id=order_id))

# --- Kitchen Display System (KDS) ---
@app.route('/kds')
def kds():
    db_instance = get_db()
    db_error_flag = db_instance is None
    kds_items = []

    if db_instance is None:
        flash("Database connection error.", "danger")
        return render_template('kds.html', kds_items=[], db_error=True)

    try:
        open_orders = list(db_instance.orders.find(
            {"status": "open"},
            {"_id": 1, "table_number": 1, "items": 1, "order_time": 1}
            ).sort("order_time"))

        for order in open_orders:
            order_id_str = str(order['_id'])
            for index, item in enumerate(order.get('items', [])):
                if item.get('status') in ['pending', 'preparing']:
                    kds_item = {
                        "order_id": order_id_str, "table_number": order.get('table_number', 'N/A'),
                        "item_name": item.get('name'), "quantity": item.get('quantity'),
                        "status": item.get('status'), "item_index": index,
                        "order_time": order.get('order_time')
                    }
                    kds_items.append(kds_item)

        kds_items.sort(key=lambda x: (x['order_time'] or datetime.min, x['status'] == 'pending'))

    except Exception as e:
         flash(f"Error fetching KDS items: {e}", "danger")
         print(f"Error fetching KDS items: {e}")
         db_error_flag = True

    return render_template('kds.html', kds_items=kds_items, db_error=db_error_flag)

# --- Analytics & Reporting ---
@app.route('/reports')
def reports():
    db_instance = get_db()
    db_error_flag = db_instance is None
    report_data = { "today_total_sales": 0, "today_bill_count": 0, "top_selling_items": [] }

    if db_instance is None:
        flash("Database connection error.", "danger")
        return render_template('reports.html', report_data=report_data, db_error=True)

    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start.replace(hour=23, minute=59, second=59, microsecond=999999)
        pipeline_today = [
            {"$match": {"billed_at": {"$gte": today_start, "$lte": today_end}, "payment_status": "paid"}},
            {"$group": {"_id": None, "total_sales": {"$sum": "$total_amount"}, "count": {"$sum": 1}}}
        ]
        today_sales_result = list(db_instance.bills.aggregate(pipeline_today))
        today_sales = today_sales_result[0] if today_sales_result else {"total_sales": 0, "count": 0}
        report_data["today_total_sales"] = today_sales.get('total_sales', 0)
        report_data["today_bill_count"] = today_sales.get('count', 0)

        pipeline_top_items = [
             {"$match": {"payment_status": "paid"}},
             {"$unwind": "$items"},
             {"$match": {"items.status": {"$ne": "cancelled"}}},
             {"$group": {"_id": "$items.name", "total_quantity": {"$sum": "$items.quantity"}}},
             {"$sort": {"total_quantity": -1}},
             {"$limit": 5}
        ]
        top_items = list(db_instance.bills.aggregate(pipeline_top_items))
        report_data["top_selling_items"] = top_items

    except Exception as e:
        flash(f"Error generating reports: {e}", "danger")
        print(f"Error generating reports: {e}")
        db_error_flag = True

    return render_template('reports.html', report_data=report_data, db_error=db_error_flag)


# --- UPDATED Context Processors ---
@app.context_processor
def inject_global_vars():
    """Inject global variables/config into all templates."""
    db_status_ok = get_db() is not None # Correct check
    now = datetime.utcnow() # Get current UTC time
    return dict(
        config=config,
        db_status_ok=db_status_ok, # Pass DB status flag
        now=now, # Pass datetime object for use in templates if needed
        current_year=now.year # Pass current year for footer
        )
# --- END UPDATED Context Processors ---

# --- Main Execution ---
if __name__ == '__main__':
    print("Starting Flask development server...")
    # Use host='0.0.0.0' to make accessible on network
    # Use threaded=True only for DEVELOPMENT server
    app.run(host='0.0.0.0', port=5000, debug=app.config['DEBUG'], threaded=True)