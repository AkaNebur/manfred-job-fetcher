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
    'BUILD_ID_HASH': os.getenv('BUILD_ID_HASH', 'BIDHCAYe6i8X-XyfefcMo'),
    'DETAIL_ENDPOINT_PATTERN': os.getenv(
        'DETAIL_ENDPOINT_PATTERN',
        "https://www.getmanfred.com/_next/data/{build_id}/es/job-offers/{offer_id}/{offer_slug}.json"
    )
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
    allowed_methods=["GET", "POST"]
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
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"Created database directory: {db_dir}")
        except OSError as e:
            logger.error(f"Error creating database directory {db_dir}: {e}")

    try:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row # Return rows as dict-like objects
        yield conn
    except Exception as e:
        logger.error(f"Database connection error to {db_path}: {e}")
        raise
    finally:
        if conn:
            conn.close()

def _db_execute(sql, params=(), fetch_one=False, fetch_all=False, commit=False):
    """Executes a SQL query with error handling and optional fetching/committing."""
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if commit:
                conn.commit()
            if fetch_one:
                return cursor.fetchone()
            if fetch_all:
                return cursor.fetchall()
            return cursor
    except sqlite3.Error as e:
        logger.error(f"Database error executing SQL: {sql} with params {params}. Error: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected error during DB operation: {e}", exc_info=True)
        raise

