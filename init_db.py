import sqlite3
import os
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = os.getenv('DB_PATH', '/app/data/history.db')

# Ensure the database directory exists
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def init_db():
    """Initialize the SQLite database with the required schema."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create table for job offers
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS job_offers (
        offer_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        company TEXT NOT NULL,
        location TEXT,
        remote BOOLEAN,
        salary_min INTEGER,
        salary_max INTEGER,
        currency TEXT,
        first_seen TIMESTAMP NOT NULL,
        last_seen TIMESTAMP NOT NULL,
        offer_url TEXT,
        slug TEXT,
        details_fetched BOOLEAN DEFAULT 0,
        notified BOOLEAN DEFAULT 0
    )
    ''')
    
    # Create table for fetch history (for debugging/monitoring)
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
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

if __name__ == '__main__':
    init_db()