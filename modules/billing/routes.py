# modules/billing/routes.py
from flask import render_template, request, redirect, url_for, flash
from bson.objectid import ObjectId
from bson.errors import InvalidId
from database import get_db
from . import bp
import datetime
from decimal import Decimal, ROUND_HALF_UP # For precise calculations

@bp.route('/')
def index():
    db = get_db()
    # Find tables that are 'occupied' OR have orders that are not 'billed'/'cancelled'
    # This is more robust than just looking for 'occupied' tables

    # 1. Find all non-final orders
    active_orders = list(db.orders.find(
        {'status': {'$nin': ['billed', 'cancelled']}},
        {'table_id': 1, 'total_amount': 1} # Projection: Only need table_id and total
    ))

    # 2. Get unique table IDs from these orders
    active_table_ids = list(set([o['table_id'] for o in active_orders if o.get('table_id')]))

    # 3. Find tables that are explicitly 'occupied' (might not have orders yet or orders were cancelled)
    occupied_tables = list(db.tables.find(
        {'status': 'occupied'},
        {'_id': 1} # Only need ID
    ))
    occupied_table_ids = [t['_id'] for t in occupied_tables]

    # 4. Combine the lists of table IDs (unique)
    all_relevant_table_ids = list(set(active_table_ids + occupied_table_ids))

    # 5. Fetch details for these tables
    tables_needing_attention = list(db.tables.find({'_id': {'$in': all_relevant_table_ids}}).sort('number'))

    # 6. Add order info (count and total) to each table for display
    for table in tables_needing_attention:
        table_orders = [o for o in active_orders if o.get('table_id') == table['_id']]
        table['active_order_count'] = len(table_orders)
        # Calculate total using Decimal for accuracy
        table['current_total'] = sum(Decimal(str(o.get('total_amount', '0.0'))) for o in table_orders)
        table['current_total_str'] = f"{table['current_total']:.2f}" # Format for display

    return render_template('billing/index.html', title="Billing Dashboard", tables=tables_needing_attention)