def _add_column_if_not_exists(cursor, table_name, column_name, column_type):
    """Helper function to add a column if it doesn't exist (requires cursor from get_db_conn)."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [info['name'] for info in cursor.fetchall()]
    if column_name not in columns:
        logger.info(f"Adding column '{column_name}' to table '{table_name}'...")
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        logger.info(f"Column '{column_name}' added successfully.")
    else:
        logger.debug(f"Column '{column_name}' already exists in table '{table_name}'.")

def init_db():
    """Initialize the SQLite database and ensure schema consistency."""
    logger.info(f"Initializing database at {CONFIG['DB_PATH']}...")
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS fetch_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TIMESTAMP NOT NULL, endpoint TEXT NOT NULL,
                status_code INTEGER, response_size INTEGER, error TEXT
            )''')
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS job_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, offer_id INTEGER NOT NULL UNIQUE,
                position TEXT NOT NULL, company_name TEXT NOT NULL, remote_percentage INTEGER,
                salary_from INTEGER, salary_to INTEGER, locations TEXT,
                company_logo_dark_url TEXT, slug TEXT, timestamp TIMESTAMP NOT NULL,
                notification_sent BOOLEAN DEFAULT 0, skills_retrieved BOOLEAN DEFAULT 0
            )''')
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS job_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT, offer_id INTEGER NOT NULL, category TEXT NOT NULL,
                skill_name TEXT NOT NULL, skill_icon TEXT, skill_level INTEGER, skill_desc TEXT,
                FOREIGN KEY (offer_id) REFERENCES job_offers(offer_id) ON DELETE CASCADE,
                UNIQUE(offer_id, category, skill_name)
            )''')

            _add_column_if_not_exists(cursor, 'job_offers', 'company_logo_dark_url', 'TEXT')
            _add_column_if_not_exists(cursor, 'job_offers', 'notification_sent', 'BOOLEAN DEFAULT 0')
            _add_column_if_not_exists(cursor, 'job_offers', 'slug', 'TEXT')
            _add_column_if_not_exists(cursor, 'job_offers', 'skills_retrieved', 'BOOLEAN DEFAULT 0')

            conn.commit()
            logger.info("Database initialized/verified successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize or migrate database: {e}", exc_info=True)


def log_fetch(endpoint, status_code=None, response_size=None, error=None):
    """Log API fetch attempts to the database."""
    try:
        _db_execute(
            "INSERT INTO fetch_history (timestamp, endpoint, status_code, response_size, error) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(), endpoint, status_code, response_size, str(error) if error else None),
            commit=True
        )
    except Exception as e:
        logger.error(f"Failed to log fetch attempt for {endpoint} due to DB error: {e}")


# --- Core Logic Functions ---
def _make_api_request(url, method='GET', json_payload=None, timeout=15):
    """Makes an HTTP request with retries and logs the attempt."""
    response = None
    error = None
    status_code = None
    response_size = None
    try:
        if method.upper() == 'POST':
            response = http_session.post(url, json=json_payload, headers={"Content-Type": "application/json"}, timeout=timeout)
        else: # Default to GET
            response = http_session.get(url, timeout=timeout)

        status_code = response.status_code
        response_size = len(response.content)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        error = str(e)
        if hasattr(e, 'response') and e.response is not None:
            status_code = e.response.status_code
            response_size = len(e.response.content) if e.response.content else 0
        logger.error(f"Request failed for {url}: {e}")
    except Exception as e:
        error = f"Unexpected error during request: {e}"
        logger.exception(f"Unexpected error during request to {url}")
    finally:
        log_fetch(url, status_code, response_size, error)
    return None

def fetch_job_details(offer_id, slug):
    """Fetches detailed information for a specific job offer."""
    if not slug:
        logger.warning(f"Skipping job details fetch for offer ID {offer_id} due to missing slug")
        return None

    endpoint_url = CONFIG['DETAIL_ENDPOINT_PATTERN'].format(
        build_id=CONFIG['BUILD_ID_HASH'],
        offer_id=offer_id,
        offer_slug=slug
    )

    logger.info(f"Fetching job details for offer ID {offer_id} from {endpoint_url}")
    response = _make_api_request(endpoint_url)

    if not response:
        logger.error(f"Failed to fetch job details for offer ID {offer_id}")
        return None

    try:
        data = response.json()
        offer_details = data.get('pageProps', {}).get('offer')
        if offer_details:
            return offer_details
        else:
            logger.error(f"Unexpected response format for job details, offer ID {offer_id}")
            return None
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON job details for offer ID {offer_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error processing job details for offer ID {offer_id}: {e}")
        return None

def store_job_skills(offer_id, skills_data):
    """Stores the skills information for a job offer in the database."""
    if not skills_data:
        logger.warning(f"No skills data provided for offer ID {offer_id}")
        return False

    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM job_skills WHERE offer_id = ?", (offer_id,))

            skills_to_insert = []
            for category in ['must', 'nice', 'extra']:
                if category in skills_data and skills_data[category]:
                    for skill in skills_data[category]:
                         skills_to_insert.append((
                            offer_id, category,
                            skill.get('skill', ''), skill.get('icon', ''),
                            skill.get('level', 0), skill.get('desc', '')
                         ))

            if skills_to_insert:
                 cursor.executemany(
                    """INSERT INTO job_skills (offer_id, category, skill_name, skill_icon, skill_level, skill_desc)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    skills_to_insert
                 )

            cursor.execute("UPDATE job_offers SET skills_retrieved = 1 WHERE offer_id = ?", (offer_id,))
            conn.commit()
            logger.info(f"Successfully stored {len(skills_to_insert)} skills for offer ID {offer_id}")
            return True
    except Exception as e:
        logger.error(f"Error storing skills for offer ID {offer_id}: {e}")
        return False

def get_job_skills(offer_id):
    """Retrieves the skills for a specific job offer from the database."""
    result = {'must': [], 'nice': [], 'extra': []}
    try:
        rows = _db_execute(
            """SELECT category, skill_name, skill_icon, skill_level, skill_desc
               FROM job_skills WHERE offer_id = ? ORDER BY category, skill_name""",
            (offer_id,),
            fetch_all=True
        )

        for row in rows:
            category = row['category']
            if category in result:
                result[category].append({
                    'skill': row['skill_name'],
                    'icon': row['skill_icon'],
                    'level': row['skill_level'],
                    'desc': row['skill_desc']
                })
        return result
    except Exception as e:
        logger.error(f"Failed to retrieve skills for offer ID {offer_id}, returning empty. Error: {e}")
        return result

