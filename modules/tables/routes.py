# modules/tables/routes.py
from flask import render_template, request, redirect, url_for, flash
from bson.objectid import ObjectId
from bson.errors import InvalidId
from database import get_db
from . import bp
from pymongo.errors import DuplicateKeyError

TABLE_STATUSES = ['available', 'occupied', 'reserved', 'unavailable'] # Define possible statuses

@bp.route('/')
def list_tables():
    db = get_db()
    try:
        # Sort by table number (assuming it's stored numerically)
        tables = list(db.tables.find().sort("number", 1))
    except Exception as e:
        flash(f"Error fetching tables: {e}", "danger")
        tables = []
    return render_template('tables/list.html', tables=tables, title="Tables", statuses=TABLE_STATUSES)

@bp.route('/add', methods=['GET', 'POST'])
def add_table():
    if request.method == 'POST':
        db = get_db()
        number_str = request.form.get('number')
        capacity_str = request.form.get('capacity')
        status = request.form.get('status', 'available')
        location = request.form.get('location', '').strip() # Optional field

        if not number_str or not capacity_str:
            flash('Table Number and Capacity are required.', 'warning')
            return render_template('tables/form.html', title="Add Table", table=request.form, statuses=TABLE_STATUSES)

        try:
            number = int(number_str)
            capacity = int(capacity_str)
            if capacity <= 0 or number <= 0:
                raise ValueError("Number and Capacity must be positive integers.")
            if status not in TABLE_STATUSES:
                 raise ValueError("Invalid status selected.")
        except ValueError as e:
            flash(f'Invalid input: {e}', 'warning')
            return render_template('tables/form.html', title="Add Table", table=request.form, statuses=TABLE_STATUSES)

        new_table = {
            'number': number,
            'capacity': capacity,
            'status': status,
            'location': location
        }
        try:
            db.tables.insert_one(new_table)
            flash(f'Table {number} added successfully!', 'success')
            return redirect(url_for('tables.list_tables'))
        except DuplicateKeyError:
             flash(f'Error: Table number {number} already exists.', 'danger')
        except Exception as e:
             flash(f'Error adding table: {e}', 'danger')
             print(f"Error in add_table: {e}") # Log error

        # Return form with data if error
        return render_template('tables/form.html', title="Add Table", table=request.form, statuses=TABLE_STATUSES)

    # GET request
    return render_template('tables/form.html', title="Add Table", table=None, statuses=TABLE_STATUSES)

@bp.route('/edit/<table_id>', methods=['GET', 'POST'])
def edit_table(table_id):
    db = get_db()
    try:
        obj_id = ObjectId(table_id)
    except InvalidId:
        flash('Invalid Table ID.', 'danger')
        return redirect(url_for('tables.list_tables'))

    table = db.tables.find_one({'_id': obj_id})
    if not table:
        flash('Table not found.', 'warning')
        return redirect(url_for('tables.list_tables'))

    if request.method == 'POST':
        number_str = request.form.get('number')
        capacity_str = request.form.get('capacity')
        status = request.form.get('status')
        location = request.form.get('location', '').strip() # Optional field

        if not number_str or not capacity_str:
            flash('Table Number and Capacity are required.', 'warning')
            form_data = {**table, **request.form} # Merge DB data with form data
            return render_template('tables/form.html', title="Edit Table", table=form_data, table_id=table_id, statuses=TABLE_STATUSES)

        try:
            number = int(number_str)
            capacity = int(capacity_str)
            if capacity <= 0 or number <= 0:
                raise ValueError("Number and Capacity must be positive integers.")
            if status not in TABLE_STATUSES:
                 raise ValueError("Invalid status selected.")
        except ValueError as e:
            flash(f'Invalid input: {e}', 'warning')
            form_data = {**table, **request.form}
            return render_template('tables/form.html', title="Edit Table", table=form_data, table_id=table_id, statuses=TABLE_STATUSES)

        update_data = {
            'number': number,
            'capacity': capacity,
            'status': status,
            'location': location
        }
        try:
            # Check for duplicate number ONLY if the number was changed
            if table['number'] != number:
                 existing_table = db.tables.find_one({'number': number, '_id': {'$ne': obj_id}})
                 if existing_table:
                     raise DuplicateKeyError(f"Table number {number} already exists.")

            db.tables.update_one({'_id': obj_id}, {'$set': update_data})
            flash(f'Table {number} updated successfully!', 'success')
            return redirect(url_for('tables.list_tables'))
        except DuplicateKeyError as e:
             flash(f'Error: {e}', 'danger')
        except Exception as e:
             flash(f'Error updating table: {e}', 'danger')
             print(f"Error in edit_table: {e}") # Log error

        # Return form with data if error
        form_data = {**table, **request.form}
        return render_template('tables/form.html', title="Edit Table", table=form_data, table_id=table_id, statuses=TABLE_STATUSES)

    # GET request
    return render_template('tables/form.html', title="Edit Table", table=table, table_id=table_id, statuses=TABLE_STATUSES)


