# --- START OF FILE app.py ---
import os
import sqlite3
import json
import logging
from datetime import datetime
from contextlib import contextmanager
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import Flask, jsonify, request
from swagger import setup_swagger # Assuming swagger.py exists and is correct

# --- Configuration ---
CONFIG = {
    'EXTERNAL_ENDPOINT_URL': os.getenv('EXTERNAL_ENDPOINT_URL', 'https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true'),
    'DB_PATH': os.getenv('DB_PATH', '/app/data/history.db'),
    'MAX_RETRIES': int(os.getenv('MAX_RETRIES', '3')),
    'RETRY_BACKOFF': float(os.getenv('RETRY_BACKOFF', '0.5')),
}

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Flask App and Swagger Setup ---
app = Flask(__name__)
swagger = setup_swagger(app) # Setup Swagger using the simplified config

# --- Requests Session with Retries ---
retry_strategy = Retry(
    total=CONFIG['MAX_RETRIES'],
    backoff_factor=CONFIG['RETRY_BACKOFF'],
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"] # Keep POST in case used elsewhere, low overhead
)
adapter = HTTPAdapter(max_retries=retry_strategy)
http_session = requests.Session()
http_session.mount("http://", adapter)
http_session.mount("https://", adapter)

# --- Database Handling ---
@contextmanager
def get_db_conn():
    """Provides a database connection context."""
    conn = None
    db_path = CONFIG['DB_PATH']
    # Ensure directory exists before connecting
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
         try:
             os.makedirs(db_dir, exist_ok=True)
             logger.info(f"Created database directory: {db_dir}")
         except OSError as e:
             logger.error(f"Error creating database directory {db_dir}: {e}")
             # Decide if this is fatal - for health check, maybe not, but logging might fail.
             # For simplicity, we'll proceed but log the error.

    try:
        # Use a timeout for connection attempts
        conn = sqlite3.connect(db_path, timeout=10)
        # No need for row_factory if just checking connection or simple logging
        # conn.row_factory = sqlite3.Row
        yield conn
    except Exception as e:
        logger.error(f"Database connection error to {db_path}: {e}")
        raise # Re-raise the exception after logging
    finally:
        if conn:
            conn.close()

def init_db():
    """Initialize the SQLite database with tables."""
    logger.info(f"Initializing database at {CONFIG['DB_PATH']}...")
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            # Create table for fetch history
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS fetch_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP NOT NULL,
                endpoint TEXT NOT NULL,
                status_code INTEGER,
                response_size INTEGER,
                error TEXT
            )
            ''')
            
            # Drop job_offers table if it exists but has wrong schema
            try:
                # Try to query the table to check its structure
                cursor.execute("SELECT offer_id, position, company_name FROM job_offers LIMIT 1")
            except sqlite3.OperationalError:
                # Table doesn't exist or has wrong schema, drop it if it exists
                logger.info("Job offers table has wrong schema or doesn't exist - recreating it")
                cursor.execute("DROP TABLE IF EXISTS job_offers")
            
            # Create table for job offers
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS job_offers (
                id INTEGER PRIMARY KEY,
                offer_id INTEGER NOT NULL,
                position TEXT NOT NULL,
                company_name TEXT NOT NULL,
                remote_percentage INTEGER,
                salary_from INTEGER,
                salary_to INTEGER,
                locations TEXT,
                timestamp TIMESTAMP NOT NULL,
                UNIQUE(offer_id)
            )
            ''')
            
            conn.commit()
            logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        # Depending on severity, you might want to exit the application here
        # raise SystemExit(f"Could not initialize database: {e}")


def log_fetch(endpoint, status_code=None, response_size=None, error=None):
    """Log API fetch attempts to the database."""
    try:
        with get_db_conn() as conn:
            conn.execute(
                "INSERT INTO fetch_history (timestamp, endpoint, status_code, response_size, error) VALUES (?, ?, ?, ?, ?)",
                (datetime.now(), endpoint, status_code, response_size, str(error) if error else None)
            )
            conn.commit()
    except Exception as e:
        # Log DB error, but don't let it stop the main flow
        logger.error(f"Failed to log fetch attempt for {endpoint}: {e}")