def process_pending_job_details(limit=10):
    """Processes job offers that don't have detailed skills information yet."""
    processed_count = 0
    try:
        pending_offers = _db_execute(
            "SELECT offer_id, slug FROM job_offers WHERE skills_retrieved = 0 LIMIT ?",
            (limit,),
            fetch_all=True
        )

        if not pending_offers:
            logger.info("No pending job details to process.")
            return 0

        for offer_row in pending_offers:
            offer_id = offer_row['offer_id']
            slug = offer_row['slug']

            job_details = fetch_job_details(offer_id, slug)
            skills_data = job_details.get('skillsSectionData', {}).get('skills') if job_details else None

            if skills_data:
                if store_job_skills(offer_id, skills_data):
                    processed_count += 1
            else:
                if job_details is not None:
                     logger.warning(f"Failed to extract skills data for offer ID {offer_id}, details fetched but skills section missing or empty.")

        logger.info(f"Attempted to process details for {len(pending_offers)} offers, successfully processed skills for {processed_count}.")
        return processed_count
    except Exception as e:
        logger.error(f"Error during the overall processing of pending job details: {e}")
        return processed_count

# --- Discord Webhook Integration ---
def _build_discord_embed(offer):
    """Builds the Discord embed message for a job offer."""
    offer_id = offer.get('id')
    if not offer_id: return None

    position = offer.get('position', 'Unknown Position')
    company_data = offer.get('company', {})
    company_name = company_data.get('name', 'Unknown Company')
    logo_url = company_data.get('logoDark', {}).get('url')
    slug = offer.get('slug', f"job-{offer_id}")
    job_url = f"https://www.getmanfred.com/es/job-offers/{offer_id}/{slug}"

    salary_from = offer.get('salaryFrom')
    salary_to = offer.get('salaryTo')
    salary_text = ""
    if salary_from and salary_to: salary_text = f"💰 {salary_from}€ - {salary_to}€"
    elif salary_from: salary_text = f"💰 From {salary_from}€"
    elif salary_to: salary_text = f"💰 Up to {salary_to}€"

    remote_percentage = offer.get('remotePercentage')
    remote_text = f"🏠 {remote_percentage}% Remote" if remote_percentage is not None else ""

    locations = offer.get('locations', [])
    locations_text = f"📍 {', '.join(locations)}" if locations else ""

    skills_data = get_job_skills(offer_id)
    skills_fields = []
    
    # Format must-have skills with level and line breaks
    if skills_data.get('must'):
        must_skills = []
        for skill in skills_data['must']:
            level_stars = "★" * skill.get('level', 0) if skill.get('level') else ""
            must_skills.append(f"• {skill['skill']} {level_stars}")
        skills_fields.append({
            "name": "🔒 Must Have", 
            "value": "\n".join(must_skills), 
            "inline": False
        })
    
    # Format nice-to-have skills with level and line breaks
    if skills_data.get('nice'):
        nice_skills = []
        for skill in skills_data['nice']:
            level_stars = "★" * skill.get('level', 0) if skill.get('level') else ""
            nice_skills.append(f"• {skill['skill']} {level_stars}")
        skills_fields.append({
            "name": "✨ Nice to Have", 
            "value": "\n".join(nice_skills), 
            "inline": False
        })

    # Add extra skills if they exist
    if skills_data.get('extra'):
        extra_skills = []
        for skill in skills_data['extra']:
            level_stars = "★" * skill.get('level', 0) if skill.get('level') else ""
            extra_skills.append(f"• {skill['skill']} {level_stars}")
        skills_fields.append({
            "name": "➕ Extra Skills", 
            "value": "\n".join(extra_skills), 
            "inline": False
        })

    embed = {
        "title": f"{position} at {company_name}",
        "description": f"{salary_text}\n{remote_text}\n{locations_text}\n\n[View on Manfred]({job_url})".strip(),
        "color": 5814783, # Blue
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "Via Manfred Job Fetcher"},
        "fields": skills_fields
    }
    if logo_url:
        embed["thumbnail"] = {"url": logo_url}

    return embed

