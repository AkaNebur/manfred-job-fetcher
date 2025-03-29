import os
import sqlite3
import json
import logging
from datetime import datetime
import requests
import time
from flask import Flask, request, jsonify
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from swagger import setup_swagger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Setup Swagger documentation
swagger = setup_swagger(app)

# Configuration from environment variables
EXTERNAL_ENDPOINT_URL = os.getenv('EXTERNAL_ENDPOINT_URL', 'https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true')
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')
# The BUILD_ID_HASH might need to be updated periodically if it changes
BUILD_ID_HASH = os.getenv('BUILD_ID_HASH', 'BIDHCAYe6i8X-XyfefcMo')  # Example value
DETAIL_ENDPOINT_PATTERN = os.getenv(
    'DETAIL_ENDPOINT_PATTERN', 
    f'https://www.getmanfred.com/_next/data/{BUILD_ID_HASH}/es/job-offers/{{offer_id}}/{{offer_slug}}.json'
)
DB_PATH = os.getenv('DB_PATH', '/app/data/history.db')
FETCH_INTERVAL = int(os.getenv('FETCH_INTERVAL', '300'))  # Default: 5 minutes
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))
RETRY_BACKOFF = float(os.getenv('RETRY_BACKOFF', '0.5'))

# Configure requests with retry capability
retry_strategy = Retry(
    total=MAX_RETRIES,
    backoff_factor=RETRY_BACKOFF,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
http_session = requests.Session()
http_session.mount("http://", adapter)
http_session.mount("https://", adapter)

# Import and run database initialization
from init_db import init_db

def log_fetch(endpoint, status_code=None, response_size=None, error=None):
    """Log API fetch attempts to the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO fetch_history (timestamp, endpoint, status_code, response_size, error) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(), endpoint, status_code, response_size, error)
        )
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log fetch: {e}")

def save_basic_offer(offer_id, title, company, location=None, remote=None, offer_url=None, slug=None):
    """Save or update basic job offer details in the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if the offer already exists
    cursor.execute("SELECT * FROM job_offers WHERE offer_id = ?", (offer_id,))
    existing = cursor.fetchone()
    
    now = datetime.now()
    
    if existing:
        # Update the existing record
        cursor.execute(
            "UPDATE job_offers SET title = ?, company = ?, location = ?, remote = ?, last_seen = ?, offer_url = ?, slug = ? WHERE offer_id = ?",
            (title, company, location, remote, now, offer_url, slug, offer_id)
        )
        is_new = False
    else:
        # Insert a new record
        cursor.execute(
            "INSERT INTO job_offers (offer_id, title, company, location, remote, first_seen, last_seen, offer_url, slug, notified) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (offer_id, title, company, location, remote, now, now, offer_url, slug, False)
        )
        is_new = True
    
    conn.commit()
    conn.close()
    
    return is_new

def update_offer_details(offer_id, salary_min=None, salary_max=None, currency=None):
    """Update a job offer with detailed information."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE job_offers SET salary_min = ?, salary_max = ?, currency = ?, details_fetched = 1 WHERE offer_id = ?",
        (salary_min, salary_max, currency, offer_id)
    )
    
    conn.commit()
    conn.close()

def get_unnotified_offers():
    """Get all offers that haven't been notified yet."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # This allows accessing columns by name
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM job_offers WHERE notified = 0")
    offers = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return offers

def get_offers_without_details():
    """Get offers that haven't had their details fetched yet."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM job_offers WHERE details_fetched = 0")
    offers = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return offers

def mark_as_notified(offer_id):
    """Mark an offer as notified."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("UPDATE job_offers SET notified = 1 WHERE offer_id = ?", (offer_id,))
    
    conn.commit()
    conn.close()

def send_discord_notification(offers):
    """Send a notification about new job offers to Discord."""
    if not DISCORD_WEBHOOK_URL:
        logger.warning("Discord webhook URL not configured. Skipping notification.")
        return False
    
    if not offers:
        logger.info("No new offers to notify about.")
        return True
    
    # Format the message
    message = {
        "content": f"🚨 Found {len(offers)} new job offers on Manfred!",
        "embeds": []
    }
    
    for offer in offers:
        # Format salary information if available
        salary_info = ""
        if offer.get('salary_min') and offer.get('salary_max') and offer.get('currency'):
            salary_info = f"\nSalary: {offer['salary_min']}-{offer['salary_max']} {offer['currency']}"
        elif offer.get('salary_min') and offer.get('currency'):
            salary_info = f"\nSalary: {offer['salary_min']}+ {offer['currency']}"
        
        # Format location information
        location = offer.get('location', 'Unknown location')
        if offer.get('remote'):
            location += " (Remote available)"
        
        embed = {
            "title": offer['title'],
            "description": f"Company: {offer['company']}\nLocation: {location}{salary_info}",
            "url": offer.get('offer_url', f"https://www.getmanfred.com/es/job-offers/{offer['offer_id']}"),
            "color": 5814783,  # A nice blue color
            "timestamp": datetime.now().isoformat()
        }
        message["embeds"].append(embed)
    
    try:
        response = http_session.post(
            DISCORD_WEBHOOK_URL,
            json=message,
            headers={"Content-Type": "application/json"},
            timeout=10  # Set a timeout to avoid hanging
        )
        response.raise_for_status()
        
        # Mark offers as notified
        for offer in offers:
            mark_as_notified(offer['offer_id'])
        
        return True
    except Exception as e:
        logger.error(f"Failed to send Discord notification: {e}")
        return False

def fetch_job_offer_details(offer_id, slug):
    """Fetch detailed information for a specific job offer."""
    try:
        # Construct the detail endpoint URL
        detail_url = DETAIL_ENDPOINT_PATTERN.format(offer_id=offer_id, offer_slug=slug)
        
        response = http_session.get(detail_url, timeout=10)
        response.raise_for_status()
        
        offer_data = response.json()
        log_fetch(detail_url, response.status_code, len(response.content))
        
        # Extract salary and other detailed information
        offer_details = offer_data.get('pageProps', {}).get('jobOffer', {})
        
        salary_min = None
        salary_max = None
        currency = None
        
        if 'salary' in offer_details:
            salary = offer_details['salary']
            salary_min = salary.get('minAmount')
            salary_max = salary.get('maxAmount')
            currency = salary.get('currency')
        
        # Update the database with the detailed information
        update_offer_details(offer_id, salary_min, salary_max, currency)
        
        return {
            'offer_id': offer_id,
            'salary_min': salary_min,
            'salary_max': salary_max,
            'currency': currency
        }
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error fetching details for offer {offer_id}: {error_msg}")
        log_fetch(detail_url if 'detail_url' in locals() else f"detail-endpoint-for-{offer_id}", error=error_msg)
        return None

def fetch_job_offers():
    """Fetch job offers from Manfred API."""
    try:
        response = http_session.get(EXTERNAL_ENDPOINT_URL, timeout=10)
        response.raise_for_status()
        
        offers_data = response.json()
        log_fetch(EXTERNAL_ENDPOINT_URL, response.status_code, len(response.content))
        
        new_offers = []
        
        for offer in offers_data.get('offers', []):
            offer_id = offer.get('offerId')
            title = offer.get('title', 'Untitled Position')
            company = offer.get('companyName', 'Unknown Company')
            location = offer.get('location', {}).get('city')
            remote = offer.get('remote')
            slug = offer.get('slug')
            offer_url = f"https://www.getmanfred.com/es/job-offers/{offer_id}/{slug}" if slug else None
            
            if offer_id:
                is_new = save_basic_offer(offer_id, title, company, location, remote, offer_url, slug)
                if is_new:
                    new_offers.append({
                        'offer_id': offer_id,
                        'title': title,
                        'company': company,
                        'location': location,
                        'remote': remote,
                        'offer_url': offer_url,
                        'slug': slug
                    })
        
        # Fetch details for new offers (if slug is available)
        for offer in new_offers:
            if offer.get('slug'):
                details = fetch_job_offer_details(offer['offer_id'], offer['slug'])
                if details:
                    offer.update(details)
                # Add a small delay to avoid rate limiting
                time.sleep(1)
        
        # Send notifications for new offers
        if new_offers:
            logger.info(f"Found {len(new_offers)} new job offers.")
            send_discord_notification(new_offers)
        else:
            logger.info("No new job offers found.")
        
        return new_offers
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error fetching job offers: {error_msg}")
        log_fetch(EXTERNAL_ENDPOINT_URL, error=error_msg)
        return None

@app.route('/trigger', methods=['GET', 'POST'])
def trigger_fetch():
    """
    HTTP endpoint to trigger job offer fetching.
    ---
    tags:
      - Job Offers
    summary: Trigger fetching of new job offers
    description: Fetches currently active job offers from Manfred API
    responses:
      200:
        description: Successful operation
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            new_offers_count:
              type: integer
              example: 5
            new_offers:
              type: array
              items:
                type: object
                properties:
                  offer_id:
                    type: string
                  title:
                    type: string
                  company:
                    type: string
      500:
        description: Error fetching job offers
        schema:
          type: object
          properties:
            status:
              type: string
              example: error
            message:
              type: string
    """
    try:
        result = fetch_job_offers()
        if result is None:
            return jsonify({"status": "error", "message": "Failed to fetch job offers"}), 500
        
        return jsonify({
            "status": "success",
            "new_offers_count": len(result),
            "new_offers": result
        })
    except Exception as e:
        logger.exception("Error in trigger endpoint")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/fetch-details', methods=['GET', 'POST'])
def trigger_fetch_details():
    """
    HTTP endpoint to trigger fetching details for offers that don't have them yet.
    ---
    tags:
      - Job Offers
    summary: Fetch details for job offers
    description: Fetches detailed information for job offers that don't have details yet
    responses:
      200:
        description: Successful operation
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            offers_without_details:
              type: integer
              example: 10
            updated_count:
              type: integer
              example: 8
      500:
        description: Error fetching details
        schema:
          type: object
          properties:
            status:
              type: string
              example: error
            message:
              type: string
    """
    try:
        offers = get_offers_without_details()
        updated_count = 0
        
        for offer in offers:
            if offer.get('slug'):
                details = fetch_job_offer_details(offer['offer_id'], offer['slug'])
                if details:
                    updated_count += 1
                # Add a small delay to avoid rate limiting
                time.sleep(1)
        
        return jsonify({
            "status": "success",
            "offers_without_details": len(offers),
            "updated_count": updated_count
        })
    except Exception as e:
        logger.exception("Error in fetch-details endpoint")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """
    Simple health check endpoint.
    ---
    tags:
      - System
    summary: System health check
    description: Checks if the system is healthy and returns configuration details
    responses:
      200:
        description: System health information
        schema:
          type: object
          properties:
            status:
              type: string
              example: healthy
            timestamp:
              type: string
              format: date-time
            database:
              type: string
              example: connected
            config:
              type: object
              properties:
                external_endpoint:
                  type: string
                discord_webhook_configured:
                  type: boolean
                fetch_interval:
                  type: integer
    """
    # Check database connection
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "database": db_status,
        "config": {
            "external_endpoint": EXTERNAL_ENDPOINT_URL,
            "discord_webhook_configured": bool(DISCORD_WEBHOOK_URL),
            "fetch_interval": FETCH_INTERVAL
        }
    })

