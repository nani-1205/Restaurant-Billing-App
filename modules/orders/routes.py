# modules/orders/routes.py
from flask import render_template, request, redirect, url_for, flash, jsonify # Added jsonify for potential future AJAX
from bson.objectid import ObjectId
from bson.errors import InvalidId
import datetime
from database import get_db
from . import bp

ORDER_STATUSES = ['pending', 'preparing', 'ready', 'served', 'cancelled', 'billed']

# Helper to get details needed for display
def get_order_display_details(db, orders):
    table_ids = [o.get('table_id') for o in orders if o.get('table_id')]
    menu_item_ids = []
    for o in orders:
        if 'items' in o:
            menu_item_ids.extend([item.get('menu_item_id') for item in o['items'] if item.get('menu_item_id')])

    tables = {str(t['_id']): t['number'] for t in db.tables.find({'_id': {'$in': table_ids}}, {'number': 1})} if table_ids else {}
    menu_items = {str(i['_id']): i for i in db.menu_items.find({'_id': {'$in': menu_item_ids}})} if menu_item_ids else {}

    for order in orders:
        # Assign table number
        order['table_number'] = tables.get(str(order.get('table_id')), 'N/A')
        # Assign item names and ensure price_at_order exists
        if 'items' in order:
            for item in order['items']:
                item_details = menu_items.get(str(item.get('menu_item_id')))
                if item_details:
                    item['name'] = item_details.get('name', 'Unknown Item')
                    # Ensure price_at_order exists, fallback to current price if missing (shouldn't happen for new orders)
                    if 'price_at_order' not in item:
                        item['price_at_order'] = item_details.get('price', 0)
                else:
                     item['name'] = 'Deleted Item'
                     if 'price_at_order' not in item:
                         item['price_at_order'] = 0 # Avoid errors if item deleted
        # Format timestamp nicely (optional)
        if isinstance(order.get('timestamp'), datetime.datetime):
             order['timestamp_str'] = order['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
        else:
             order['timestamp_str'] = "N/A"


@bp.route('/')
@bp.route('/status/<filter_status>')
def list_orders(filter_status=None):
    db = get_db()
    query = {}
    title = "All Orders"
    if filter_status and filter_status in ORDER_STATUSES:
        query = {'status': filter_status}
        title = f"{filter_status.capitalize()} Orders"
    elif filter_status == 'active':
         query = {'status': {'$nin': ['billed', 'cancelled']}}
         title = "Active Orders"

    orders = list(db.orders.find(query).sort("timestamp", -1)) # Show newest first
    get_order_display_details(db, orders) # Add table numbers and item names

    # Count orders by status for filtering links
    status_counts = db.orders.aggregate([
        {'$group': {'_id': '$status', 'count': {'$sum': 1}}}
    ])
    counts = {item['_id']: item['count'] for item in status_counts}
    active_count = sum(v for k, v in counts.items() if k not in ['billed', 'cancelled'])


    return render_template(
        'orders/list.html',
        orders=orders,
        title=title,
        statuses=ORDER_STATUSES,
        status_counts=counts,
        active_count=active_count,
        current_filter=filter_status
        )

@bp.route('/new', methods=['GET', 'POST'])
def new_order():
    db = get_db()
    # Only show tables that are not 'occupied' or 'unavailable'
    available_tables = list(db.tables.find({'status': {'$nin': ['occupied', 'unavailable']}}).sort('number'))
    menu_items = list(db.menu_items.find({'is_available': True}).sort('category').sort('name'))

    if request.method == 'POST':
        table_id_str = request.form.get('table_id')
        # These will come from dynamically added rows in the form
        item_ids = request.form.getlist('item_id[]')
        quantities = request.form.getlist('quantity[]')
        notes = request.form.get('notes', '')

        if not table_id_str:
            flash('Please select a table.', 'warning')
            return render_template('orders/form.html', title="New Order", tables=available_tables, menu_items=menu_items, current_data=request.form)

        if not item_ids or not quantities or len(item_ids) != len(quantities):
             flash('Please add at least one item with a valid quantity.', 'warning')
             return render_template('orders/form.html', title="New Order", tables=available_tables, menu_items=menu_items, current_data=request.form)

        try:
            table_id = ObjectId(table_id_str)
        except InvalidId:
            flash('Invalid Table ID.', 'danger')
            return render_template('orders/form.html', title="New Order", tables=available_tables, menu_items=menu_items, current_data=request.form)

        order_items = []
        total_amount = 0.0
        item_object_ids = []
        valid_quantities = {}

        # Validate items and quantities first
        valid_input = True
        for i in range(len(item_ids)):
            item_id_str = item_ids[i]
            qty_str = quantities[i]
            if not item_id_str or not qty_str: continue # Skip potentially empty rows if JS adds them

            try:
                item_obj_id = ObjectId(item_id_str)
                quantity = int(qty_str)
                if quantity <= 0:
                    flash(f"Quantity must be positive for item ID {item_id_str}.", "warning")
                    valid_input = False
                    continue # Skip this item but continue validation
                item_object_ids.append(item_obj_id)
                valid_quantities[item_id_str] = quantity # Store quantity keyed by string ID for lookup
            except (InvalidId, ValueError):
                flash(f"Invalid item ID ({item_id_str}) or quantity ({qty_str}).", "warning")
                valid_input = False
                # Stop processing if invalid data encountered? Or just skip? Skipping for now.

        if not valid_input or not item_object_ids:
            flash("Order contains invalid items or quantities.", "danger")
            return render_template('orders/form.html', title="New Order", tables=available_tables, menu_items=menu_items, current_data=request.form)


        # Fetch prices for validated items ONCE
        selected_item_docs = {str(item['_id']): item for item in db.menu_items.find({'_id': {'$in': item_object_ids}, 'is_available': True})}

        # Build order_items list using fetched data
        for item_obj_id in item_object_ids:
            item_id_str = str(item_obj_id)
            menu_item = selected_item_docs.get(item_id_str)
            quantity = valid_quantities[item_id_str]

            if not menu_item:
                flash(f"Menu item {item_id_str} not found or is unavailable.", "warning")
                continue # Skip if item became unavailable or was invalid initially

            price_at_order = menu_item['price']
            order_items.append({
                'menu_item_id': item_obj_id,
                'quantity': quantity,
                'price_at_order': price_at_order,
                'name': menu_item['name'] # Store name for convenience
            })
            total_amount += price_at_order * quantity

        if not order_items:
            flash('No valid and available items were added to the order.', 'warning')
            return render_template('orders/form.html', title="New Order", tables=available_tables, menu_items=menu_items, current_data=request.form)

        # Check if table still exists and is available
        table = db.tables.find_one({'_id': table_id})
        if not table:
             flash(f"Selected table no longer exists.", "danger")
             return render_template('orders/form.html', title="New Order", tables=available_tables, menu_items=menu_items, current_data=request.form)
        if table.get('status') in ['occupied', 'unavailable']:
             flash(f"Table {table['number']} is no longer available ({table.get('status')}). Please select another table.", "warning")
             # Refresh table list in case status changed while user was filling form
             available_tables = list(db.tables.find({'status': {'$nin': ['occupied', 'unavailable']}}).sort('number'))
             return render_template('orders/form.html', title="New Order", tables=available_tables, menu_items=menu_items, current_data=request.form)


        new_order_doc = {
            'table_id': table_id,
            'items': order_items,
            'status': 'pending', # Initial status
            'total_amount': round(total_amount, 2), # Round to 2 decimal places
            'notes': notes,
            'timestamp': datetime.datetime.utcnow()
        }

        try:
            # --- Use a Transaction (Optional but recommended for consistency) ---
            # with db.client.start_session() as session:
            #     with session.with_transaction():
            #         # Insert order
            #         insert_result = db.orders.insert_one(new_order_doc, session=session)
            #         # Update table status to 'occupied'
            #         update_result = db.tables.update_one({'_id': table_id}, {'$set': {'status': 'occupied'}}, session=session)
            #         if update_result.matched_count == 0:
            #              raise Exception("Table update failed, aborting transaction.") # Aborts transaction
            #         # TODO: Add inventory update logic here within the transaction
            #         # update_inventory(db, order_items, session=session)
            # ---------------------------------------------------------------------

            # --- Without Transaction (Simpler, but less safe) ---
            insert_result = db.orders.insert_one(new_order_doc)
            update_result = db.tables.update_one({'_id': table_id}, {'$set': {'status': 'occupied'}})
            if update_result.matched_count == 0:
                # Problem: Order created but table not marked occupied. Manual intervention needed.
                # Could try to delete the order, but it's messy. Transactions are better.
                 flash(f"Order placed (ID: {insert_result.inserted_id}), BUT FAILED TO UPDATE TABLE STATUS.", "danger")
                 # Don't redirect yet, let user see the error
                 return render_template('orders/form.html', title="New Order", tables=available_tables, menu_items=menu_items, current_data=request.form)

            # TODO: Basic Inventory Update (Decrement stock - needs dedicated function)
            # update_inventory(db, order_items)

            flash(f'Order placed successfully for table {table["number"]}!', 'success')
            # Redirect to active orders or specific table view? Active orders for now.
            return redirect(url_for('orders.list_orders', filter_status='active'))

        except Exception as e:
            flash(f'Error placing order: {e}', 'danger')
            # Log the error e
            print(f"Order placement error: {e}") # Basic logging
            return render_template('orders/form.html', title="New Order", tables=available_tables, menu_items=menu_items, current_data=request.form)

    # GET request
    return render_template('orders/form.html', title="New Order", tables=available_tables, menu_items=menu_items, current_data={})

@bp.route('/view/<order_id>')
def view_order(order_id):
    db = get_db()
    try:
        obj_id = ObjectId(order_id)
        order = db.orders.find_one({'_id': obj_id})
        if not order:
            flash('Order not found.', 'warning')
            return redirect(url_for('orders.list_orders'))

        # Get display details for this single order
        get_order_display_details(db, [order])

        return render_template('orders/view.html', title=f"Order Details", order=order, statuses=ORDER_STATUSES)
    except InvalidId:
        flash('Invalid Order ID.', 'danger')
        return redirect(url_for('orders.list_orders'))


@bp.route('/update_status/<order_id>', methods=['POST'])
def update_order_status(order_id):
    db = get_db()
    new_status = request.form.get('status')

    if not new_status or new_status not in ORDER_STATUSES:
         flash('Invalid status selected.', 'warning')
         # Redirect back to where the user came from if possible, otherwise list
         return redirect(request.referrer or url_for('orders.list_orders'))

    try:
        obj_id = ObjectId(order_id)

        # Optional: Add logic checks (e.g., cannot change status if 'billed' or 'cancelled')
        current_order = db.orders.find_one({'_id': obj_id}, {'status': 1})
        if not current_order:
             flash('Order not found.', 'warning')
             return redirect(request.referrer or url_for('orders.list_orders'))

        if current_order.get('status') in ['billed', 'cancelled']:
             flash(f"Cannot change status of a {current_order.get('status')} order.", 'warning')
             return redirect(request.referrer or url_for('orders.list_orders'))


        result = db.orders.update_one(
            {'_id': obj_id},
            {'$set': {'status': new_status}}
        )
        if result.matched_count:
            flash(f'Order status updated to {new_status}.', 'success')
            # If cancelled, should we free up the table? Maybe only if it's the *last* active order for that table.
            if new_status == 'cancelled':
                order = db.orders.find_one({'_id': obj_id}) # Get full order to find table_id
                table_id = order.get('table_id')
                if table_id:
                    # Check if there are OTHER non-billed/non-cancelled orders for this table
                    other_orders = db.orders.count_documents({
                        'table_id': table_id,
                        '_id': {'$ne': obj_id},
                        'status': {'$nin': ['billed', 'cancelled']}
                    })
                    if other_orders == 0:
                        # This was the last active order, make table available
                         db.tables.update_one({'_id': table_id, 'status': 'occupied'}, {'$set': {'status': 'available'}})
                         flash(f'Table {order.get("table_number", table_id)} automatically set to available.', 'info')
        else:
            flash('Order not found.', 'warning')
    except InvalidId:
        flash('Invalid Order ID.', 'danger')
    except Exception as e:
         flash(f'Error updating order status: {e}', 'danger')
         print(f"Status update error: {e}") # Log error

    return redirect(request.referrer or url_for('orders.list_orders'))

# Placeholder for inventory update function
# def update_inventory(db, order_items, session=None):
#     print(f"TODO: Update inventory for items: {order_items}") # Add actual logic
#     # Needs recipe mapping and inventory collection access
#     pass