# app.py
from flask import Flask, render_template, g
from config import Config
from modules.utils.database import init_db, get_db
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize Database
    with app.app_context():
        try:
            init_db(app)
            logger.info("Database initialization sequence completed.")
        except Exception as e:
            logger.error(f"Failed to initialize database during app creation: {e}")
            # Decide if the app should stop or continue without DB
            # For this app, DB is critical, but we already exit in init_db on critical errors.
            # If init_db returns None (e.g., auth failure), get_db() will raise errors later.

    # Register Blueprints (Modules)
    # Import blueprints AFTER app creation and DB init to avoid circular dependencies
    # and ensure DB is available if blueprints access it upon import (less common)
    try:
        from modules.auth.routes import auth_bp
        from modules.menu.routes import menu_bp
        from modules.tables.routes import tables_bp
        from modules.orders.routes import orders_bp
        from modules.billing.routes import billing_bp
        from modules.kds.routes import kds_bp
        from modules.employees.routes import employees_bp
        # Import other blueprints (inventory, crm, reports) here
        # from modules.inventory.routes import inventory_bp
        # from modules.crm.routes import crm_bp
        # from modules.reports.routes import reports_bp

        app.register_blueprint(auth_bp, url_prefix='/auth')
        app.register_blueprint(menu_bp, url_prefix='/menu')
        app.register_blueprint(tables_bp, url_prefix='/tables')
        app.register_blueprint(orders_bp, url_prefix='/orders')
        app.register_blueprint(billing_bp, url_prefix='/billing')
        app.register_blueprint(kds_bp, url_prefix='/kds')
        app.register_blueprint(employees_bp, url_prefix='/employees')
        # app.register_blueprint(inventory_bp, url_prefix='/inventory')
        # app.register_blueprint(crm_bp, url_prefix='/crm')
        # app.register_blueprint(reports_bp, url_prefix='/reports')
        logger.info("Blueprints registered successfully.")

    except ImportError as e:
        logger.error(f"Failed to import or register blueprints: {e}")
    except Exception as e:
         logger.error(f"An unexpected error occurred during blueprint registration: {e}")


    # --- Basic Routes ---
    @app.route('/')
    def index():
        # Could show a dashboard here later
        return render_template('index.html', title='Home')

    # --- Error Handlers ---
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        # You might want to log the error details here
        # db.session.rollback() # If using SQLAlchemy
        logger.error(f"Internal server error: {error}", exc_info=True)
        return render_template('500.html'), 500

    # --- Request Context ---
    # Optional: Make DB accessible via Flask's 'g' object
    # @app.before_request
    # def before_request():
    #     g.db = get_db()

    # @app.teardown_appcontext
    # def teardown_db(exception=None):
    #     db = g.pop('db', None)
    #     # Close DB connection if needed (MongoClient handles pooling)
    #     # if db is not None:
    #     #     db.client.close()

    return app

# --- Main Execution ---
if __name__ == '__main__':
    app = create_app()
    # Use host='0.0.0.0' to make it accessible on your network
    app.run(host='0.0.0.0', port=5000, debug=True) # Turn off debug in production!