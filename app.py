import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from pymongo import MongoClient, errors
from bson import ObjectId
from datetime import datetime, timedelta, timezone # Added timedelta, timezone
from dateutil.relativedelta import relativedelta # Added relativedelta
import urllib.parse # For encoding credentials
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
            # Ensure MONGO_URI is correctly constructed in config.py
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
    if not items: # Handle empty item list
        return 0.0, 0.0, 0.0
    subtotal = sum(item['price'] * item['quantity'] for item in items if item.get('status') != 'cancelled')
    tax = (subtotal * config.TAX_RATE_PERCENT) / 100.0
    total = subtotal + tax
    return subtotal, tax, total

# --- Routes ---

# --- Index Route (Dashboard) ---
@app.route('/')
def index():
    """Dashboard/Home Page"""
    db_instance = get_db()
    db_error_flag = db_instance is None

    tables_metrics = {"total": 0, "available": 0}
    orders_metrics = {"active": 0, "pending_bills": 0, "total": 0}
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
            orders_metrics["total"] = tables_metrics["total"] if tables_metrics["total"] > 0 else 1

            # Sales Metrics (Today)
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            pipeline_today = [
                {"$match": {"billed_at": {"$gte": today_start, "$lt": today_end}, "payment_status": "paid"}},
                {"$group": {"_id": None, "total_sales": {"$sum": "$total_amount"}, "count": {"$sum": 1}}}
            ]
            today_sales_result = list(db_instance.bills.aggregate(pipeline_today))
            today_sales_data = today_sales_result[0] if today_sales_result else {"total_sales": 0, "count": 0}
            sales_metrics["today"] = today_sales_data.get('total_sales', 0)
            sales_metrics["count"] = today_sales_data.get('count', 0)

            # KDS Preview (e.g., first 3 items)
            open_orders = list(db_instance.orders.find(
                {"status": "open"},
                {"_id": 1, "table_number": 1, "items": 1, "order_time": 1}
            ).sort("order_time").limit(5))

            preview_count = 0
            max_preview = 3
            for order in open_orders:
                if preview_count >= max_preview: break
                for item in order.get('items', []):
                    if item.get('status') in ['pending', 'preparing']:
                        kds_item = {
                            "table_number": order.get('table_number', 'N/A'),
                            "item_name": item.get('name'), "quantity": item.get('quantity'),
                            "status": item.get('status'), "order_time": order.get('order_time')
                        }
                        kds_preview.append(kds_item)
                        preview_count += 1
                        if preview_count >= max_preview: break

        except errors.PyMongoError as e:
             print(f"Database error fetching dashboard metrics: {e}")
             flash("Could not load all dashboard metrics due to a database error.", "warning")
             db_error_flag = True
        except Exception as e:
             print(f"Unexpected error fetching dashboard metrics: {e}")
             flash("An unexpected error occurred while loading dashboard metrics.", "danger")
             db_error_flag = True

    else:
         flash("Database connection error. Please check configuration and MongoDB status.", "danger")

    return render_template('index.html',
                           db_error=db_error_flag,
                           tables_metrics=tables_metrics,
                           orders_metrics=orders_metrics,
                           sales_metrics=sales_metrics,
                           kds_preview=kds_preview
                           )

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
                    "name": name, "description": description, "price": price,
                    "category": category, "is_available": is_available,
                    "created_at": datetime.now(timezone.utc)
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
                    flash("Item name and non-negative price required.", "warning")
                    return render_template('menu_edit.html', item=item)

                db_instance.menu_items.update_one(
                    {"_id": obj_id},
                    {"$set": {
                        "name": name, "description": description, "price": price,
                        "category": category, "is_available": is_available,
                        "updated_at": datetime.now(timezone.utc)
                    }}
                )
                flash(f"Menu item '{name}' updated successfully!", "success")
                return redirect(url_for('menu_manage'))
            except ValueError:
                 flash("Invalid price format.", "danger")
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
        flash(f"Invalid item ID or error: {e}", "danger")
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
        if result.deleted_count > 0: flash("Menu item deleted.", "success")
        else: flash("Menu item not found.", "warning")
    except Exception as e:
        flash(f"Error deleting menu item: {e}", "danger")
        print(f"Error deleting menu item {item_id}: {e}")
    return redirect(url_for('menu_manage'))

