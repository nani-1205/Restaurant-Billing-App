# modules/menu/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from modules.utils.database import get_db
from bson.objectid import ObjectId
from bson.errors import InvalidId

menu_bp = Blueprint('menu', __name__, template_folder='../../templates/menu')

@menu_bp.route('/')
def list_menu_items():
    """Displays the list of menu items."""
    try:
        db = get_db()
        items = list(db.menu_items.find().sort('category').sort('name'))
        return render_template('menu_list.html', items=items, title="Menu Items")
    except Exception as e:
        current_app.logger.error(f"Error fetching menu items: {e}")
        flash('Error loading menu items.', 'danger')
        return render_template('menu_list.html', items=[], title="Menu Items")


@menu_bp.route('/add', methods=['GET', 'POST'])
def add_menu_item():
    """Handles adding a new menu item."""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        price_str = request.form.get('price')
        category = request.form.get('category')
        is_available = 'is_available' in request.form # Checkbox

        if not name or not price_str or not category:
            flash('Name, Price, and Category are required.', 'warning')
            return render_template('menu_form.html', title="Add Menu Item", item={})

        try:
            price = float(price_str)
            if price < 0:
                 raise ValueError("Price cannot be negative")
        except ValueError:
            flash('Invalid price entered.', 'warning')
            return render_template('menu_form.html', title="Add Menu Item", item=request.form)

        try:
            db = get_db()
            new_item = {
                'name': name,
                'description': description,
                'price': price,
                'category': category,
                'is_available': is_available
            }
            result = db.menu_items.insert_one(new_item)
            if result.inserted_id:
                flash(f'Menu item "{name}" added successfully!', 'success')
                # Ensure the collection exists now if it was the first insert
                current_app.logger.info(f"Inserted menu item, ID: {result.inserted_id}")
                return redirect(url_for('menu.list_menu_items'))
            else:
                 flash('Failed to add menu item.', 'danger')
        except Exception as e:
            current_app.logger.error(f"Error adding menu item: {e}")
            flash('An error occurred while adding the item.', 'danger')

        return render_template('menu_form.html', title="Add Menu Item", item=request.form)

    # GET request
    return render_template('menu_form.html', title="Add Menu Item", item={})


@menu_bp.route('/edit/<item_id>', methods=['GET', 'POST'])
def edit_menu_item(item_id):
    """Handles editing an existing menu item."""
    try:
        oid = ObjectId(item_id)
    except InvalidId:
        flash('Invalid item ID.', 'danger')
        return redirect(url_for('menu.list_menu_items'))

    db = get_db()
    item = db.menu_items.find_one({'_id': oid})

    if not item:
        flash('Menu item not found.', 'danger')
        return redirect(url_for('menu.list_menu_items'))

    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        price_str = request.form.get('price')
        category = request.form.get('category')
        is_available = 'is_available' in request.form

        if not name or not price_str or not category:
            flash('Name, Price, and Category are required.', 'warning')
            # Pass current form data back to template
            item.update(request.form)
            item['is_available'] = is_available # Update checkbox state
            return render_template('menu_form.html', title="Edit Menu Item", item=item, item_id=item_id)

        try:
            price = float(price_str)
            if price < 0:
                 raise ValueError("Price cannot be negative")
        except ValueError:
            flash('Invalid price entered.', 'warning')
            item.update(request.form)
            item['is_available'] = is_available
            return render_template('menu_form.html', title="Edit Menu Item", item=item, item_id=item_id)

        try:
            update_data = {
                '$set': {
                    'name': name,
                    'description': description,
                    'price': price,
                    'category': category,
                    'is_available': is_available
                }
            }
            result = db.menu_items.update_one({'_id': oid}, update_data)

            if result.modified_count > 0:
                flash(f'Menu item "{name}" updated successfully!', 'success')
            elif result.matched_count > 0:
                 flash(f'No changes detected for menu item "{name}".', 'info')
            else:
                 # This case should be rare if item was found initially
                 flash('Failed to update menu item (not found).', 'danger')

            return redirect(url_for('menu.list_menu_items'))

        except Exception as e:
            current_app.logger.error(f"Error updating menu item {item_id}: {e}")
            flash('An error occurred while updating the item.', 'danger')
            # Pass current form data back
            item.update(request.form)
            item['is_available'] = is_available
            return render_template('menu_form.html', title="Edit Menu Item", item=item, item_id=item_id)


    # GET request
    return render_template('menu_form.html', title="Edit Menu Item", item=item, item_id=item_id)


@menu_bp.route('/delete/<item_id>', methods=['POST'])
def delete_menu_item(item_id):
    """Handles deleting a menu item."""
    try:
        oid = ObjectId(item_id)
    except InvalidId:
        flash('Invalid item ID.', 'danger')
        return redirect(url_for('menu.list_menu_items'))

    try:
        db = get_db()
        result = db.menu_items.delete_one({'_id': oid})
        if result.deleted_count > 0:
            flash('Menu item deleted successfully!', 'success')
        else:
            flash('Menu item not found or already deleted.', 'warning')
    except Exception as e:
        current_app.logger.error(f"Error deleting menu item {item_id}: {e}")
        flash('An error occurred while deleting the item.', 'danger')

    return redirect(url_for('menu.list_menu_items'))