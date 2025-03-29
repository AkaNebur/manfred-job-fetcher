# --- START OF FILE app.py ---
import os
import logging
import sys
from typing import Callable

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Import configurations and initializers
from config import CONFIG
from database import init_db, check_db_connection, Session
from routes import router
# Delay scheduler import to avoid circular imports

# --- Logging Setup ---
log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s',
    stream=sys.stdout
)
# Reduce verbosity of certain loggers
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# lifespan function
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup operations
    logger.info("Starting application with FastAPI")
    
    # Initialize database - don't exit on failure, let app start in degraded mode
    try:
        init_db()
        db_ok, db_msg = check_db_connection()
        if not db_ok:
            logger.error(f"Initial database connection check failed: {db_msg}")
        else:
            logger.info("Database initialization and connection check successful.")
    except Exception as e:
        logger.critical(f"CRITICAL: Failed to initialize database: {e}", exc_info=True)
        # Don't exit, let app start in degraded mode
        # sys.exit("Database initialization failed. Exiting.")
    
    # Initialize scheduler (adapted for FastAPI)
    try:
        # Import scheduler at the top level to avoid circular imports
        from scheduler import initialize_scheduler as init_sched
        scheduler = init_sched(app)
        logger.info("Scheduler initialized. Automatic fetch will run every hour.")
    except Exception as e:
        logger.error(f"Failed to initialize scheduler: {e}", exc_info=True)
    
    yield  # This is where FastAPI serves the application
    
    # Shutdown operations
    logger.info("Shutting down application")
    
    # Shutdown scheduler if running - handle possible import error
    try:
        from scheduler import scheduler as sched
        if sched and getattr(sched, 'running', False):
            logger.info("Shutting down scheduler")
            sched.shutdown()
    except (ImportError, AttributeError) as e:
        logger.warning(f"Could not properly shut down scheduler: {e}")
    
    # Close HTTP clients
    try:
        # Import the functions to close HTTP clients
        from manfred_api import close_http_client
        from discord_notifier import close_discord_client
        
        # Close the clients
        logger.info("Closing HTTP clients")
        close_http_client()
        close_discord_client()
    except (ImportError, Exception) as e:
        logger.warning(f"Could not properly close HTTP clients: {e}")

# Create FastAPI application
app = FastAPI(
    title="Manfred Job Fetcher API",
    description="API for fetching, storing, and processing job offers from GetManfred, with Discord notifications.",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins in development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SQLAlchemy session management middleware
@app.middleware("http")
async def db_session_middleware(request: Request, call_next: Callable):
    try:
        response = await call_next(request)
    finally:
        Session.remove()
    return response

# Include routes
app.include_router(router)

# Display logging info at startup when run directly
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    
    # Log key configuration details on startup
    logger.info("-----------------------------------------")
    logger.info("Manfred Job Fetcher Starting Up (FastAPI Version)")
    logger.info(f"Log Level: {log_level_str}")
    logger.info(f"DB Path: {CONFIG['DB_PATH']}")
    logger.info(f"External API: {CONFIG['EXTERNAL_ENDPOINT_URL']}")
    logger.info(f"Webhook Configured: {bool(CONFIG['DISCORD_WEBHOOK_URL'])}")
    logger.info(f"Detail Build Hash: {CONFIG['BUILD_ID_HASH']}")
    logger.info(f"Fetch Interval: {CONFIG['FETCH_INTERVAL']} seconds ({CONFIG['FETCH_INTERVAL']/60:.1f} minutes)")
    logger.info("-----------------------------------------")
    
    # Run with uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv('FLASK_DEBUG', '0') == '1'
    )

# --- END OF FILE app.py ---