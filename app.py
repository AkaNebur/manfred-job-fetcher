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
    'DISCORD_WEBHOOK_URL': os.getenv('DISCORD_WEBHOOK_URL', ''),
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

# --- Discord Webhook Integration ---
def send_discord_webhook(offer):
    """
    Send a job offer to Discord using webhook.
    
    Args:
        offer (dict): Job offer data to send to Discord
    
    Returns:
        bool: True if successful, False otherwise
    """
    webhook_url = CONFIG['DISCORD_WEBHOOK_URL']
    if not webhook_url:
        logger.warning("Discord webhook URL not configured. Skipping notification.")
        return False
    
    try:
        # Extract key job offer details for the message
        position = offer.get('position', 'Unknown Position')
        company_data = offer.get('company', {})
        company_name = company_data.get('name', 'Unknown Company')
        
        # Format salary range if available
        salary_from = offer.get('salaryFrom')
        salary_to = offer.get('salaryTo')
        salary_text = ""
        if salary_from and salary_to:
            salary_text = f"💰 {salary_from}€ - {salary_to}€"
        elif salary_from:
            salary_text = f"💰 From {salary_from}€"
        elif salary_to:
            salary_text = f"💰 Up to {salary_to}€"
        
        # Format remote percentage
        remote_percentage = offer.get('remotePercentage')
        remote_text = f"🏠 {remote_percentage}% Remote" if remote_percentage is not None else ""
        
        # Format locations
        locations = offer.get('locations', [])
        locations_text = f"📍 {', '.join(locations)}" if locations else ""
        
        # Get offer ID for job link
        offer_id = offer.get('id')
        offer_slug = offer.get('slug', 'job')
        job_url = f"https://www.getmanfred.com/es/job-offers/{offer_id}/{offer_slug}"
        
        # Get logo URL if available
        logo_url = None
        if company_data and 'logoDark' in company_data and 'url' in company_data['logoDark']:
            logo_url = company_data['logoDark']['url']
        
        # Create Discord embed
        embed = {
            "title": f"{position} at {company_name}",
            "description": f"{salary_text}\n{remote_text}\n{locations_text}\n\n[View on Manfred]({job_url})",
            "color": 5814783,  # Blue color
            "timestamp": datetime.now().isoformat(),
            "footer": {
                "text": "Via Manfred Job Fetcher"
            }
        }
        
        # Add thumbnail if logo is available
        if logo_url:
            embed["thumbnail"] = {"url": logo_url}
        
        # Create webhook payload
        webhook_data = {
            "content": "📢 New Job Offer",
            "embeds": [embed]
        }
        
        # Send to Discord
        response = http_session.post(
            webhook_url,
            json=webhook_data,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        
        logger.info(f"Sent job offer notification to Discord: {position} at {company_name}")
        return True
    
    except Exception as e:
        logger.error(f"Failed to send Discord webhook: {e}", exc_info=True)
        return False

def send_webhook_batch(offers, batch_size=5):
    """
    Send a batch of new offers to Discord webhook.
    
    Args:
        offers (list): List of job offer dictionaries
        batch_size (int): Maximum number of offers to send
    
    Returns:
        int: Number of offers sent successfully
    """
    if not offers:
        return 0
    
    sent_count = 0
    for offer in offers[:batch_size]:  # Limit to batch_size
        if send_discord_webhook(offer):
            sent_count += 1
    
    return sent_count

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
        # Enable foreign key constraints if needed (not currently used)
        # conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    except Exception as e:
        logger.error(f"Database connection error to {db_path}: {e}")
        raise # Re-raise the exception after logging
    finally:
        if conn:
            conn.close()

def _add_column_if_not_exists(cursor, table_name, column_name, column_type):
    """Helper function to add a column if it doesn't exist."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [info[1] for info in cursor.fetchall()]
    if column_name not in columns:
        logger.info(f"Adding column '{column_name}' to table '{table_name}'...")
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        logger.info(f"Column '{column_name}' added successfully.")
    else:
        logger.debug(f"Column '{column_name}' already exists in table '{table_name}'.")


def init_db():
    """Initialize the SQLite database with tables and ensures necessary columns exist."""
    logger.info(f"Initializing database at {CONFIG['DB_PATH']}...")
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            # Create table for fetch history (no changes needed here)
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

            # Create table for job offers - including the notification flag
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS job_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, -- Using standard auto-increment PK
                offer_id INTEGER NOT NULL UNIQUE,     -- The actual ID from the API, must be unique
                position TEXT NOT NULL,
                company_name TEXT NOT NULL,
                remote_percentage INTEGER,
                salary_from INTEGER,
                salary_to INTEGER,
                locations TEXT,
                company_logo_dark_url TEXT,           -- New column for dark logo URL
                timestamp TIMESTAMP NOT NULL,
                notification_sent BOOLEAN DEFAULT 0    -- Flag for tracking webhook notifications
            )
            ''')

            # --- Schema Migration: Ensure new columns exist ---
            # Add company_logo_dark_url if it's missing from an existing table
            _add_column_if_not_exists(cursor, 'job_offers', 'company_logo_dark_url', 'TEXT')
            
            # Add notification_sent flag if it's missing
            _add_column_if_not_exists(cursor, 'job_offers', 'notification_sent', 'BOOLEAN DEFAULT 0')

            # Example for future: How to add another column later
            # _add_column_if_not_exists(cursor, 'job_offers', 'another_new_field', 'INTEGER')

            conn.commit()
            logger.info("Database initialized/verified successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize or migrate database: {e}", exc_info=True)
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
    description: Fetches job offers from the external API and stores them in the local database, including the company's dark logo URL. Returns a summary of the operation.
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
                total_fetched:
                  type: integer
                  example: 50
                new_offers:
                  type: integer
                  example: 10
                updated_offers:
                  type: integer
                  example: 40
                webhook_sent:
                  type: integer
                  example: 5
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
      502:
        description: Bad Gateway or invalid response format from external API.
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
                  example: Received non-JSON or invalid list response from external API
    """
    external_url = CONFIG['EXTERNAL_ENDPOINT_URL']
    logger.info(f"Request received to fetch and store offers from {external_url}")

    # 1. Fetch data from external API
    response = _make_api_request(external_url)

    if not response:
        return jsonify({
            "status": "error",
            "message": "Failed to fetch data from external API"
        }), 500

    # 2. Parse and Validate Response
    try:
        offers = response.json()
        if not isinstance(offers, list):
            logger.error(f"Store offers endpoint: Invalid response format from {external_url}. Expected a list, got {type(offers)}")
            return jsonify({
                "status": "error",
                "message": "Invalid response format from external API - expected a list of offers"
            }), 502 # Use 502 as it's a problem with the upstream response
    except json.JSONDecodeError as e:
        logger.error(f"Store offers endpoint: Content from {external_url} is not valid JSON: {e}")
        return jsonify({
            "status": "error",
            "message": "Received non-JSON response from external API"
        }), 502
    except Exception as e: # Catch other potential errors during parsing
        logger.exception(f"Unexpected error parsing response from {external_url}")
        return jsonify({"status": "error", "message": "Failed to parse response from external API"}), 500


    # 3. Store Offers in Database
    new_count = 0
    updated_count = 0
    timestamp = datetime.now()
    total_fetched = len(offers)
    new_offers = []  # Track new offers for webhook notification

    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()

            for offer in offers:
                # Extract key fields, using .get() for safety
                offer_id = offer.get('id')
                if offer_id is None:
                    logger.warning(f"Skipping offer due to missing 'id': {offer.get('position', 'N/A')}")
                    continue # Skip offers without an ID

                position = offer.get('position', 'Unknown Position')
                company_data = offer.get('company', {}) # Default to empty dict if 'company' is missing
                company_name = company_data.get('name', 'Unknown Company')

                # Extract nested logoDark URL safely
                logo_dark_data = company_data.get('logoDark', {})
                company_logo_dark_url = logo_dark_data.get('url', None) # Use None if url is missing

                remote_percentage = offer.get('remotePercentage') # Allow None if not present
                salary_from = offer.get('salaryFrom')
                salary_to = offer.get('salaryTo')

                # Handle locations (convert list to comma-separated string)
                locations = offer.get('locations', [])
                locations_str = ', '.join(loc for loc in locations if isinstance(loc, str)) if locations else None

                # Prepare data tuple for insert/update
                offer_data = (
                    position, company_name, remote_percentage, salary_from,
                    salary_to, locations_str, company_logo_dark_url, timestamp, offer_id # offer_id at the end for UPDATE WHERE clause
                )

                # Try INSERT first (more common for new offers)
                try:
                    insert_sql = """
                        INSERT INTO job_offers
                        (offer_id, position, company_name, remote_percentage, salary_from, salary_to,
                         locations, company_logo_dark_url, timestamp, notification_sent)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """
                    # Note: For INSERT, offer_id is first in the VALUES list
                    cursor.execute(insert_sql, (offer_id,) + offer_data[:-1]) # Reorder tuple for INSERT
                    new_count += 1
                    
                    # Add to new offers list for Discord webhook
                    new_offers.append(offer)
                except sqlite3.IntegrityError:
                    # offer_id already exists, so UPDATE instead
                    try:
                        update_sql = """
                            UPDATE job_offers
                            SET position = ?, company_name = ?, remote_percentage = ?,
                                salary_from = ?, salary_to = ?, locations = ?,
                                company_logo_dark_url = ?, timestamp = ?
                            WHERE offer_id = ?
                        """
                        cursor.execute(update_sql, offer_data) # Use original tuple order for UPDATE
                        updated_count += 1
                    except Exception as update_err:
                         logger.error(f"Failed to UPDATE offer_id {offer_id}: {update_err}", exc_info=True)
                         # Decide if you want to stop the whole process or just log and continue
                         # For now, log and continue

            # Commit all changes at the end
            conn.commit()
            logger.info(f"Successfully processed {total_fetched} offers. New: {new_count}, Updated: {updated_count}")

    except sqlite3.Error as db_err:
        logger.error(f"Database error during offer storage: {db_err}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Database error during storage: {str(db_err)}"
        }), 500
    except Exception as e:
        logger.exception(f"Unexpected error during offer storage process: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to store offers due to unexpected error: {str(e)}"
        }), 500

    # 4. Send new offers to Discord webhook
    webhook_sent = 0
    if new_offers and CONFIG['DISCORD_WEBHOOK_URL']:
        webhook_sent = send_webhook_batch(new_offers)
        
        # Update notification_sent flag in database
        if webhook_sent > 0:
            try:
                with get_db_conn() as conn:
                    for offer in new_offers[:webhook_sent]:  # Only mark the ones we successfully sent
                        conn.execute(
                            "UPDATE job_offers SET notification_sent = 1 WHERE offer_id = ?",
                            (offer.get('id'),)
                        )
                    conn.commit()
            except Exception as e:
                logger.error(f"Error updating notification status: {e}")
                # Continue anyway - this is not critical

    # 5. Return Success Summary
    return jsonify({
        "status": "success",
        "total_fetched": total_fetched,
        "new_offers": new_count,
        "updated_offers": updated_count,
        "webhook_sent": webhook_sent,
        "timestamp": timestamp.isoformat()
    })