def send_discord_webhook(offer):
    """Sends a single job offer embed to Discord."""
    webhook_url = CONFIG['DISCORD_WEBHOOK_URL']
    if not webhook_url:
        logger.warning("Discord webhook URL not configured. Skipping notification.")
        return False

    embed = _build_discord_embed(offer)
    if not embed:
        logger.error(f"Could not build Discord embed for offer: {offer.get('id')}")
        return False

    webhook_data = {"content": "📢 New Job Offer", "embeds": [embed]}

    try:
        response = http_session.post(
            webhook_url,
            json=webhook_data,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        response.raise_for_status()
        logger.info(f"Sent Discord notification for offer ID: {offer.get('id')}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Discord webhook for offer ID {offer.get('id')}: {e}", exc_info=True)
        return False
    except Exception as e:
         logger.error(f"Unexpected error sending Discord webhook for offer ID {offer.get('id')}: {e}", exc_info=True)
         return False

def send_webhook_batch(offers, batch_size=5):
    """Sends a batch of new offers to Discord webhook, limited by batch_size."""
    if not offers: return 0

    sent_count = 0
    for offer in offers[:batch_size]:
        if send_discord_webhook(offer):
            sent_count += 1
            # import time; time.sleep(0.5) # Optional delay

    logger.info(f"Sent {sent_count}/{len(offers)} offers in webhook batch (limit {batch_size}).")
    return sent_count

def _update_notification_status(offer_ids):
    """Marks offers as notification sent in the database."""
    if not offer_ids: return
    try:
        placeholders = ', '.join('?' for _ in offer_ids)
        sql = f"UPDATE job_offers SET notification_sent = 1 WHERE offer_id IN ({placeholders})"
        _db_execute(sql, offer_ids, commit=True)
        logger.info(f"Marked {len(offer_ids)} offers as notification sent.")
    except Exception as e:
        logger.error(f"Failed to update notification status for offers: {offer_ids}. Error: {e}")


def _parse_offer_data(offer_dict):
    """Parses raw offer dictionary into data tuple for DB insertion/update."""
    offer_id = offer_dict.get('id')
    if offer_id is None: return None

    position = offer_dict.get('position', 'Unknown Position')
    company_data = offer_dict.get('company', {})
    company_name = company_data.get('name', 'Unknown Company')
    logo_url = company_data.get('logoDark', {}).get('url')
    slug = offer_dict.get('slug', f"job-{offer_id}")
    remote = offer_dict.get('remotePercentage')
    salary_from = offer_dict.get('salaryFrom')
    salary_to = offer_dict.get('salaryTo')
    locations = offer_dict.get('locations', [])
    locations_str = ', '.join(loc for loc in locations if isinstance(loc, str)) if locations else None
    timestamp = datetime.now()

    update_data = (
        position, company_name, remote, salary_from, salary_to,
        locations_str, logo_url, slug, timestamp, offer_id
    )
    insert_data = (
        offer_id, position, company_name, remote, salary_from, salary_to,
        locations_str, logo_url, slug, timestamp
    )
    return insert_data, update_data


def _store_or_update_offers(offers):
    """Stores new offers or updates existing ones in the database."""
    new_count = 0
    updated_count = 0
    new_offers_list = []

    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            for offer_dict in offers:
                parsed_data = _parse_offer_data(offer_dict)
                if not parsed_data:
                    logger.warning(f"Skipping offer due to missing ID or parse error: {offer_dict.get('position', 'N/A')}")
                    continue

                insert_data, update_data = parsed_data
                offer_id = insert_data[0]

                try:
                    insert_sql = """
                        INSERT INTO job_offers
                        (offer_id, position, company_name, remote_percentage, salary_from, salary_to,
                         locations, company_logo_dark_url, slug, timestamp, notification_sent, skills_retrieved)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)"""
                    cursor.execute(insert_sql, insert_data)
                    new_count += 1
                    new_offers_list.append(offer_dict)
                except sqlite3.IntegrityError:
                    try:
                        update_sql = """
                            UPDATE job_offers
                            SET position = ?, company_name = ?, remote_percentage = ?,
                                salary_from = ?, salary_to = ?, locations = ?,
                                company_logo_dark_url = ?, slug = ?, timestamp = ?
                            WHERE offer_id = ?"""
                        cursor.execute(update_sql, update_data)
                        updated_count += 1
                    except Exception as update_err:
                         logger.error(f"Failed to UPDATE offer_id {offer_id}: {update_err}", exc_info=True)

            conn.commit()
            logger.info(f"Database storage complete. New: {new_count}, Updated: {updated_count}")

    except sqlite3.Error as db_err:
        logger.error(f"Database transaction failed during offer storage: {db_err}")
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during offer storage batch processing: {e}")
        raise

    return new_count, updated_count, new_offers_list


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
                status: {type: string, example: error}
                message: {type: string, example: "Failed to fetch data from external API"}
      502:
        description: Bad Gateway or invalid response from external API.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Received non-JSON or invalid response from external API"}
    """
    external_url = CONFIG['EXTERNAL_ENDPOINT_URL']
    logger.info(f"Request received for raw offers from {external_url}")
    response = _make_api_request(external_url)

    if response:
        try:
            data = response.json()
            return jsonify(data) # Return parsed JSON
        except json.JSONDecodeError as e:
            logger.error(f"Raw offers: Content from {external_url} is not valid JSON: {e}")
            return jsonify({"status": "error", "message": "Received non-JSON response from external API"}), 502
        except Exception as e:
            logger.exception(f"Unexpected error processing raw response from {external_url}")
            return jsonify({"status": "error", "message": "Failed to process response from external API"}), 500
    else:
        return jsonify({"status": "error", "message": "Failed to fetch data from external API"}), 500

@app.route('/store-offers', methods=['GET'])
def store_offers():
    """
    Fetches job offers from the Manfred API, stores/updates them, processes skills, and notifies.

    ---
    tags:
      - Data Storage
    summary: Fetch, store/update job offers, process skills, notify
    description: Fetches offers, stores new ones/updates existing ones, attempts to fetch skills for new offers, sends Discord notifications for new offers (limited batch). Returns a summary.
    responses:
      200:
        description: Successfully fetched and processed job offers.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: success}
                total_fetched: {type: integer}
                new_offers: {type: integer}
                updated_offers: {type: integer}
                skills_processed: {type: integer}
                webhook_sent: {type: integer}
                timestamp: {type: string, format: date-time}
      500:
        description: Error fetching, storing data, or during processing.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Failed to fetch or process job offers"}
      502:
        description: Bad Gateway or invalid response format from external API.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Received non-JSON or invalid list response from external API"}
    """
    external_url = CONFIG['EXTERNAL_ENDPOINT_URL']
    logger.info(f"Request received to fetch and store offers from {external_url}")
    start_time = datetime.now()

    # 1. Fetch data
    response = _make_api_request(external_url)
    if not response:
        return jsonify({"status": "error", "message": "Failed to fetch data from external API"}), 500

    # 2. Parse and Validate Response
    try:
        offers_list = response.json()
        if not isinstance(offers_list, list):
            logger.error(f"Store offers: Invalid response format from {external_url}. Expected list, got {type(offers_list)}")
            return jsonify({"status": "error", "message": "Invalid response format from external API - expected list"}), 502
    except json.JSONDecodeError as e:
        logger.error(f"Store offers: Content from {external_url} is not valid JSON: {e}")
        return jsonify({"status": "error", "message": "Received non-JSON response from external API"}), 502
    except Exception as e:
        logger.exception(f"Unexpected error parsing response from {external_url}")
        return jsonify({"status": "error", "message": "Failed to parse response from external API"}), 500

    total_fetched = len(offers_list)
    new_count, updated_count, skills_processed, webhook_sent = 0, 0, 0, 0
    new_offers_for_webhook = []

    # 3. Store/Update Offers
    try:
        new_count, updated_count, new_offers_for_webhook = _store_or_update_offers(offers_list)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed during offer storage: {str(e)}"}), 500

    # 4. Process skills for NEW offers
    if new_offers_for_webhook:
        logger.info(f"Processing skills details for {len(new_offers_for_webhook)} new offers...")
        skills_processed = process_pending_job_details()

    # 5. Send new offers to Discord
    if new_offers_for_webhook and CONFIG['DISCORD_WEBHOOK_URL']:
        logger.info(f"Sending {len(new_offers_for_webhook)} new offers to Discord webhook...")
        webhook_sent = send_webhook_batch(new_offers_for_webhook)

        if webhook_sent > 0:
            sent_offer_ids = [offer['id'] for offer in new_offers_for_webhook[:webhook_sent] if 'id' in offer]
            _update_notification_status(sent_offer_ids)

    # 6. Return Success Summary
    return jsonify({
        "status": "success",
        "total_fetched": total_fetched,
        "new_offers": new_count,
        "updated_offers": updated_count,
        "skills_processed": skills_processed,
        "webhook_sent": webhook_sent,
        "timestamp": start_time.isoformat()
    })


@app.route('/process-job-details', methods=['GET'])
def process_job_details_endpoint():
    """
    Processes pending job offers to fetch and store detailed skills information.

    ---
    tags:
      - Data Processing
    summary: Process job offers to fetch and store detailed skills information
    description: Finds job offers marked as needing skills details, fetches their data from the Manfred API (limited batch), and stores the skills.
    responses:
      200:
        description: "Successfully processed job offers."
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: success}
                processed_count: {type: integer}
                timestamp: {type: string, format: date-time}
      500:
        description: "Error processing job offers."
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Failed to process job offers"}
    """
    logger.info("Request received to process pending job details")
    try:
        processed_count = process_pending_job_details()
        return jsonify({
            "status": "success",
            "processed_count": processed_count,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.exception(f"Error processing job details endpoint: {e}")
        return jsonify({"status": "error", "message": f"Failed to process job details: {str(e)}"}), 500

@app.route('/job-skills/<int:offer_id>', methods=['GET'])
def get_job_skills_endpoint(offer_id):
    """
    Gets the stored skills for a specific job offer.

    ---
    tags:
      - Data Processing
    summary: Get skills for a specific job offer
    description: Retrieves the stored skills information (must, nice, extra) for a given job offer ID from the database.
    parameters:
      - name: offer_id
        in: path
        description: "ID of the job offer"
        required: true
        schema:
          type: integer
    responses:
      200:
        description: "Successfully retrieved job skills."
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: success}
                offer_id: {type: integer}
                skills:
                  type: object
                  properties:
                    must: {type: array, items: {type: object}}
                    nice: {type: array, items: {type: object}}
                    extra: {type: array, items: {type: object}}
      404:
        description: "Job offer not found."
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Job offer not found"}
      500:
        description: "Error retrieving job skills."
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Failed to retrieve job skills"}
    """
    logger.info(f"Request received to get skills for offer ID {offer_id}")
    try:
        offer_exists = _db_execute("SELECT 1 FROM job_offers WHERE offer_id = ?", (offer_id,), fetch_one=True)
        if not offer_exists:
            return jsonify({"status": "error", "message": "Job offer not found"}), 404

        skills = get_job_skills(offer_id)
        return jsonify({"status": "success", "offer_id": offer_id, "skills": skills})
    except Exception as e:
        logger.error(f"Failed to retrieve skills via endpoint for offer ID {offer_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to retrieve job skills: {str(e)}"}), 500

@app.route('/send-notifications', methods=['GET'])
def send_pending_notifications():
    """
    Sends Discord notifications for job offers marked as not sent yet.

    ---
    tags:
      - Notifications
    summary: Send Discord notifications for pending job offers
    description: Checks the database for job offers where notification_sent is false, sends them to Discord (limited batch), and updates their status.
    responses:
      200:
        description: Successfully processed pending notifications.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: success}
                offers_sent: {type: integer}
                remaining_pending: {type: integer}
      400:
        description: Discord webhook not configured.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string}
      500:
        description: Error processing or sending notifications.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string}
    """
    if not CONFIG['DISCORD_WEBHOOK_URL']:
        return jsonify({"status": "error", "message": "Discord webhook URL not configured"}), 400

    logger.info("Request received to send pending notifications.")
    offers_to_send = []
    pending_db_offers = []
    try:
         pending_db_offers = _db_execute(
            """SELECT offer_id, position, company_name, remote_percentage,
                       salary_from, salary_to, locations, company_logo_dark_url, slug
               FROM job_offers WHERE notification_sent = 0 ORDER BY timestamp DESC LIMIT 10""",
            fetch_all=True
         )

         for offer_row in pending_db_offers:
             offers_to_send.append({
                 'id': offer_row['offer_id'],
                 'position': offer_row['position'],
                 'company': {'name': offer_row['company_name'],
                             'logoDark': {'url': offer_row['company_logo_dark_url']} if offer_row['company_logo_dark_url'] else {}},
                 'remotePercentage': offer_row['remote_percentage'],
                 'salaryFrom': offer_row['salary_from'],
                 'salaryTo': offer_row['salary_to'],
                 'locations': offer_row['locations'].split(', ') if offer_row['locations'] else [],
                 'slug': offer_row['slug'] if offer_row['slug'] else f"job-{offer_row['offer_id']}"
             })

    except Exception as e:
        logger.error(f"Failed to fetch pending offers from DB: {e}")
        return jsonify({"status": "error", "message": "Failed to retrieve pending offers from database"}), 500

    offers_sent = 0
    if offers_to_send:
        offers_sent = send_webhook_batch(offers_to_send)

        if offers_sent > 0:
            sent_offer_ids = [offer['id'] for offer in offers_to_send[:offers_sent]]
            _update_notification_status(sent_offer_ids)

    return jsonify({
        "status": "success",
        "offers_sent": offers_sent,
        "remaining_pending": len(offers_to_send) - offers_sent
    })


@app.route('/health', methods=['GET'])
def health_check():
    """
    Performs a health check on the service, including DB connectivity.

    ---
    tags:
      - System
    summary: System health check
    description: Checks database connectivity and returns basic configuration status.
    responses:
      200:
        description: System is healthy.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: healthy}
                timestamp: {type: string, format: date-time}
                database_path: {type: string}
                database_status: {type: string}
                webhook_configured: {type: boolean}
                config: {type: object}
      503:
        description: Service Unavailable (e.g., database connection failed).
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: unhealthy}
                timestamp: {type: string, format: date-time}
                database_path: {type: string}
                database_status: {type: string}
    """
    db_status = "connected"
    is_healthy = True
    try:
        _db_execute("SELECT COUNT(*) FROM job_offers LIMIT 1", fetch_one=True)
    except Exception as e:
        db_status = f"error: {str(e)}"
        is_healthy = False
        logger.error(f"Health check failed due to DB issue: {e}")

    webhook_configured = bool(CONFIG['DISCORD_WEBHOOK_URL'])
    status_code = 200 if is_healthy else 503

    relevant_config = {k: CONFIG[k] for k in ['EXTERNAL_ENDPOINT_URL', 'MAX_RETRIES', 'RETRY_BACKOFF']}

    return jsonify({
        "status": "healthy" if is_healthy else "unhealthy",
        "timestamp": datetime.now().isoformat(),
        "database_path": CONFIG['DB_PATH'],
        "database_status": db_status,
        "webhook_configured": webhook_configured,
        "config": relevant_config
    }), status_code

# --- Application Entry Point ---
if __name__ == '__main__':
    init_db()

    logger.info("-----------------------------------------")
    logger.info("Starting Manfred Job Fetcher (Refactored & Fixed)")
    logger.info(f"DB Path: {CONFIG['DB_PATH']}")
    logger.info(f"External API: {CONFIG['EXTERNAL_ENDPOINT_URL']}")
    logger.info(f"Webhook Configured: {bool(CONFIG['DISCORD_WEBHOOK_URL'])}")
    logger.info("Endpoints: /raw-offers, /store-offers, /send-notifications, /health, /api/docs, /process-job-details, /job-skills/{offer_id}")
    logger.info("-----------------------------------------")

    # Use waitress or gunicorn in production
    # Example: waitress-serve --host 0.0.0.0 --port 5000 app:app
    app.run(host='0.0.0.0', port=5000, debug=False)

# --- END OF FILE app.py ---