@app.route('/menu/toggle_availability/<item_id>', methods=['POST'])
def menu_toggle_availability(item_id):
    db_instance = get_db()
    if db_instance is None: return jsonify({"success": False, "error": "Database error."}), 500
    try:
        obj_id = ObjectId(item_id)
        item = db_instance.menu_items.find_one({"_id": obj_id}, {"is_available": 1})
        if item:
            new_status = not item.get('is_available', False)
            db_instance.menu_items.update_one({"_id": obj_id}, {"$set": {"is_available": new_status}})
            return jsonify({"success": True, "new_status": new_status})
        else: return jsonify({"success": False, "error": "Item not found"}), 404
    except Exception as e:
        print(f"Error toggling availability for {item_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# --- Table Management ---
@app.route('/tables', methods=['GET', 'POST'])
def tables_manage():
    db_instance = get_db()
    db_error_flag = db_instance is None
    if db_instance is None and request.method == 'POST':
         flash("Database error. Cannot add table.", "danger")
         return redirect(url_for('tables_manage'))
    elif db_instance is None:
        flash("Database connection error.", "danger")
        return render_template('tables_manage.html', tables=[], db_error=True)

    if request.method == 'POST':
        try:
            table_number = request.form['table_number']
            capacity = int(request.form['capacity'])
            if not table_number or capacity <= 0:
                 flash("Valid table number and positive capacity required.", "warning")
            elif db_instance.tables.find_one({"table_number": table_number}):
                flash(f"Table '{table_number}' already exists.", "warning")
            else:
                db_instance.tables.insert_one({
                    "table_number": table_number, "capacity": capacity,
                    "status": "available", "created_at": datetime.now(timezone.utc)
                })
                flash(f"Table '{table_number}' added.", "success")
        except ValueError: flash("Invalid capacity format.", "danger")
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
        flash("Database error. Cannot update status.", "danger")
        return redirect(url_for('tables_manage'))
    try:
        obj_id = ObjectId(table_id)
        new_status = request.form.get('status')
        valid_statuses = ["available", "occupied", "reserved", "cleaning"]
        if not new_status or new_status not in valid_statuses:
             flash("Invalid status.", "warning")
             return redirect(url_for('tables_manage'))

        update_doc = {"$set": {"status": new_status, "updated_at": datetime.now(timezone.utc)}}
        if new_status == "available": update_doc["$unset"] = {"current_order_id": ""}

        result = db_instance.tables.update_one({"_id": obj_id}, update_doc)
        if result.matched_count > 0: flash(f"Table status updated to '{new_status}'.", "success")
        else: flash("Table not found.", "warning")
    except Exception as e:
        flash(f"Error updating status: {e}", "danger")
        print(f"Error updating table status for {table_id}: {e}")
    return redirect(url_for('tables_manage'))

@app.route('/tables/delete/<table_id>', methods=['POST'])
def table_delete(table_id):
    db_instance = get_db()
    if db_instance is None:
        flash("Database error.", "danger")
        return redirect(url_for('tables_manage'))
    try:
        obj_id = ObjectId(table_id)
        table = db_instance.tables.find_one({"_id": obj_id})
        if table and table.get("status") == "occupied":
             flash("Cannot delete occupied table.", "warning")
             return redirect(url_for('tables_manage'))
        result = db_instance.tables.delete_one({"_id": obj_id})
        if result.deleted_count > 0: flash("Table deleted.", "success")
        else: flash("Table not found.", "warning")
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
            flash(f"Table {table.get('table_number', table_id)} already has open order.", "info")
            return redirect(url_for('order_view', order_id=str(existing_order['_id'])))
        elif table.get('status') != 'available':
             flash(f"Table status is '{table.get('status', 'Unknown')}'. Cannot start new order.", "warning")
             return redirect(url_for('tables_manage'))

        if request.method == 'POST':
            order_items = []
            try:
                for key, value in request.form.items():
                    if key.startswith("quantity_") and value and int(value) > 0:
                        quantity = int(value)
                        menu_item_id_str = key.split("quantity_")[1]
                        menu_item = db_instance.menu_items.find_one({"_id": ObjectId(menu_item_id_str)})
                        if menu_item:
                            order_items.append({
                                "menu_item_id": menu_item['_id'], "name": menu_item['name'],
                                "price": menu_item['price'], "quantity": quantity, "status": "pending"
                            })
                        else: print(f"Warn: Initial item ID {menu_item_id_str} not found.")
            except Exception as e:
                 flash(f"Error processing initial items: {e}. Order created empty.", "danger")
                 print(f"Error processing initial items: {e}")
                 order_items = []

            subtotal, tax, total = calculate_order_total(order_items)
            new_order = {
                "table_id": table_obj_id, "table_number": table["table_number"], "items": order_items,
                "status": "open", "order_time": datetime.now(timezone.utc), "subtotal": subtotal,
                "tax": tax, "total_amount": total, "created_at": datetime.now(timezone.utc)
            }
            result = db_instance.orders.insert_one(new_order)
            db_instance.tables.update_one(
                {"_id": table_obj_id},
                {"$set": {"status": "occupied", "current_order_id": result.inserted_id, "updated_at": datetime.now(timezone.utc)}}
            )
            flash(f"New order started for Table {table.get('table_number', table_id)}.", "success")
            if not order_items and request.form: flash("No initial items added.", "info")
            return redirect(url_for('order_view', order_id=str(result.inserted_id)))

        menu_items = []
        try: menu_items = list(db_instance.menu_items.find({"is_available": True}).sort("category"))
        except Exception as e: print(f"Error fetching menu items: {e}")
        return render_template('order_new.html', table=table, menu_items=menu_items)

    except Exception as e:
        flash(f"Error starting new order: {e}", "danger")
        print(f"Error in order_new for table {table_id}: {e}")
        return redirect(url_for('tables_manage'))

@app.route('/order/view/<order_id>', methods=['GET'])
def order_view(order_id):
    db_instance = get_db()
    if db_instance is None:
        flash("Database connection error.", "danger")
        return redirect(url_for('index'))
    try:
        order = db_instance.orders.find_one({"_id": ObjectId(order_id)})
        if not order:
            flash("Order not found.", "warning")
            return redirect(url_for('index'))
        menu_items = list(db_instance.menu_items.find({"is_available": True}).sort("category"))
        subtotal, tax, total = calculate_order_total(order.get('items', []))
        order['subtotal'], order['tax'], order['total_amount'] = subtotal, tax, total
        return render_template('order_view.html', order=order, menu_items=menu_items)
    except Exception as e:
        flash(f"Error loading order: {e}", "danger")
        print(f"Error loading order {order_id}: {e}")
        return redirect(url_for('index'))

@app.route('/order/add_item/<order_id>', methods=['POST'])
def order_add_item(order_id):
    db_instance = get_db()
    if db_instance is None:
        flash("Database error. Cannot add item.", "danger")
        return redirect(request.referrer or url_for('order_view', order_id=order_id))
    try:
        quantity = int(request.form.get('quantity', 1))
        menu_item_id = request.form.get('menu_item_id')
        if not menu_item_id or quantity <= 0:
             flash("Invalid item/quantity.", "warning")
             return redirect(url_for('order_view', order_id=order_id))

        menu_item = db_instance.menu_items.find_one({"_id": ObjectId(menu_item_id)})
        if not menu_item or not menu_item.get('is_available'):
             flash("Item not found/unavailable.", "warning")
             return redirect(url_for('order_view', order_id=order_id))

        order_item = {"menu_item_id": menu_item['_id'], "name": menu_item['name'], "price": menu_item['price'], "quantity": quantity, "status": "pending"}
        update_result = db_instance.orders.update_one(
            {"_id": ObjectId(order_id), "status": "open"},
            {"$push": {"items": order_item}, "$set": {"updated_at": datetime.now(timezone.utc)}}
        )
        if update_result.matched_count == 0:
             flash("Order not found/open.", "warning")
             return redirect(url_for('order_view', order_id=order_id))

        order = db_instance.orders.find_one({"_id": ObjectId(order_id)})
        if order:
            subtotal, tax, total = calculate_order_total(order.get('items', []))
            db_instance.orders.update_one({"_id": ObjectId(order_id)}, {"$set": {"subtotal": subtotal, "tax": tax, "total_amount": total, "updated_at": datetime.now(timezone.utc)}})
            flash(f"Added {quantity} x {menu_item['name']}.", "success")
        else: flash("Item added, recalc failed.", "warning")
        return redirect(url_for('order_view', order_id=order_id))

    except Exception as e:
        flash(f"Error adding item: {e}", "danger")
        print(f"Error adding item to order {order_id}: {e}")
        return redirect(url_for('order_view', order_id=order_id))

@app.route('/order/update_item_status/<order_id>/<int:item_index>', methods=['POST'])
def order_update_item_status(order_id, item_index):
    db_instance = get_db()
    if db_instance is None: return jsonify({"success": False, "error": "Database error."}), 500
    try:
        new_status = request.form.get('status')
        valid_statuses = ["pending", "preparing", "served", "cancelled"]
        if new_status not in valid_statuses: return jsonify({"success": False, "error": "Invalid status."}), 400

        update_key = f"items.{item_index}.status"
        result = db_instance.orders.update_one(
            {"_id": ObjectId(order_id), f"items.{item_index}": {"$exists": True}},
            {"$set": {update_key: new_status, "updated_at": datetime.now(timezone.utc)}}
        )
        if result.matched_count > 0:
            if new_status == 'cancelled':
                order = db_instance.orders.find_one({"_id": ObjectId(order_id)})
                if order:
                    subtotal, tax, total = calculate_order_total(order.get('items', []))
                    db_instance.orders.update_one({"_id": ObjectId(order_id)}, {"$set": {"subtotal": subtotal, "tax": tax, "total_amount": total, "updated_at": datetime.now(timezone.utc)}})
            flash(f"Item status updated.", "success") # For non-JS fallback
            return jsonify({"success": True, "new_status": new_status})
        else: return jsonify({"success": False, "error": "Order/item not found."}), 404
    except Exception as e:
        print(f"Error updating item status {order_id}/{item_index}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/order/close/<order_id>', methods=['POST'])
def order_close(order_id):
    db_instance = get_db()
    if db_instance is None:
        flash("Database error.", "danger")
        return redirect(request.referrer or url_for('index'))
    try:
        obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": obj_id})
        if not order:
             flash("Order not found.", "warning")
             return redirect(request.referrer or url_for('index'))
        if order['status'] == 'open':
            if not order.get('items'):
                flash("Cannot close empty order.", "warning")
                return redirect(url_for('order_view', order_id=order_id))
            subtotal, tax, total = calculate_order_total(order.get('items', []))
            db_instance.orders.update_one({"_id": obj_id}, {"$set": {"status": "closed", "closed_time": datetime.now(timezone.utc), "subtotal": subtotal, "tax": tax, "total_amount": total, "updated_at": datetime.now(timezone.utc)}})
            flash("Order closed.", "success")
            return redirect(url_for('billing'))
        elif order['status'] == 'closed':
             flash("Order already closed.", "info")
             return redirect(url_for('billing'))
        else:
             flash(f"Order status is '{order['status']}'.", "warning")
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
        flash("Database error.", "danger")
        return render_template('billing.html', orders=[], db_error=True)
    try: closed_orders = list(db_instance.orders.find({"status": "closed"}).sort("closed_time", -1))
    except Exception as e:
        flash(f"Error fetching bills: {e}", "danger"); print(f"Error fetching bills: {e}"); db_error_flag = True
    return render_template('billing.html', orders=closed_orders, db_error=db_error_flag)

@app.route('/bill/view/<order_id>')
def bill_view(order_id):
    db_instance = get_db()
    if db_instance is None: flash("Database error.", "danger"); return redirect(url_for('billing'))
    try:
        order = db_instance.orders.find_one({"_id": ObjectId(order_id)})
        if not order: flash("Order not found.", "warning"); return redirect(url_for('billing'))
        if order['status'] not in ['closed', 'billed']:
             flash("Order not closed.", "warning"); return redirect(url_for('order_view', order_id=order_id))
        bill = db_instance.bills.find_one({"order_id": ObjectId(order_id)})
        subtotal, tax, total = calculate_order_total(order.get('items', []))
        order['subtotal'], order['tax'] = subtotal, tax
        order['total_amount'] = bill['total_amount'] if bill else total
        return render_template('bill_view.html', order=order, bill=bill, tax_rate=config.TAX_RATE_PERCENT)
    except Exception as e:
        flash(f"Error loading bill: {e}", "danger"); print(f"Error loading bill {order_id}: {e}"); return redirect(url_for('billing'))

@app.route('/bill/finalize/<order_id>', methods=['POST'])
def bill_finalize(order_id):
    db_instance = get_db()
    if db_instance is None: flash("Database error.", "danger"); return redirect(url_for('billing'))
    try:
        order_obj_id = ObjectId(order_id)
        order = db_instance.orders.find_one({"_id": order_obj_id})
        if not order: flash("Order not found.", "warning"); return redirect(url_for('billing'))
        if order['status'] != 'closed': flash(f"Order status '{order['status']}'.", "warning"); return redirect(url_for('bill_view', order_id=order_id))
        if db_instance.bills.find_one({"order_id": order_obj_id}): flash("Bill already finalized.", "warning"); return redirect(url_for('bill_view', order_id=order_id))

        payment_method = request.form.get('payment_method', 'Cash')
        discount = float(request.form.get('discount', 0.0))
        subtotal, tax, _ = calculate_order_total(order.get('items', []))
        total_after_discount = max(0, (subtotal + tax) - discount)

        bill_doc = {
            "order_id": order['_id'], "table_number": order.get('table_number'), "items": order.get('items', []),
            "subtotal": subtotal, "tax": tax, "tax_rate_percent": config.TAX_RATE_PERCENT, "discount": discount,
            "total_amount": total_after_discount, "payment_method": payment_method, "payment_status": "paid",
            "billed_at": datetime.now(timezone.utc)
        }
        bill_result = db_instance.bills.insert_one(bill_doc)
        db_instance.orders.update_one({"_id": order_obj_id}, {"$set": {"status": "billed", "final_bill_id": bill_result.inserted_id, "updated_at": datetime.now(timezone.utc)}})
        table_update = {"$set": {"status": "available", "updated_at": datetime.now(timezone.utc)}, "$unset": {"current_order_id": ""}}
        if order.get('table_id'): db_instance.tables.update_one({"_id": order['table_id']}, table_update)
        else: db_instance.tables.update_one({"table_number": order.get('table_number')}, table_update)

        flash(f"Bill finalized. Payment: {payment_method}.", "success")
        return redirect(url_for('billing'))
    except ValueError: flash("Invalid discount value.", "danger"); return redirect(url_for('bill_view', order_id=order_id))
    except Exception as e: flash(f"Error finalizing bill: {e}", "danger"); print(f"Error finalizing bill {order_id}: {e}"); return redirect(url_for('bill_view', order_id=order_id))

# --- Kitchen Display System (KDS) ---
@app.route('/kds')
def kds():
    db_instance = get_db(); db_error_flag = db_instance is None; kds_items = []
    if db_instance is None: flash("Database error.", "danger"); return render_template('kds.html', kds_items=[], db_error=True)
    try:
        open_orders = list(db_instance.orders.find({"status": "open"}, {"_id": 1, "table_number": 1, "items": 1, "order_time": 1}).sort("order_time"))
        for order in open_orders:
            for index, item in enumerate(order.get('items', [])):
                if item.get('status') in ['pending', 'preparing']:
                    kds_items.append({
                        "order_id": str(order['_id']), "table_number": order.get('table_number', 'N/A'), "item_name": item.get('name'),
                        "quantity": item.get('quantity'), "status": item.get('status'), "item_index": index, "order_time": order.get('order_time') })
        kds_items.sort(key=lambda x: (x['order_time'] or datetime.min, x['status'] == 'pending'))
    except Exception as e: flash(f"Error fetching KDS items: {e}", "danger"); print(f"Error fetching KDS items: {e}"); db_error_flag = True
    return render_template('kds.html', kds_items=kds_items, db_error=db_error_flag)

# --- Analytics & Reporting ---
@app.route('/reports')
def reports():
    db_instance = get_db()
    db_error_flag = db_instance is None
    report_data = {"total_sales": 0, "bill_count": 0, "top_selling_items": []}
    selected_period = request.args.get('period', 'today')
    start_date, end_date, selected_period_display = None, None, "N/A"
    now = datetime.now(timezone.utc)

    try:
        if selected_period == 'today': start_date = now.replace(hour=0, minute=0, second=0, microsecond=0); end_date = start_date + timedelta(days=1); selected_period_display = "Today"
        elif selected_period == 'yesterday': yesterday = now - timedelta(days=1); start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0); end_date = start_date + timedelta(days=1); selected_period_display = "Yesterday"
        elif selected_period == 'month': start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0); end_date = (start_date + relativedelta(months=1)); selected_period_display = "This Month"
        elif selected_period == 'prev_month': last_month_end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0); start_date = last_month_end - relativedelta(months=1); end_date = last_month_end; selected_period_display = "Last Month"
        elif selected_period == 'year': start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0); end_date = (start_date + relativedelta(years=1)); selected_period_display = "This Year"
        else:
            flash(f"Invalid period '{selected_period}'. Defaulting to 'Today'.", "warning"); selected_period = 'today'
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0); end_date = start_date + timedelta(days=1); selected_period_display = "Today"

        if start_date and end_date and db_instance is not None:
            print(f"Report: {selected_period}, Start: {start_date}, End: {end_date}")
            match_criteria = {"billed_at": {"$gte": start_date, "$lt": end_date}, "payment_status": "paid"}
            pipeline_sales = [{"$match": match_criteria}, {"$group": {"_id": None, "total_sales": {"$sum": "$total_amount"}, "count": {"$sum": 1}}}]
            sales_result = list(db_instance.bills.aggregate(pipeline_sales))
            sales_data = sales_result[0] if sales_result else {"total_sales": 0, "count": 0}
            report_data["total_sales"] = sales_data.get('total_sales', 0); report_data["bill_count"] = sales_data.get('count', 0)
            pipeline_top_items = [{"$match": match_criteria}, {"$unwind": "$items"}, {"$match": {"items.status": {"$ne": "cancelled"}}}, {"$group": {"_id": "$items.name", "total_quantity": {"$sum": "$items.quantity"}}}, {"$sort": {"total_quantity": -1}}, {"$limit": 5}]
            report_data["top_selling_items"] = list(db_instance.bills.aggregate(pipeline_top_items))
        elif db_instance is None: flash("Database connection error.", "danger"); db_error_flag = True
    except Exception as e:
        flash(f"Error generating reports: {e}", "danger"); print(f"Error reports period '{selected_period}': {e}"); db_error_flag = True

    return render_template('reports.html', report_data=report_data, db_error=db_error_flag, selected_period=selected_period, selected_period_display=selected_period_display, start_date=start_date, end_date=end_date)

# --- Context Processors ---
@app.context_processor
def inject_global_vars():
    """Inject global variables/config into all templates."""
    db_status_ok = get_db() is not None
    now_utc = datetime.now(timezone.utc)
    # Make timedelta accessible in templates for date calculations
    from datetime import timedelta
    return dict(
        config=config, db_status_ok=db_status_ok, now=now_utc,
        current_year=now_utc.year, timedelta=timedelta
        )

# --- Main Execution ---
if __name__ == '__main__':
    print("Starting Flask development server...")
    # For development convenience, ensure DB connection is attempted on start
    # connect_db() # Removed as before_request handles this better
    app.run(host='0.0.0.0', port=5000, debug=app.config['DEBUG'], threaded=True)

    # Production Deployment Examples (Commented out)
    # from waitress import serve
    # print("Starting Flask production server with Waitress...")
    # serve(app, host="0.0.0.0", port=5000)
    #
    # Gunicorn command line:
    # gunicorn --bind 0.0.0.0:5000 app:app -w 4 # Example with 4 workers