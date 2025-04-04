# --- START OF FILE config.py ---
import os
import logging
import json

def load_config():
    """Loads configuration from environment variables and build_hash.json file."""
    logger = logging.getLogger(__name__)
    
    # Get database path first as we need it for the JSON file path
    db_path = os.getenv('DB_PATH', '/app/data/history.db')
    
    # Initialize build_id_hash as empty - will be fetched from web if not found
    build_id_hash = ""
    
    # Set up path to the build hash JSON file
    config_dir = os.path.join(os.path.dirname(db_path), 'config')
    config_file = os.path.join(config_dir, 'build_hash.json')
    
    # Try to load BUILD_ID_HASH from file first
    try:
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config_data = json.load(f)
                build_id_hash = config_data.get('BUILD_ID_HASH', '')
                if build_id_hash:
                    logger.info(f"Loaded BUILD_ID_HASH from file: {build_id_hash}")
                else:
                    logger.warning("BUILD_ID_HASH in config file is empty")
    except Exception as e:
        logger.warning(f"Failed to load BUILD_ID_HASH from file: {e}")
    
    # If not found in file, check environment variable as fallback
    # This is for backward compatibility during transition
    if not build_id_hash:
        env_hash = os.getenv('BUILD_ID_HASH', '')
        if env_hash:
            logger.info(f"Using BUILD_ID_HASH from environment: {env_hash}")
            build_id_hash = env_hash
            
            # Save to file for future use if directory exists
            try:
                if not os.path.exists(config_dir):
                    os.makedirs(config_dir, exist_ok=True)
                
                with open(config_file, 'w') as f:
                    json.dump({'BUILD_ID_HASH': build_id_hash}, f)
                logger.info(f"Saved environment BUILD_ID_HASH to file for future use")
            except Exception as e:
                logger.warning(f"Failed to save environment BUILD_ID_HASH to file: {e}")
    
    # Get detail endpoint pattern
    detail_pattern = os.getenv(
        'DETAIL_ENDPOINT_PATTERN',
        "https://www.getmanfred.com/_next/data/${BUILD_ID_HASH}/es/job-offers/{offer_id}/{offer_slug}.json"
    )
    
    # Ensure the pattern uses the correct placeholder
    if "${BUILD_ID_HASH}" not in detail_pattern:
        logger.warning("DETAIL_ENDPOINT_PATTERN doesn't contain ${BUILD_ID_HASH} placeholder! Fixing...")
        # Try to fix common pattern issues
        if "${}" in detail_pattern:
            detail_pattern = detail_pattern.replace("${}", "${BUILD_ID_HASH}")
            logger.info("Fixed empty placeholder in DETAIL_ENDPOINT_PATTERN")
    
    # Get other configuration values
    config = {
        'EXTERNAL_ENDPOINT_URL': os.getenv('EXTERNAL_ENDPOINT_URL', 'https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true'),
        'DB_PATH': db_path,
        'MAX_RETRIES': int(os.getenv('MAX_RETRIES', '3')),
        'RETRY_BACKOFF': float(os.getenv('RETRY_BACKOFF', '0.5')),
        'DISCORD_WEBHOOK_URL': os.getenv('DISCORD_WEBHOOK_URL', ''),
        'BUILD_ID_HASH': build_id_hash,
        'DETAIL_ENDPOINT_PATTERN': detail_pattern,
        'CONFIG_FILE_PATH': config_file,  # Save the path for future updates
        'RESET_DB': os.getenv('RESET_DB', 'false').lower() in ('true', '1', 't'),
        'FETCH_INTERVAL': int(os.getenv('FETCH_INTERVAL', '3600')),  # Default to 1 hour (3600 seconds)
        
        # SQLAlchemy specific settings
        'SQLALCHEMY_ECHO': os.getenv('SQLALCHEMY_ECHO', 'false').lower() in ('true', '1', 't'),
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'SQLALCHEMY_ENGINE_OPTIONS': {
            'pool_pre_ping': True,  # Check connection before using from pool
            'pool_recycle': 3600,   # Recycle connections after 1 hour
        },
    }
    
    # Log configuration summary
    if not build_id_hash:
        logger.warning("No BUILD_ID_HASH found in file or environment. Will attempt to fetch from website.")
    
    return config

CONFIG = load_config()

# --- START OF FILE config.py ---