# --- Core Logic Functions ---
def _make_api_request(url, method='GET', json_payload=None, timeout=15):
    """Makes an HTTP request with retries and logs the attempt."""
    try:
        if method.upper() == 'POST':
             # Although no POST endpoint remains, keep for potential future use/robustness
             response = http_session.post(url, json=json_payload, headers={"Content-Type": "application/json"}, timeout=timeout)
        else: # Default to GET
            response = http_session.get(url, timeout=timeout)

        # Log before raising exception for status code
        log_fetch(url, response.status_code, len(response.content))
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        return response
    except requests.exceptions.RequestException as e:
        status_code = e.response.status_code if hasattr(e, 'response') and e.response is not None else None
        # Log the error condition
        log_fetch(url, status_code=status_code, error=str(e))
        logger.error(f"Request failed for {url}: {e}")
        return None
    except Exception as e:
        # Catch any other unexpected errors during the request process
        log_fetch(url, error=f"Unexpected error during request: {e}")
        logger.exception(f"Unexpected error during request to {url}") # Log full traceback
        return None


# --- Flask Routes ---

@app.route('/raw-offers', methods=['GET'])
def get_raw_offers():
    """
    Fetches and returns the raw JSON data from the external Manfred API.
    ---
    tags:
      - Raw Data
    summary: Get raw job offers list from Manfred API
    description: Directly fetches and returns the JSON response from the configured EXTERNAL_ENDPOINT_URL without processing or saving. Uses configured retries.
    responses:
      200:
        description: Raw list of active job offers from the external API.
        content:
          application/json:
            schema:
              type: object # Or array, depending on the actual API response
              description: Structure depends entirely on the external Manfred API response.
      500:
        description: Error fetching data from the external API after retries.
        content:
          application/json:
            schema:
              type: object
              properties:
                status:
                  type: string
                  example: error
                message:
                  type: string
                  example: Failed to fetch data from external API
      502:
        description: Bad Gateway or invalid response from external API.
        content:
          application/json:
            schema:
              type: object
              properties:
                status:
                  type: string
                  example: error
                message:
                  type: string
                  example: Received non-JSON or invalid response from external API
    """
    external_url = CONFIG['EXTERNAL_ENDPOINT_URL']
    logger.info(f"Request received for raw offers from {external_url}")
    response = _make_api_request(external_url)

    if response:
        try:
            # Attempt to parse JSON - critical step
            data = response.json()
            # Return the parsed JSON data with the original status code potentially
            # Flask's jsonify will set content-type to application/json
            return jsonify(data)
        except json.JSONDecodeError as e:
             # Log the failure to parse
             logger.error(f"Raw offers endpoint: Content from {external_url} is not valid JSON: {e}")
             # Return a specific error for non-JSON response
             return jsonify({"status": "error", "message": "Received non-JSON response from external API"}), 502 # 502 Bad Gateway seems appropriate
        except Exception as e:
             # Catch other potential errors during response processing
             logger.exception(f"Unexpected error processing response from {external_url}")
             return jsonify({"status": "error", "message": "Failed to process response from external API"}), 500
    else:
        # _make_api_request failed (already logged)
        return jsonify({"status": "error", "message": "Failed to fetch data from external API"}), 500