@app.route('/stats', methods=['GET'])
def stats():
    """
    Endpoint to get statistics about fetched offers.
    ---
    tags:
      - System
    summary: System statistics
    description: Returns statistics about fetched job offers and recent API calls
    responses:
      200:
        description: System statistics
        schema:
          type: object
          properties:
            offers:
              type: object
              properties:
                total:
                  type: integer
                  example: 150
                notified:
                  type: integer
                  example: 120
                with_details:
                  type: integer
                  example: 130
                unnotified:
                  type: integer
                  example: 30
                without_details:
                  type: integer
                  example: 20
            recent_fetches:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  timestamp:
                    type: string
                    format: date-time
                  endpoint:
                    type: string
                  status_code:
                    type: integer
                  response_size:
                    type: integer
                  error:
                    type: string
      500:
        description: Error getting statistics
        schema:
          type: object
          properties:
            status:
              type: string
              example: error
            message:
              type: string
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get total, notified, and with details counts
        cursor.execute("SELECT COUNT(*) as total FROM job_offers")
        total = dict(cursor.fetchone())['total']
        
        cursor.execute("SELECT COUNT(*) as notified FROM job_offers WHERE notified = 1")
        notified = dict(cursor.fetchone())['notified']
        
        cursor.execute("SELECT COUNT(*) as with_details FROM job_offers WHERE details_fetched = 1")
        with_details = dict(cursor.fetchone())['with_details']
        
        # Get recent fetch history
        cursor.execute("SELECT * FROM fetch_history ORDER BY timestamp DESC LIMIT 10")
        recent_fetches = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            "offers": {
                "total": total,
                "notified": notified,
                "with_details": with_details,
                "unnotified": total - notified,
                "without_details": total - with_details
            },
            "recent_fetches": recent_fetches
        })
    except Exception as e:
        logger.exception("Error in stats endpoint")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # Initialize the database
    init_db()
    
    # Log startup
    logger.info("Starting Manfred Job Fetcher")
    
    # Run the Flask app
    app.run(host='0.0.0.0', port=5000)