# --- START OF FILE app.py ---
import os
import logging
import sys
from flask import Flask

# Import configurations and initializers
from config import CONFIG # Base configuration
from database import init_db, check_db_connection # DB initializer and check
from swagger import setup_swagger # Swagger setup
from routes import api_bp # Import the Blueprint with API routes
from scheduler import initialize_scheduler # Import scheduler initializer

# --- Logging Setup ---
# Configure logging early
log_level_str = os.getenv('LOG_LEVEL', 'DEBUG').upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s',
    stream=sys.stdout # Log to stdout, suitable for containers
)
# Optionally reduce log level for noisy libraries
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING) # Less verbose server logs

logger = logging.getLogger(__name__) # Logger for this module

def create_app():
    """Creates and configures the Flask application."""
    app = Flask(__name__)

    # Load Flask specific configurations if any (can be from CONFIG or os.getenv)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'a-default-secret-key-for-dev') # Example Flask config
    # app.config['DEBUG'] = CONFIG.get('FLASK_DEBUG', False) # If debug needed

    logger.info("Flask app created. Initializing components...")

    # Initialize Database
    try:
        init_db()
        # Perform a quick connection check after init
        db_ok, db_msg = check_db_connection()
        if not db_ok:
            logger.error(f"Initial database connection check failed: {db_msg}")
            # Depending on requirements, might exit or continue with degraded functionality
        else:
            logger.info("Database initialization and connection check successful.")
    except Exception as e:
        logger.critical(f"CRITICAL: Failed to initialize database: {e}", exc_info=True)
        # Exit if DB initialization fails, as the app likely can't function
        sys.exit("Database initialization failed. Exiting.")

    # Register Blueprints (API routes)
    app.register_blueprint(api_bp, url_prefix='/') # Register API routes at root '/'
    logger.info("API routes registered.")

    # Setup Swagger Documentation
    try:
        setup_swagger(app)
        logger.info("Swagger UI setup complete. Available at /api/docs")
    except Exception as e:
        logger.error(f"Failed to setup Swagger: {e}", exc_info=True)
        # Continue running even if Swagger fails
        
    # Initialize the scheduler
    try:
        initialize_scheduler(app)
        logger.info("Scheduler initialized. Automatic fetch will run every hour.")
    except Exception as e:
        logger.error(f"Failed to initialize scheduler: {e}", exc_info=True)
        # Continue running even if scheduler initialization fails

    logger.info("Application components initialized.")
    return app

# --- Application Entry Point ---
if __name__ == '__main__':
    app = create_app()

    # Log key configuration details on startup
    logger.info("-----------------------------------------")
    logger.info("Manfred Job Fetcher Starting Up (Refactored)")
    logger.info(f"Log Level: {log_level_str}")
    logger.info(f"DB Path: {CONFIG['DB_PATH']}")
    logger.info(f"External API: {CONFIG['EXTERNAL_ENDPOINT_URL']}")
    logger.info(f"Webhook Configured: {bool(CONFIG['DISCORD_WEBHOOK_URL'])}")
    logger.info(f"Detail Build Hash: {CONFIG['BUILD_ID_HASH']}")
    logger.info(f"Fetch Interval: {CONFIG['FETCH_INTERVAL']} seconds ({CONFIG['FETCH_INTERVAL']/60:.1f} minutes)")
    logger.info("Registered Routes:")
    for rule in app.url_map.iter_rules():
        if rule.endpoint != 'static': # Exclude static rule
            logger.info(f"  - {rule.methods} {rule.rule} -> {rule.endpoint}")
    logger.info("-----------------------------------------")

    # Use Waitress or Gunicorn in production instead of app.run()
    # For development:
    port = int(os.getenv('PORT', 5000))
    debug_mode = os.getenv('FLASK_DEBUG', '0') == '1' # Enable Flask debug mode if FLASK_DEBUG=1
    logger.info(f"Running Flask development server on port {port} (Debug Mode: {debug_mode})")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

    # Example for production using Waitress (install waitress first: pip install waitress)
    # from waitress import serve
    # serve(app, host='0.0.0.0', port=port)

# --- END OF FILE app.py ---