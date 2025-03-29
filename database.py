# --- START OF FILE database.py ---
import sqlite3
import os
import logging
from datetime import datetime
from contextlib import contextmanager
from config import CONFIG # Import shared configuration

logger = logging.getLogger(__name__)

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
        conn = sqlite3.connect(db_path, timeout=10) # Increased timeout slightly
        conn.execute("PRAGMA journal_mode=WAL;") # Improve concurrency
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row # Return rows as dict-like objects
        yield conn
    except Exception as e:
        logger.error(f"Database connection error to {db_path}: {e}", exc_info=True)
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
            result = None
            if fetch_one:
                result = cursor.fetchone()
            elif fetch_all:
                result = cursor.fetchall()
            else:
                result = cursor # e.g., for rowcount or lastrowid

            if commit:
                conn.commit()
            return result
    except sqlite3.Error as e:
        logger.error(f"Database error executing SQL: '{sql[:100]}...' with params {params}. Error: {e}", exc_info=True)
        raise # Re-raise after logging
    except Exception as e:
        logger.error(f"Unexpected error during DB operation: {e}", exc_info=True)
        raise # Re-raise after logging

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
    if CONFIG['RESET_DB'] and os.path.exists(CONFIG['DB_PATH']):
         logger.warning(f"RESET_DB is true, deleting existing database: {CONFIG['DB_PATH']}")
         try:
            os.remove(CONFIG['DB_PATH'])
         except OSError as e:
            logger.error(f"Error removing database file: {e}")

    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            # Fetch History Table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS fetch_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                endpoint TEXT NOT NULL,
                status_code INTEGER,
                response_size INTEGER,
                error TEXT
            )''')
            # Job Offers Table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS job_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                offer_id INTEGER NOT NULL UNIQUE,
                position TEXT NOT NULL,
                company_name TEXT NOT NULL,
                remote_percentage INTEGER,
                salary_from INTEGER,
                salary_to INTEGER,
                locations TEXT,
                company_logo_dark_url TEXT,
                slug TEXT,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                notification_sent BOOLEAN DEFAULT 0 NOT NULL,
                skills_retrieved BOOLEAN DEFAULT 0 NOT NULL
            )''')
            # Job Skills Table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS job_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                offer_id INTEGER NOT NULL,
                category TEXT NOT NULL CHECK(category IN ('must', 'nice', 'extra')),
                skill_name TEXT NOT NULL,
                skill_icon TEXT,
                skill_level INTEGER,
                skill_desc TEXT,
                FOREIGN KEY (offer_id) REFERENCES job_offers(offer_id) ON DELETE CASCADE,
                UNIQUE(offer_id, category, skill_name)
            )''')
            # Index for faster lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_offers_offer_id ON job_offers(offer_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_skills_offer_id ON job_skills(offer_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_offers_notification_sent ON job_offers(notification_sent)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_offers_skills_retrieved ON job_offers(skills_retrieved)")

            # Add columns if they don't exist (for backward compatibility)
            # These might not be strictly needed if init_db creates them correctly now,
            # but it's safer for migrations.
            _add_column_if_not_exists(cursor, 'job_offers', 'company_logo_dark_url', 'TEXT')
            _add_column_if_not_exists(cursor, 'job_offers', 'notification_sent', 'BOOLEAN DEFAULT 0 NOT NULL')
            _add_column_if_not_exists(cursor, 'job_offers', 'slug', 'TEXT')
            _add_column_if_not_exists(cursor, 'job_offers', 'skills_retrieved', 'BOOLEAN DEFAULT 0 NOT NULL')

            conn.commit()
            logger.info("Database initialized/verified successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize or migrate database: {e}", exc_info=True)
        raise # Propagate error

def log_fetch_attempt(endpoint, status_code=None, response_size=None, error=None):
    """Log API fetch attempts to the database."""
    try:
        _db_execute(
            "INSERT INTO fetch_history (timestamp, endpoint, status_code, response_size, error) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(), endpoint, status_code, response_size, str(error) if error else None),
            commit=True
        )
    except Exception as e:
        # Avoid crashing the main process if logging fails
        logger.error(f"Failed to log fetch attempt for {endpoint} due to DB error: {e}")

def store_job_skills(offer_id, skills_data):
    """Stores the skills information for a job offer in the database."""
    if not skills_data:
        logger.warning(f"No skills data provided for offer ID {offer_id}")
        return False

    skills_to_insert = []
    for category in ['must', 'nice', 'extra']:
        if category in skills_data and skills_data[category]:
            for skill in skills_data[category]:
                 skills_to_insert.append((
                    offer_id, category,
                    skill.get('skill', ''), skill.get('icon', ''),
                    skill.get('level', 0), skill.get('desc', '')
                 ))

    if not skills_to_insert:
        logger.info(f"No valid skills found in data for offer ID {offer_id}, marking as retrieved anyway.")
        # Mark as retrieved even if no skills found, to avoid retrying indefinitely
        try:
            _db_execute("UPDATE job_offers SET skills_retrieved = 1 WHERE offer_id = ?", (offer_id,), commit=True)
            return True # Indicate processing happened, even if no skills inserted
        except Exception as e:
            logger.error(f"Error marking offer {offer_id} as skills_retrieved: {e}")
            return False


    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            # Clear existing skills first
            cursor.execute("DELETE FROM job_skills WHERE offer_id = ?", (offer_id,))
            # Insert new skills
            cursor.executemany(
               """INSERT OR IGNORE INTO job_skills (offer_id, category, skill_name, skill_icon, skill_level, skill_desc)
                  VALUES (?, ?, ?, ?, ?, ?)""", # Use OR IGNORE for safety with UNIQUE constraint
               skills_to_insert
            )
            # Mark the offer as having skills retrieved
            cursor.execute("UPDATE job_offers SET skills_retrieved = 1 WHERE offer_id = ?", (offer_id,))
            conn.commit()
            logger.info(f"Successfully stored/updated {len(skills_to_insert)} skills for offer ID {offer_id}")
            return True
    except Exception as e:
        logger.error(f"Error storing skills for offer ID {offer_id}: {e}", exc_info=True)
        return False

def get_job_skills_from_db(offer_id):
    """Retrieves the skills for a specific job offer from the database."""
    result = {'must': [], 'nice': [], 'extra': []}
    try:
        rows = _db_execute(
            """SELECT category, skill_name, skill_icon, skill_level, skill_desc
               FROM job_skills WHERE offer_id = ? ORDER BY category, skill_name""",
            (offer_id,),
            fetch_all=True
        )
        if not rows:
             # Check if the offer exists at all and if skills were marked as retrieved
            offer_status = _db_execute("SELECT skills_retrieved FROM job_offers WHERE offer_id = ?", (offer_id,), fetch_one=True)
            if offer_status and offer_status['skills_retrieved']:
                logger.debug(f"No skills found in DB for offer ID {offer_id}, but marked as retrieved.")
            elif offer_status:
                logger.debug(f"No skills found in DB for offer ID {offer_id}, skills not yet retrieved.")
            else:
                 logger.warning(f"Attempted to get skills for non-existent offer ID {offer_id}")
            return result # Return empty structure

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
        logger.error(f"Failed to retrieve skills for offer ID {offer_id} from DB, returning empty. Error: {e}", exc_info=True)
        return result # Return default empty structure on error

def get_pending_skill_offers(limit=10):
    """Retrieves job offers that need skills details fetched."""
    try:
        return _db_execute(
            "SELECT offer_id, slug FROM job_offers WHERE skills_retrieved = 0 LIMIT ?",
            (limit,),
            fetch_all=True
        )
    except Exception as e:
        logger.error(f"Error fetching pending skill offers: {e}", exc_info=True)
        return []

def update_notification_status(offer_ids):
    """Marks offers as notification sent in the database."""
    if not offer_ids: return 0
    try:
        placeholders = ', '.join('?' for _ in offer_ids)
        sql = f"UPDATE job_offers SET notification_sent = 1 WHERE offer_id IN ({placeholders})"
        cursor = _db_execute(sql, offer_ids, commit=True)
        updated_count = cursor.rowcount
        logger.info(f"Marked {updated_count} offers as notification sent.")
        return updated_count
    except Exception as e:
        logger.error(f"Failed to update notification status for offers: {offer_ids}. Error: {e}", exc_info=True)
        return 0

def get_pending_notification_offers(limit=10):
     """Retrieves job offers that have not had notifications sent."""
     try:
         # Fetch all necessary fields to reconstruct the offer for the notification embed
         return _db_execute(
            """SELECT offer_id, position, company_name, remote_percentage,
                       salary_from, salary_to, locations, company_logo_dark_url, slug
               FROM job_offers WHERE notification_sent = 0 ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
            fetch_all=True
         )
     except Exception as e:
        logger.error(f"Error fetching pending notification offers: {e}", exc_info=True)
        return []

def store_or_update_offers(offers):
    """Stores new offers or updates existing ones in the database. Returns list of new offers."""
    new_count = 0
    updated_count = 0
    new_offer_dicts = [] # Store the full dict of new offers

    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            for offer_dict in offers:
                parsed_data = _parse_offer_data(offer_dict)
                if not parsed_data:
                    logger.warning(f"Skipping offer due to missing ID or parse error: {offer_dict.get('position', 'N/A')}")
                    continue

                insert_data, update_data = parsed_data
                offer_id = insert_data[0] # offer_id is the first element

                # Attempt insert
                try:
                    insert_sql = """
                        INSERT INTO job_offers
                        (offer_id, position, company_name, remote_percentage, salary_from, salary_to,
                         locations, company_logo_dark_url, slug, timestamp, notification_sent, skills_retrieved)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)"""
                    cursor.execute(insert_sql, insert_data)
                    if cursor.rowcount > 0:
                        new_count += 1
                        new_offer_dicts.append(offer_dict) # Add the original dict for notifications
                        logger.debug(f"Inserted new offer ID: {offer_id}")
                except sqlite3.IntegrityError:
                    # Offer already exists, attempt update
                    try:
                        update_sql = """
                            UPDATE job_offers
                            SET position = ?, company_name = ?, remote_percentage = ?,
                                salary_from = ?, salary_to = ?, locations = ?,
                                company_logo_dark_url = ?, slug = ?, timestamp = ?
                            WHERE offer_id = ?"""
                        cursor.execute(update_sql, update_data)
                        if cursor.rowcount > 0:
                             updated_count += 1
                             logger.debug(f"Updated existing offer ID: {offer_id}")
                        # else: offer exists but data hasn't changed
                    except Exception as update_err:
                         logger.error(f"Failed to UPDATE offer_id {offer_id}: {update_err}", exc_info=True)
                except Exception as insert_err:
                    logger.error(f"Failed to INSERT offer_id {offer_id}: {insert_err}", exc_info=True)


            conn.commit()
            logger.info(f"Database storage complete. New: {new_count}, Updated: {updated_count}")

    except sqlite3.Error as db_err:
        logger.error(f"Database transaction failed during offer storage: {db_err}", exc_info=True)
        raise # Propagate error
    except Exception as e:
        logger.exception(f"Unexpected error during offer storage batch processing: {e}")
        raise # Propagate error

    return new_count, updated_count, new_offer_dicts # Return the list of new offer dicts

def _parse_offer_data(offer_dict):
    """Parses raw offer dictionary into data tuple for DB insertion/update."""
    offer_id = offer_dict.get('id')
    if offer_id is None: return None

    position = offer_dict.get('position', 'Unknown Position')
    company_data = offer_dict.get('company', {})
    company_name = company_data.get('name', 'Unknown Company')
    logo_url = company_data.get('logoDark', {}).get('url') # Use logoDark as per schema
    slug = offer_dict.get('slug', f"job-{offer_id}") # Generate slug if missing
    remote = offer_dict.get('remotePercentage') # Keep as None if missing
    salary_from = offer_dict.get('salaryFrom')
    salary_to = offer_dict.get('salaryTo')
    locations = offer_dict.get('locations', [])
    # Ensure locations are strings and handle potential None values before joining
    locations_str = ', '.join(str(loc) for loc in locations if loc is not None) if locations else None
    timestamp = datetime.now() # Use current time for insert/update timestamp

    # Data for INSERT (matches VALUES clause in store_or_update_offers)
    insert_data = (
        offer_id, position, company_name, remote, salary_from, salary_to,
        locations_str, logo_url, slug, timestamp
    )
    # Data for UPDATE (matches SET clause + WHERE clause in store_or_update_offers)
    update_data = (
        position, company_name, remote, salary_from, salary_to,
        locations_str, logo_url, slug, timestamp,
        offer_id # For the WHERE clause
    )
    return insert_data, update_data

def check_db_connection():
    """Checks if a connection to the database can be established."""
    try:
        # Try a simple query
        _db_execute("SELECT 1", fetch_one=True)
        return True, "connected"
    except Exception as e:
        logger.error(f"Database connection check failed: {e}", exc_info=False) # Don't need full trace here usually
        return False, f"error: {str(e)}"

def get_offer_by_id(offer_id):
    """Retrieves a single job offer by its ID."""
    try:
        return _db_execute("SELECT * FROM job_offers WHERE offer_id = ?", (offer_id,), fetch_one=True)
    except Exception as e:
        logger.error(f"Error fetching offer by ID {offer_id}: {e}", exc_info=True)
        return None
# --- END OF FILE database.py ---