# Restaurant Billing Web App

A web-based Point of Sale (POS) application for restaurants built with Python (Flask) and MongoDB. It helps manage menus, tables, orders, kitchen displays, billing, and provides basic reporting.

**Repository:** [https://github.com/nani-1205/Restaurant-Billing-App.git](https://github.com/nani-1205/Restaurant-Billing-App.git)

## Features

*   **Dashboard:** Overview of key metrics (Tables, Active Orders, Pending Bills, Today's Sales), KDS preview, and Quick Actions.
*   **Menu Management:** Add, edit, delete, and search menu items. Toggle item availability.
*   **Table Management:** Add, delete tables. View table status (Available, Occupied, Reserved, Cleaning) and capacity. Start new orders directly from available tables.
*   **Order Management:** Create new orders (optionally with initial items), view open orders, add items, update item status (for KDS), close orders (ready for billing).
*   **Kitchen Display System (KDS):** Real-time (via page reload) display of pending and preparing items from open orders for the kitchen staff. Allows marking items as preparing or served.
*   **Billing & Invoicing:** List orders ready for billing. View bill details, apply discounts, finalize payment (Cash, Card, UPI, etc.), and mark orders as billed. Automatically updates table status upon payment.
*   **Reporting & Analytics:** View sales summaries and top-selling items based on different time periods (Today, Yesterday, This Month, Last Month, This Year, Custom Date Range).

## Technology Stack

*   **Backend:** Python 3, Flask Framework
*   **Database:** MongoDB
*   **ODM/Driver:** PyMongo
*   **Frontend:** HTML, CSS, Bootstrap 5, JavaScript (basic interactions, AJAX for KDS)
*   **Libraries:**
    *   `python-dotenv` (for environment variable management)
    *   `python-dateutil` (for relative date calculations in reports)
    *   `Werkzeug` (Flask dependency)
    *   `Font Awesome` (for icons)


## Setup and Installation

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/nani-1205/Restaurant-Billing-App.git
    cd Restaurant-Billing-App
    ```

2.  **Create and Activate Virtual Environment:**
    ```bash
    # Linux/macOS
    python3 -m venv venv
    source venv/bin/activate

    # Windows (Git Bash/Linux Subsystem)
    python -m venv venv
    source venv/Scripts/activate
    # Windows (Command Prompt)
    python -m venv venv
    .\venv\Scripts\activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

Configuration is primarily handled through environment variables loaded via a `.env` file.

1.  **Create `.env` file:** Create a file named `.env` in the project's root directory.
2.  **Populate `.env`:** Add the following variables, replacing the placeholder values with your actual configuration.

    ```dotenv
    # .env file for Restaurant Billing App Configuration
    # --- IMPORTANT: Add this file to your .gitignore ---

    # --- MongoDB Configuration ---
    # Replace with your actual MongoDB credentials and connection details
    MONGO_USERNAME="your_mongo_username" # e.g., admin
    MONGO_PASSWORD="your_mongo_password" # e.g., admin@1234 (special characters are handled)
    MONGO_IP="your_mongo_db_ip_or_hostname" # e.g., 0.0.0.0 or localhost
    MONGO_PORT="27017"   # Default MongoDB port
    MONGO_DB_NAME="restaurant_db" # Name for the application's database
    MONGO_AUTH_DB="admin" # Database to authenticate against (often 'admin' or the user's db)

    # --- Flask Configuration ---
    # IMPORTANT: Generate a strong, random secret key for production!
    # You can generate one in Python using: python -c 'import secrets; print(secrets.token_hex(24))'
    SECRET_KEY="your_strong_random_secret_key_here"

    # Set 'development' for debug mode, 'production' otherwise
    FLASK_ENV="development" # Use "production" for deployment

    # --- Application Specific ---
    TAX_RATE_PERCENT="5.0" # Example Tax Rate
    ```

3.  **`.gitignore`:** Ensure `.env` and the `venv/` directory are listed in your `.gitignore` file to prevent committing sensitive information.

    ```gitignore
    venv/
    __pycache__/
    *.pyc
    *.log
    .env
    ```

## Running the Application

1.  **Ensure MongoDB is running** and accessible with the credentials provided in `.env`.
2.  **Activate the virtual environment** (if not already active): `source venv/bin/activate` (or equivalent for your OS).
3.  **Run the Flask development server:**
    ```bash
    python app.py
    ```
4.  **Access the application:** Open your web browser and go to `http://127.0.0.1:5000/` or `http://<your-server-ip>:5000/` if running on a server.

**Note:** The application attempts to create the necessary MongoDB database (`restaurant_db`) and collections (`menu_items`, `tables`, `orders`, `bills`) on first connection if they don't exist. Ensure the MongoDB user has permissions to create databases and collections, or create them manually beforehand.

**For Production:** Do not use the Flask development server. Use a production-ready WSGI server like Gunicorn or Waitress.
*   **Waitress:** `pip install waitress` then `waitress-serve --host 0.0.0.0 --port 5000 app:app`
*   **Gunicorn (Linux/macOS):** `pip install gunicorn` then `gunicorn --bind 0.0.0.0:5000 -w 4 app:app` (adjust `-w 4` workers as needed)
    Remember to set `FLASK_ENV=production` in your environment variables for production.

## Usage Overview

*   **Dashboard:** Provides a quick glance at current restaurant status.
*   **Menu:** Manage food and drink items offered. Mark items as unavailable if out of stock.
*   **Tables:** Manage restaurant tables, view their status. Click "New Order" on an available table to start an order.
*   **Starting/Managing Orders:**
    *   Select initial items when starting an order (optional).
    *   Add more items from the "Order View" page.
    *   Update item status (Pending -> Preparing -> Served/Cancelled) from the "Order View" or "KDS".
    *   Close the order when the customer is finished.
*   **KDS:** Kitchen staff monitor this screen. Click buttons to update item status (triggers page reload).
*   **Billing:** View closed orders. Click on an order to view the bill, apply discounts, and finalize payment using the form.
*   **Reports:** Select predefined periods or a custom date range to view sales totals, transaction counts, and top-selling items.

---

Happy Dining Management! 🍽️