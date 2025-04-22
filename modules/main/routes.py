# modules/menu/routes.py
from flask import render_template, request, redirect, url_for, flash
from bson.objectid import ObjectId
from bson.errors import InvalidId
from database import get_db
from . import bp
from pymongo.errors import DuplicateKeyError # Import error for handling unique constraint

@bp.route('/')
def list_items():
    db = get_db()
    try:
        items = list(db.menu_items.find().sort([("category", 1), ("name", 1)])) # Sort by category, then name
    except Exception as e:
        flash(f"Error fetching menu items: {e}", "danger")
        items = []
    return render_template('menu/list.html', items=items, title="Menu Items")

@bp.route('/add', methods=['GET', 'POST'])
def add_item():
    if request.method == 'POST':
        db = get_db()
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price_str = request.form.get('price')
        category = request.form.get('category', 'Uncategorized').strip()
        is_available = 'is_available' in request.form # Checkbox value

        if not name or not price_str:
            flash('Name and Price are required.', 'warning')
            return render_template('menu/form.html', title="Add Menu Item", item=request.form) # Pass back form data

        try:
            price = float(price_str)
            if price < 0:
                 raise ValueError("Price cannot be negative")
        except ValueError:
            flash('Invalid price format. Please enter a non-negative number.', 'warning')
            return render_template('menu/form.html', title="Add Menu Item", item=request.form)

        new_item = {
            'name': name,
            'description': description,
            'price': price,
            'category': category,
            'is_available': is_available,
            # Add other fields like image_url, ingredients etc. later
        }
        try:
            result = db.menu_items.insert_one(new_item)
            flash(f'Menu item "{name}" added successfully!', 'success')
            return redirect(url_for('menu.list_items'))
        except DuplicateKeyError:
             flash(f'Error: Menu item with name "{name}" already exists.', 'danger')
        except Exception as e:
             flash(f'Error adding menu item: {e}', 'danger')
             print(f"Error in add_item: {e}") # Log error

        # Return form with data if error occurred
        return render_template('menu/form.html', title="Add Menu Item", item=request.form)

    # GET request
    return render_template('menu/form.html', title="Add Menu Item", item=None) # Pass None for a new item

@bp.route('/edit/<item_id>', methods=['GET', 'POST'])
def edit_item(item_id):
    db = get_db()
    try:
        obj_id = ObjectId(item_id)
    except InvalidId:
        flash('Invalid Item ID.', 'danger')
        return redirect(url_for('menu.list_items'))

    # Fetch item or return 404 (or redirect)
    item = db.menu_items.find_one({'_id': obj_id})
    if not item:
        flash('Menu item not found.', 'warning')
        return redirect(url_for('menu.list_items'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price_str = request.form.get('price')
        category = request.form.get('category', 'Uncategorized').strip()
        is_available = 'is_available' in request.form

        if not name or not price_str:
            flash('Name and Price are required.', 'warning')
            # Pass existing item data back to form for editing (merge with request.form to keep edits)
            form_data = {**item, **request.form}
            return render_template('menu/form.html', title="Edit Menu Item", item=form_data, item_id=item_id)

        try:
            price = float(price_str)
            if price < 0:
                 raise ValueError("Price cannot be negative")
        except ValueError:
            flash('Invalid price format. Please enter a non-negative number.', 'warning')
            form_data = {**item, **request.form}
            return render_template('menu/form.html', title="Edit Menu Item", item=form_data, item_id=item_id)

        update_data = {
            'name': name,
            'description': description,
            'price': price,
            'category': category,
            'is_available': is_available,
        }
        try:
            result = db.menu_items.update_one({'_id': obj_id}, {'$set': update_data})
            flash(f'Menu item "{name}" updated successfully!', 'success')
            return redirect(url_for('menu.list_items'))
        except DuplicateKeyError:
             flash(f'Error: Another menu item with name "{name}" already exists.', 'danger')
        except Exception as e:
             flash(f'Error updating menu item: {e}', 'danger')
             print(f"Error in edit_item: {e}") # Log error

        # Return form with data if error occurred
        form_data = {**item, **request.form} # Keep user's changes on error
        return render_template('menu/form.html', title="Edit Menu Item", item=form_data, item_id=item_id)


    # GET request: populate form with existing item data
    # Convert boolean for checkbox checked state - This is better handled directly in template
    # item['is_available_checked'] = 'checked' if item.get('is_available', False) else ''
    return render_template('menu/form.html', title="Edit Menu Item", item=item, item_id=item_id)

@bp.route('/delete/<item_id>', methods=['POST']) # Use POST for delete actions
def delete_item(item_id):
    # Consider adding role-based access control here later
    db = get_db()
    try:
        obj_id = ObjectId(item_id)
        # TODO: Check if item is part of any active (non-billed/cancelled) order?
        # active_orders = db.orders.count_documents({'items.menu_item_id': obj_id, 'status': {'$nin': ['billed', 'cancelled']}})
        # if active_orders > 0:
        #     flash('Cannot delete item: It is part of active orders.', 'warning')
        #     return redirect(url_for('menu.list_items'))

        result = db.menu_items.delete_one({'_id': obj_id})
        if result.deleted_count > 0:
            flash('Menu item deleted successfully!', 'success')
        else:
            flash('Menu item not found or already deleted.', 'warning')
    except InvalidId:
        flash('Invalid Item ID.', 'danger')
    except Exception as e:
        flash(f'Error deleting menu item: {e}', 'danger')
        print(f"Error in delete_item: {e}") # Log error

    return redirect(url_for('menu.list_items'))