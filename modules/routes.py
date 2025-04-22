# modules/main/routes.py
from flask import render_template
from database import get_db # Might need DB later for dashboard stats
from . import bp # Use relative import

@bp.route('/')
def index():
    db = get_db()
    # Example: Fetch some basic stats for the dashboard
    try:
        active_orders_count = db.orders.count_documents({'status': {'$nin': ['billed', 'cancelled']}})
        occupied_tables_count = db.tables.count_documents({'status': 'occupied'})
        low_stock_items_count = db.inventory_items.count_documents({
            # Requires comparing numeric values directly if possible, or fetching all and comparing in Python
            # This might be slow if there are many items. A pipeline is better.
            # '$expr': { '$lte': [ '$current_stock', '$low_stock_threshold' ] } # Needs numeric types
        })
        # Simplified low stock check (less efficient):
        low_stock_items = db.inventory_items.find({}, {'current_stock': 1, 'low_stock_threshold': 1})
        low_stock_count = sum(1 for item in low_stock_items if float(item.get('current_stock', 0)) <= float(item.get('low_stock_threshold', 0)))

    except Exception as e:
        print(f"Dashboard stat error: {e}")
        active_orders_count = 'N/A'
        occupied_tables_count = 'N/A'
        low_stock_count = 'N/A'


    dashboard_stats = {
        'active_orders': active_orders_count,
        'occupied_tables': occupied_tables_count,
        'low_stock_items': low_stock_count,
    }

    return render_template('index.html', title='Dashboard', stats=dashboard_stats)