@app.route('/store-offers', methods=['GET'])
def store_offers():
    """
    Fetches job offers from the Manfred API and stores them in the database.
    ---
    tags:
      - Data Storage
    summary: Fetch and store job offers in the database
    description: Fetches job offers from the external API and stores them in the local database. Returns a summary of the operation.
    responses:
      200:
        description: Successfully fetched and stored job offers.
        content:
          application/json:
            schema:
              type: object
              properties:
                status:
                  type: string
                  example: success
                stored_count:
                  type: integer
                  example: 25
                new_offers:
                  type: integer
                  example: 10
                updated_offers:
                  type: integer
                  example: 15
                timestamp:
                  type: string
                  format: date-time
      500:
        description: Error fetching or storing data.
        content:
          application/json:
            schema:
              type: object
              properties:
                status:
                  type: string
                  example: error
                message:
                  type: string
                  example: Failed to fetch or store job offers
    """
    external_url = CONFIG['EXTERNAL_ENDPOINT_URL']
    logger.info(f"Request received to fetch and store offers from {external_url}")
    
    # Fetch data from external API
    response = _make_api_request(external_url)
    
    if not response:
        return jsonify({
            "status": "error", 
            "message": "Failed to fetch data from external API"
        }), 500
    
    try:
        # Parse the JSON response
        offers = response.json()
        
        # Check if we have a valid list of offers
        if not isinstance(offers, list):
            return jsonify({
                "status": "error", 
                "message": "Invalid response format from external API - expected a list of offers"
            }), 500
        
        # Store the offers in the database
        new_count = 0
        updated_count = 0
        timestamp = datetime.now()
        
        with get_db_conn() as conn:
            cursor = conn.cursor()
            
            for offer in offers:
                # Extract key fields from offer
                offer_id = offer.get('id')
                position = offer.get('position', 'Unknown')
                company_name = offer.get('company', {}).get('name', 'Unknown')
                remote_percentage = offer.get('remotePercentage', 0)
                salary_from = offer.get('salaryFrom', 0)
                salary_to = offer.get('salaryTo', 0)
                
                # Handle locations (convert list to comma-separated string)
                locations = offer.get('locations', [])
                locations_str = ', '.join(locations) if locations else ''
                
                try:
                    # Try to insert the offer (will fail if offer_id already exists)
                    cursor.execute(
                        """
                        INSERT INTO job_offers 
                        (offer_id, position, company_name, remote_percentage, salary_from, salary_to, 
                         locations, timestamp) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (offer_id, position, company_name, remote_percentage, salary_from, 
                         salary_to, locations_str, timestamp)
                    )
                    new_count += 1
                except sqlite3.IntegrityError:
                    # Offer already exists, update it
                    cursor.execute(
                        """
                        UPDATE job_offers 
                        SET position = ?, company_name = ?, remote_percentage = ?, 
                            salary_from = ?, salary_to = ?, locations = ?, 
                            timestamp = ?
                        WHERE offer_id = ?
                        """,
                        (position, company_name, remote_percentage, salary_from, 
                         salary_to, locations_str, timestamp, offer_id)
                    )
                    updated_count += 1
            
            # Commit all changes
            conn.commit()
        
        # Return a summary of the operation
        return jsonify({
            "status": "success",
            "stored_count": len(offers),
            "new_offers": new_count,
            "updated_offers": updated_count,
            "timestamp": timestamp.isoformat()
        })
    
    except json.JSONDecodeError as e:
        logger.error(f"Store offers endpoint: Content from {external_url} is not valid JSON: {e}")
        return jsonify({
            "status": "error", 
            "message": "Received non-JSON response from external API"
        }), 502
        
    except Exception as e:
        logger.exception(f"Error storing offers: {e}")
        return jsonify({
            "status": "error", 
            "message": f"Failed to store offers: {str(e)}"
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """
    Simple health check endpoint.
    ---
    tags:
      - System
    summary: System health check
    description: Checks database connectivity for logging and returns basic configuration status.
    responses:
      200:
        description: System is healthy.
        content:
          application/json:
            schema:
              type: object
              properties:
                status:
                  type: string
                  example: healthy
                timestamp:
                  type: string
                  format: date-time
                database_path:
                  type: string
                  example: /app/data/history.db
                database_status:
                  type: string
                  example: connected
                config:
                  type: object
                  properties:
                    external_endpoint_url:
                      type: string
                    max_retries:
                      type: integer
                    retry_backoff_factor:
                      type: number
      503:
        description: Service Unavailable (e.g., database connection failed).
        content:
          application/json:
            schema:
              type: object
              properties:
                status:
                  type: string
                  example: unhealthy
                timestamp:
                  type: string
                  format: date-time
                database_path:
                  type: string
                database_status:
                  type: string
                  example: "error: unable to open database file"

    """
    db_status = "connected"
    is_healthy = True
    try:
        # Test connection using the context manager
        with get_db_conn() as conn:
            # Simple query to ensure the connection is truly working
            conn.execute("SELECT 1")
    except Exception as e:
        db_status = f"error: {str(e)}"
        is_healthy = False
        logger.error(f"Health check failed due to DB connection issue: {e}") # Log error specifically for health check failure

    status_code = 200 if is_healthy else 503
    response_body = {
        "status": "healthy" if is_healthy else "unhealthy",
        "timestamp": datetime.now().isoformat(),
        "database_path": CONFIG['DB_PATH'],
        "database_status": db_status,
        "config": { # Show only relevant config
            "external_endpoint_url": CONFIG['EXTERNAL_ENDPOINT_URL'],
            "max_retries": CONFIG['MAX_RETRIES'],
            "retry_backoff_factor": CONFIG['RETRY_BACKOFF']
        }
    }
    return jsonify(response_body), status_code

# --- Application Entry Point ---
if __name__ == '__main__':
    # Ensure the database directory exists (handled within get_db_conn now)
    # Initialize the database schema (fetch_history table)
    init_db()

    # Log startup information
    logger.info("-----------------------------------------")
    logger.info("Starting Manfred Job Fetcher (Simplified)")
    logger.info(f"Database Path: {CONFIG['DB_PATH']}")
    logger.info(f"External API Endpoint: {CONFIG['EXTERNAL_ENDPOINT_URL']}")
    logger.info("Endpoints available: /raw-offers, /store-offers, /health, /api/docs")
    logger.info("-----------------------------------------")

    # Run Flask App
    # Use waitress or gunicorn in production instead of app.run()
    app.run(host='0.0.0.0', port=5000, debug=False)

# --- END OF FILE app.py ---