@bp.route('/delete/<table_id>', methods=['POST'])
def delete_table(table_id):
    db = get_db()
    try:
        obj_id = ObjectId(table_id)
        # Check if table has active orders or is occupied?
        table = db.tables.find_one({'_id': obj_id})
        if table:
            if table.get('status') == 'occupied':
                 flash(f'Cannot delete Table {table.get("number", "")}: It is currently occupied.', 'warning')
                 return redirect(url_for('tables.list_tables'))

            # Check for non-billed/non-cancelled orders associated with this table
            active_orders = db.orders.count_documents({
                'table_id': obj_id,
                'status': {'$nin': ['billed', 'cancelled']}
            })
            if active_orders > 0:
                 flash(f'Cannot delete Table {table.get("number", "")}: It has {active_orders} active order(s). Bill or cancel them first.', 'warning')
                 return redirect(url_for('tables.list_tables'))

        # Proceed with deletion if checks pass
        result = db.tables.delete_one({'_id': obj_id})
        if result.deleted_count > 0:
            flash('Table deleted successfully!', 'success')
        else:
            flash('Table not found or already deleted.', 'warning')
    except InvalidId:
        flash('Invalid Table ID.', 'danger')
    except Exception as e:
        flash(f'Error deleting table: {e}', 'danger')
        print(f"Error in delete_table: {e}") # Log error

    return redirect(url_for('tables.list_tables'))

# Route to quickly change table status (e.g., from list view buttons)
@bp.route('/set_status/<table_id>/<new_status>', methods=['POST'])
def set_table_status(table_id, new_status):
    db = get_db()
    if new_status not in TABLE_STATUSES:
         flash('Invalid status.', 'danger')
         return redirect(url_for('tables.list_tables'))
    try:
        obj_id = ObjectId(table_id)
        # Optional: Add checks - e.g., cannot set to 'available' if there are active orders
        if new_status == 'available':
             active_orders = db.orders.count_documents({
                'table_id': obj_id,
                'status': {'$nin': ['billed', 'cancelled']}
            })
             if active_orders > 0:
                  flash(f'Cannot set table to "available": It has {active_orders} active order(s).', 'warning')
                  return redirect(url_for('tables.list_tables'))

        result = db.tables.update_one(
            {'_id': obj_id},
            {'$set': {'status': new_status}}
        )
        if result.matched_count:
            table = db.tables.find_one({'_id': obj_id}, {'number': 1}) # Get number for flash message
            flash(f'Table {table.get("number", "")} status updated to "{new_status}".', 'success')
        else:
            flash('Table not found.', 'warning')
    except InvalidId:
        flash('Invalid Table ID.', 'danger')
    except Exception as e:
         flash(f'Error updating table status: {e}', 'danger')
         print(f"Error in set_table_status: {e}") # Log error

    return redirect(url_for('tables.list_tables'))