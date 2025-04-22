# app.py
import os
from flask import Flask, render_template, g
from config import Config
from database import init_db, teardown_db, get_db
from pymongo.errors import ConnectionFailure, OperationFailure

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Ensure INSTANCE_FOLDER exists if needed for sessions etc.
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass # Handle error if needed

    # Initialize Database within app context
    # This ensures config is loaded before init_db is called
    try:
        with app.app_context():
            init_db(app)
    except (ConnectionFailure, OperationFailure, ValueError) as e:
        # Handle critical DB connection error on startup
        print(f"FATAL STARTUP ERROR: Could not initialize database connection: {e}")
        # Depending on policy, might exit or run in a degraded state.
        # For now, we make it hard to start without DB.
        # You could replace raise with sys.exit(1) or allow it to run degraded.
        raise RuntimeError(f"Application cannot start without database: {e}") from e

    # Register teardown function to close DB connection when app context ends
    app.teardown_appcontext(teardown_db)

    # --- Register Blueprints ---
    from modules.main.routes import bp as main_bp
    app.register_blueprint(main_bp)

    from modules.menu.routes import bp as menu_bp
    app.register_blueprint(menu_bp, url_prefix='/menu')

    from modules.tables.routes import bp as tables_bp
    app.register_blueprint(tables_bp, url_prefix='/tables')

    from modules.orders.routes import bp as orders_bp
    app.register_blueprint(orders_bp, url_prefix='/orders')

    from modules.billing.routes import bp as billing_bp
    app.register_blueprint(billing_bp, url_prefix='/billing')

    from modules.inventory.routes import bp as inventory_bp
    app.register_blueprint(inventory_bp, url_prefix='/inventory')

    from modules.kds.routes import bp as kds_bp
    app.register_blueprint(kds_bp) # url_prefix defined in blueprint __init__

    from modules.crm.routes import bp as crm_bp
    app.register_blueprint(crm_bp) # url_prefix defined in blueprint __init__

    from modules.employees.routes import bp as employees_bp
    app.register_blueprint(employees_bp) # url_prefix defined in blueprint __init__

    from modules.reports.routes import bp as reports_bp
    app.register_blueprint(reports_bp) # url_prefix defined in blueprint __init__

    # --- Error Handlers ---
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        # Log the error properly here in a real app
        print(f"SERVER ERROR 500: {error}")
        # You might want to close the DB connection explicitly on severe errors
        # teardown_db(error) # Or rely on teardown_appcontext
        return render_template('errors/500.html'), 500

    @app.errorhandler(Exception) # Catch other potential errors
    def unhandled_exception(e):
         # Log the exception e
         print(f"UNHANDLED EXCEPTION: {e}")
         # For specific DB errors during request handling, ensure connection is ok or closed
         if isinstance(e, (ConnectionFailure, OperationFailure)):
              teardown_db(e)
         # Render a generic error page
         return render_template('errors/500.html', error_message=str(e)), 500


    print("Flask application created successfully.")
    return app

# --- Run the App ---
# This part is for running the app directly using 'python app.py'
# For production, use a WSGI server like Gunicorn or uWSGI:
# gunicorn --bind 0.0.0.0:5000 app:create_app()
if __name__ == '__main__':
    flask_app = create_app()
    # Get host and port from environment or use defaults
    host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV', 'development') == 'development'

    print(f" * Starting Flask server on http://{host}:{port}/")
    print(f" * Debug mode: {'on' if debug_mode else 'off'}")
    # Use host='0.0.0.0' to make it accessible on your network
    flask_app.run(host=host, port=port, debug=debug_mode)