@bp.route('/view/<table_id_str>')
def view_bill(table_id_str):
    db = get_db()
    try:
        table_id = ObjectId(table_id_str)
    except InvalidId:
        flash('Invalid Table ID.', 'danger')
        return redirect(url_for('billing.index'))

    table = db.tables.find_one({'_id': table_id})
    if not table:
        flash('Table not found.', 'warning')
        return redirect(url_for('billing.index'))

    # Find all non-billed, non-cancelled orders for this table
    orders = list(db.orders.find({
        'table_id': table_id,
        'status': {'$nin': ['billed', 'cancelled']} # Exclude final states
    }).sort('timestamp'))

    if not orders:
        flash(f'No active orders found for Table {table["number"]} to bill.', 'info')
        # If table is occupied but has no active orders, maybe make it available?
        if table.get('status') == 'occupied':
             update_result = db.tables.update_one({'_id': table_id, 'status': 'occupied'}, {'$set': {'status': 'available'}})
             if update_result.modified_count > 0:
                 flash(f'Table {table["number"]} status set to available as no active orders were found.', 'info')
        return redirect(url_for('billing.index'))

    # Calculate grand total and aggregate items using Decimal for precision
    grand_total = Decimal('0.0')
    combined_items = {} # Use dict to combine same items from multiple orders
    order_ids = [] # Keep track of order IDs included in this bill view

    # Cache menu item details (although name/price should be in order item)
    all_item_ids = []
    for order in orders:
        order_ids.append(order['_id'])
        grand_total += Decimal(str(order.get('total_amount', '0.0'))) # Use Decimal
        if 'items' in order:
             all_item_ids.extend([item['menu_item_id'] for item in order['items']])

    # menu_item_cache = {str(item['_id']): item for item in db.menu_items.find({'_id': {'$in': all_item_ids}})}


    for order in orders:
        for item in order.get('items', []):
            item_id_str = str(item['menu_item_id'])
            # Use price_at_order stored in the item!
            price_each = Decimal(str(item.get('price_at_order', '0.0')))
            quantity = int(item.get('quantity', 0))
            item_name = item.get('name', 'Unknown Item') # Use name stored in item

            key = item_id_str # Group by item ID

            if quantity <= 0: continue # Skip zero quantity items

            if key in combined_items:
                combined_items[key]['quantity'] += quantity
            else:
                combined_items[key] = {
                    'name': item_name,
                    'quantity': quantity,
                    'price_each': price_each,
                    # Subtotal calculated later after quantity aggregation
                }

    # Convert dict back to list and calculate subtotals
    bill_items = []
    calculated_grand_total = Decimal('0.0')
    for key, item_data in combined_items.items():
        subtotal = (item_data['price_each'] * Decimal(item_data['quantity'])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        item_data['subtotal'] = subtotal
        item_data['price_each_str'] = f"{item_data['price_each']:.2f}" # Format for display
        item_data['subtotal_str'] = f"{subtotal:.2f}" # Format for display
        bill_items.append(item_data)
        calculated_grand_total += subtotal

    # Use the calculated total from items as the most accurate figure
    grand_total_str = f"{calculated_grand_total:.2f}"

    # Convert order IDs to strings for the template form
    order_ids_str = [str(oid) for oid in order_ids]

    return render_template('billing/bill_detail.html',
                           title=f"Bill for Table {table['number']}",
                           table=table,
                           items=bill_items,
                           grand_total_str=grand_total_str,
                           order_ids_str=order_ids_str # Pass order IDs for the payment action
                           )

@bp.route('/pay/<table_id_str>', methods=['POST'])
def mark_as_paid(table_id_str):
    db = get_db()
    payment_method = request.form.get('payment_method', 'Cash') # Get payment method
    order_ids_to_bill_str = request.form.getlist('order_ids[]') # Get order IDs from hidden fields

    if not order_ids_to_bill_str:
        flash('No order IDs submitted for payment.', 'danger')
        return redirect(url_for('billing.index'))

    try:
        table_id = ObjectId(table_id_str)
        order_ids = [ObjectId(oid_str) for oid_str in order_ids_to_bill_str]
    except InvalidId:
        flash('Invalid Table ID or Order ID format.', 'danger')
        return redirect(url_for('billing.index'))

    # Verify these orders actually exist and belong to the table and are not already billed/cancelled
    orders_to_update = list(db.orders.find({
        '_id': {'$in': order_ids},
        'table_id': table_id,
        'status': {'$nin': ['billed', 'cancelled']}
    }))

    if len(orders_to_update) != len(order_ids):
        flash('Mismatch in orders found. Some orders might be missing, already billed, or belong to another table.', 'warning')
        # It's safer to redirect back to the bill view to reassess
        return redirect(url_for('billing.view_bill', table_id_str=table_id_str))

    if not orders_to_update:
         flash('No valid, unbilled orders found to mark as paid for this table.', 'warning')
         return redirect(url_for('billing.index'))


    billed_at_time = datetime.datetime.utcnow()
    total_paid = sum(Decimal(str(o.get('total_amount', '0.0'))) for o in orders_to_update)

    try:
        # --- Use Transaction (Recommended) ---
        # with db.client.start_session() as session:
        #     with session.with_transaction():
        #         # 1. Update orders status to 'billed'
        #         update_orders = db.orders.update_many(
        #             {'_id': {'$in': order_ids}},
        #             {'$set': {'status': 'billed', 'billed_at': billed_at_time}},
        #             session=session
        #         )
        #         # 2. Update table status to 'available'
        #         update_table = db.tables.update_one(
        #             {'_id': table_id},
        #             {'$set': {'status': 'available'}},
        #             session=session
        #         )
        #         # 3. (Optional but good) Log payment
        #         # payment_log = { ... details ... }
        #         # db.payments.insert_one(payment_log, session=session)
        #
        #         # Basic check if updates worked as expected within transaction
        #         if update_orders.matched_count != len(order_ids) or update_table.matched_count != 1:
        #             raise Exception("Billing update failed during transaction.")

        # --- Without Transaction ---
        update_orders_result = db.orders.update_many(
            {'_id': {'$in': order_ids}},
            {'$set': {'status': 'billed', 'billed_at': billed_at_time}}
        )
        update_table_result = db.tables.update_one(
             {'_id': table_id},
             {'$set': {'status': 'available'}}
        )

        # Log payment (example)
        payment_log = {
            'table_id': table_id,
            'order_ids': order_ids,
            'amount': float(total_paid), # Store as float or use BSON Decimal128 if needed
            'payment_method': payment_method,
            'timestamp': billed_at_time
        }
        # Ensure 'payments' collection exists (or will be auto-created)
        db.payments.insert_one(payment_log)


        if update_orders_result.modified_count == 0 and update_table_result.modified_count == 0:
             flash('No orders or table status were updated (possibly already done).', 'warning')
        else:
             flash(f'Bill paid (${total_paid:.2f}, {payment_method}). Table {db.tables.find_one({"_id": table_id})["number"]} is now available.', 'success')


    except Exception as e:
        flash(f'Error processing payment: {e}', 'danger')
        print(f"Payment processing error: {e}") # Log error
        # Redirect back to bill view on error
        return redirect(url_for('billing.view_bill', table_id_str=table_id_str))

    return redirect(url_for('billing.index'))