@app.route('/send-notifications', methods=['GET'])
def send_pending_notifications():
    """
    Send Discord webhook notifications for any pending job offers.
    ---
    tags:
      - Notifications
    summary: Send Discord webhook notifications for pending job offers
    description: Checks the database for job offers that haven't had notifications sent yet and sends them to Discord.
    responses:
      200:
        description: Successfully processed pending notifications.
        content:
          application/json:
            schema:
              type: object
              properties:
                status:
                  type: string
                  example: success
                offers_sent:
                  type: integer
                  example: 5
                pending_offers:
                  type: integer
                  example: 0
      500:
        description: Error processing or sending notifications.
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
                  example: Failed to send notifications
    """
    if not CONFIG['DISCORD_WEBHOOK_URL']:
        return jsonify({
            "status": "error", 
            "message": "Discord webhook URL not configured"
        }), 400
    
    try:
        # Get pending offers from the database
        pending_offers = []
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT offer_id, position, company_name, remote_percentage, 
                       salary_from, salary_to, locations, company_logo_dark_url 
                FROM job_offers
                WHERE notification_sent = 0
                ORDER BY timestamp DESC
                LIMIT 10
            """)
            
            pending_db_offers = cursor.fetchall()
            
            # Convert to list of dicts that match the API format
            for offer_row in pending_db_offers:
                offer_dict = {
                    'id': offer_row[0],
                    'position': offer_row[1],
                    'company': {
                        'name': offer_row[2],
                        'logoDark': {
                            'url': offer_row[7]
                        } if offer_row[7] else {}
                    },
                    'remotePercentage': offer_row[3],
                    'salaryFrom': offer_row[4],
                    'salaryTo': offer_row[5],
                    'locations': offer_row[6].split(', ') if offer_row[6] else [],
                    'slug': f"job-{offer_row[0]}"  # Generate a simple slug
                }
                pending_offers.append(offer_dict)
        
        # Send notifications
        offers_sent = 0
        if pending_offers:
            offers_sent = send_webhook_batch(pending_offers)
            
            # Update notification_sent flag
            if offers_sent > 0:
                with get_db_conn() as conn:
                    for i in range(offers_sent):
                        offer_id = pending_offers[i]['id']
                        conn.execute(
                            "UPDATE job_offers SET notification_sent = 1 WHERE offer_id = ?",
                            (offer_id,)
                        )
                    conn.commit()
        
        return jsonify({
            "status": "success",
            "offers_sent": offers_sent,
            "pending_offers": len(pending_offers) - offers_sent
        })
    
    except Exception as e:
        logger.exception(f"Error sending pending notifications: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to send notifications: {str(e)}"
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
                webhook_configured:
                  type: boolean
                  example: true
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
            # Simple query to ensure the connection is truly working and table exists
            # We query the table we modified to ensure schema changes didn't break it
            conn.execute("SELECT COUNT(*) FROM job_offers LIMIT 1")
    except Exception as e:
        db_status = f"error: {str(e)}"
        is_healthy = False
        logger.error(f"Health check failed due to DB issue: {e}") # Log error specifically for health check failure

    webhook_configured = bool(CONFIG['DISCORD_WEBHOOK_URL'])

    status_code = 200 if is_healthy else 503
    response_body = {
        "status": "healthy" if is_healthy else "unhealthy",
        "timestamp": datetime.now().isoformat(),
        "database_path": CONFIG['DB_PATH'],
        "database_status": db_status,
        "webhook_configured": webhook_configured,
        "config": { # Show only relevant config
            "external_endpoint_url": CONFIG['EXTERNAL_ENDPOINT_URL'],
            "max_retries": CONFIG['MAX_RETRIES'],
            "retry_backoff_factor": CONFIG['RETRY_BACKOFF']
        }
    }
    return jsonify(response_body), status_code

# --- Application Entry Point ---
if __name__ == '__main__':
    # Initialize/Verify the database schema (creates tables and adds columns if needed)
    init_db()

    # Log startup information
    logger.info("-----------------------------------------")
    logger.info("Starting Manfred Job Fetcher")
    logger.info(f"Database Path: {CONFIG['DB_PATH']}")
    logger.info(f"External API Endpoint: {CONFIG['EXTERNAL_ENDPOINT_URL']}")
    logger.info(f"Discord Webhook Configured: {bool(CONFIG['DISCORD_WEBHOOK_URL'])}")
    logger.info("Endpoints available: /raw-offers, /store-offers, /send-notifications, /health, /api/docs")
    logger.info("-----------------------------------------")

    # Run Flask App
    # Use waitress or gunicorn in production instead of app.run()
    # Example: waitress-serve --host 0.0.0.0 --port 5000 app:app
    app.run(host='0.0.0.0', port=5000, debug=False) # debug=False for production/testing

# --- END OF FILE app.py ---