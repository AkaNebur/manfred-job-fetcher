# --- UPDATED FILE config.py ---
import os

def load_config():
    """Loads configuration from environment variables."""
    detail_pattern = os.getenv(
        'DETAIL_ENDPOINT_PATTERN',
        "https://www.getmanfred.com/_next/data/{build_id}/es/job-offers/{offer_id}/{offer_slug}.json"
    )
    
    return {
        'EXTERNAL_ENDPOINT_URL': os.getenv('EXTERNAL_ENDPOINT_URL', 'https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true'),
        'DB_PATH': os.getenv('DB_PATH', '/app/data/history.db'),
        'MAX_RETRIES': int(os.getenv('MAX_RETRIES', '3')),
        'RETRY_BACKOFF': float(os.getenv('RETRY_BACKOFF', '0.5')),
        'DISCORD_WEBHOOK_URL': os.getenv('DISCORD_WEBHOOK_URL', ''),
        'BUILD_ID_HASH': os.getenv('BUILD_ID_HASH', 'BIDHCAYe6i8X-XyfefcMo'),
        'DETAIL_ENDPOINT_PATTERN': detail_pattern,
        'RESET_DB': os.getenv('RESET_DB', 'false').lower() in ('true', '1', 't'),
        'FETCH_INTERVAL': int(os.getenv('FETCH_INTERVAL', '3600')),  # Default to 1 hour (3600 seconds)
        
        # SQLAlchemy specific settings
        'SQLALCHEMY_ECHO': os.getenv('SQLALCHEMY_ECHO', 'false').lower() in ('true', '1', 't'),
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'SQLALCHEMY_ENGINE_OPTIONS': {
            'pool_pre_ping': True,  # Check connection before using from pool
            'pool_recycle': 3600,   # Recycle connections after 1 hour
        },
        
        # Flask specific configs might stay in app.py or move here if needed globally
        # 'FLASK_ENV': os.getenv('FLASK_ENV', 'production'),
        # 'FLASK_DEBUG': os.getenv('FLASK_DEBUG', '0'),
    }

CONFIG = load_config()

# --- END OF UPDATED FILE config.py ---