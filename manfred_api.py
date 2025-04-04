# --- START OF FILE manfred_api.py ---
import logging
import json
import httpx
import time
import os
import re

from config import CONFIG  # Shared configuration
from database import log_fetch_attempt  # Import DB function for logging

logger = logging.getLogger(__name__)

# Create a persistent httpx Client
http_client = httpx.Client(
    timeout=15.0,
    follow_redirects=True
)

def make_api_request(url, method='GET', json_payload=None, timeout=15):
    """Makes an HTTP request with retries and logs the attempt using the database logger."""
    response = None
    error = None
    status_code = None
    response_size = None
    
    # Get retry settings from config
    max_retries = CONFIG['MAX_RETRIES']
    backoff_factor = CONFIG['RETRY_BACKOFF']
    
    # Initialize retry counter
    retries = 0
    
    while retries <= max_retries:
        try:
            logger.debug(f"Making {method} request to {url} (attempt {retries+1}/{max_retries+1})")
            
            if method.upper() == 'POST':
                response = http_client.post(
                    url, 
                    json=json_payload, 
                    headers={"Content-Type": "application/json"}, 
                    timeout=timeout
                )
            else:  # Default to GET
                response = http_client.get(url, timeout=timeout)

            status_code = response.status_code
            response_size = len(response.content)
            
            # Success - no need to retry
            if 200 <= status_code < 300:
                logger.debug(f"Request successful: {method} {url} -> {status_code}")
                return response
                
            # Server errors or specific status codes that warrant a retry
            if status_code in [429, 500, 502, 503, 504] and retries < max_retries:
                retries += 1
                sleep_time = backoff_factor * (2 ** retries)
                logger.warning(f"Request failed with status {status_code}. Retrying in {sleep_time:.2f}s ({retries}/{max_retries})")
                time.sleep(sleep_time)
                continue
                
            # Client errors or other status codes that don't warrant a retry
            response.raise_for_status()  # Will raise an HTTPStatusError for status codes 4xx/5xx
            
        except httpx.TimeoutException as e:
            error = f"Timeout during request to {url}: {e}"
            logger.error(error)
            
            if retries < max_retries:
                retries += 1
                sleep_time = backoff_factor * (2 ** retries)
                logger.warning(f"Request timed out. Retrying in {sleep_time:.2f}s ({retries}/{max_retries})")
                time.sleep(sleep_time)
                continue
            break
            
        except httpx.HTTPStatusError as e:
            # Already handled status codes that warrant retries above
            error = f"HTTP error during request to {url}: {e}"
            if e.response is not None:
                status_code = e.response.status_code
                response_size = len(e.response.content) if e.response.content else 0
                logger.error(f"{error} - Status: {status_code}, Response: {e.response.text[:200]}")
            else:
                logger.error(error)
            break
            
        except httpx.RequestError as e:
            error = f"Request exception for {url}: {e}"
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                response_size = len(e.response.content) if e.response.content else 0
            
            if retries < max_retries:
                retries += 1
                sleep_time = backoff_factor * (2 ** retries)
                logger.warning(f"Request failed with error. Retrying in {sleep_time:.2f}s ({retries}/{max_retries})")
                time.sleep(sleep_time)
                continue
                
            logger.error(error, exc_info=True)
            break
            
        except Exception as e:
            error = f"Unexpected error during request to {url}: {e}"
            logger.exception(f"Unexpected error during request to {url}")
            break
    
    # Log the attempt regardless of success or failure
    log_fetch_attempt(url, status_code, response_size, error)
    return None  # Return None if all retries failed

def fetch_raw_offers_list():
    """Fetches the list of raw job offers from the configured endpoint."""
    endpoint_url = CONFIG['EXTERNAL_ENDPOINT_URL']
    logger.info(f"Fetching raw offers list from {endpoint_url}")
    response = make_api_request(endpoint_url)
    if response:
        try:
            return response.json()  # Return parsed JSON
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from {endpoint_url}: {e}")
            return None  # Indicate failure to parse
    return None  # Indicate failure to fetch

def save_build_hash_to_file(build_hash):
    """
    Saves the BUILD_ID_HASH to a file for persistence between restarts.
    Returns True if successful, False otherwise.
    """
    try:
        # Get the path from CONFIG if available, otherwise construct it
        if 'CONFIG_FILE_PATH' in CONFIG:
            config_file = CONFIG['CONFIG_FILE_PATH']
        else:
            # Create a config directory if it doesn't exist
            config_dir = os.path.join(os.path.dirname(CONFIG['DB_PATH']), 'config')
            os.makedirs(config_dir, exist_ok=True)
            config_file = os.path.join(config_dir, 'build_hash.json')
        
        # Write the hash to the file
        with open(config_file, 'w') as f:
            json.dump({'BUILD_ID_HASH': build_hash}, f)
        
        # Update CONFIG in memory
        CONFIG['BUILD_ID_HASH'] = build_hash
        
        logger.info(f"Saved BUILD_ID_HASH to {config_file}: {build_hash}")
        return True
    except Exception as e:
        logger.error(f"Failed to save BUILD_ID_HASH to file: {e}", exc_info=True)
        return False

def fetch_and_update_build_id_hash():
    """
    Fetches the current BUILD_ID_HASH from the getmanfred.com website and updates CONFIG.
    Returns True if successful, False otherwise.
    """
    try:
        # Log current hash for debugging
        current_hash = CONFIG['BUILD_ID_HASH']
        logger.info(f"Current BUILD_ID_HASH before update attempt: {current_hash}")
        
        # Log config source and env var for complete debugging
        config_file = os.path.join(os.path.dirname(CONFIG['DB_PATH']), 'config', 'build_hash.json')
        env_hash = os.environ.get('BUILD_ID_HASH', 'NOT_SET')
        
        logger.debug(f"BUILD_ID_HASH from environment: {env_hash}")
        logger.debug(f"Config file path: {config_file}")
        
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    import json
                    json_data = json.load(f)
                    json_hash = json_data.get('BUILD_ID_HASH', 'NOT_FOUND')
                    logger.debug(f"BUILD_ID_HASH from json file: {json_hash}")
            except Exception as e:
                logger.warning(f"Could not read hash from config file: {e}")
        
        # Fetch the main page
        logger.info("Attempting to fetch new BUILD_ID_HASH from getmanfred.com")
        main_page_url = "https://www.getmanfred.com/es/ofertas-empleo"  # Updated URL based on redirects in logs
        response = make_api_request(main_page_url)
        
        if not response:
            logger.error("Failed to fetch main page to extract BUILD_ID_HASH")
            return False
        
        html_content = response.text
        
        # Extract the build ID hash using a regular expression
        # Looking for patterns like: "buildId":"BIDHCAYe6i8X-XyfefcMo"
        pattern = r'"buildId":"([a-zA-Z0-9_-]+)"'
        match = re.search(pattern, html_content)
        
        if not match:
            logger.error("Could not find BUILD_ID_HASH in the main page content")
            # Log a sample of the HTML to help debug
            logger.debug(f"HTML sample: {html_content[:500]}")
            return False
        
        new_hash = match.group(1)
        logger.info(f"Extracted hash from website: {new_hash}")
        
        # Check if the hash is different from the current one
        if new_hash == CONFIG['BUILD_ID_HASH']:
            logger.info(f"Current BUILD_ID_HASH is already up-to-date: {new_hash}")
            return True
        
        # Update the CONFIG dictionary
        old_hash = CONFIG['BUILD_ID_HASH']
        CONFIG['BUILD_ID_HASH'] = new_hash
        
        # Save the new hash to file for persistence between restarts
        save_result = save_build_hash_to_file(new_hash)
        if not save_result:
            logger.warning("Failed to save new hash to file, but CONFIG was updated in memory")
        
        # Also update the environment variable
        os.environ['BUILD_ID_HASH'] = new_hash
        
        logger.info(f"Successfully updated BUILD_ID_HASH from {old_hash} to {new_hash}")
        return True
    
    except Exception as e:
        logger.error(f"Error fetching and updating BUILD_ID_HASH: {e}", exc_info=True)
        return False

def fetch_job_details_data(offer_id, slug, retry_on_hash_error=True):
    """Fetches detailed information for a specific job offer."""
    if not slug:
        logger.warning(f"Skipping job details fetch for offer ID {offer_id} due to missing slug.")
        return None

    # Construct the detail endpoint URL by replacing placeholders
    try:
        # Get the current hash from CONFIG
        current_hash = CONFIG.get('BUILD_ID_HASH', '')
        
        # If hash is empty, try to fetch it first
        if not current_hash and retry_on_hash_error:
            logger.warning("BUILD_ID_HASH is empty, fetching it before proceeding")
            if fetch_and_update_build_id_hash():
                current_hash = CONFIG.get('BUILD_ID_HASH', '')
                if not current_hash:
                    logger.error("Failed to get BUILD_ID_HASH even after update attempt")
                    return None
            else:
                logger.error("Failed to fetch BUILD_ID_HASH, cannot proceed with job details request")
                return None
        
        logger.debug(f"Using BUILD_ID_HASH for request: {current_hash}")
        
        # Get the pattern and replace the placeholder
        pattern = CONFIG['DETAIL_ENDPOINT_PATTERN']
        logger.debug(f"Original pattern: {pattern}")
        
        # Handle different placeholder formats for backward compatibility
        if "${BUILD_ID_HASH}" in pattern:
            endpoint_url = pattern.replace('${BUILD_ID_HASH}', current_hash)
        elif "${}" in pattern:
            endpoint_url = pattern.replace('${}', current_hash)
        else:
            # Fallback to manually constructing the URL if pattern is unexpected
            logger.warning(f"Could not find BUILD_ID_HASH placeholder in pattern: {pattern}")
            endpoint_url = f"https://www.getmanfred.com/_next/data/{current_hash}/es/job-offers/{offer_id}/{offer_slug}.json"
        
        logger.debug(f"Endpoint URL after hash replacement: {endpoint_url}")
        
        # Now handle the Python format placeholders
        try:
            endpoint_url = endpoint_url.format(
                offer_id=offer_id,
                offer_slug=slug
            )
        except KeyError as e:
            logger.error(f"Error in format placeholders: {e}. Using direct URL construction.")
            endpoint_url = f"https://www.getmanfred.com/_next/data/{current_hash}/es/job-offers/{offer_id}/{slug}.json"
        
        logger.info(f"Final endpoint URL: {endpoint_url}")
        
    except Exception as e:
        logger.error(f"Error constructing URL: {e}", exc_info=True)
        # Fallback to a simple construction method
        current_hash = CONFIG.get('BUILD_ID_HASH', '')
        endpoint_url = f"https://www.getmanfred.com/_next/data/{current_hash}/es/job-offers/{offer_id}/{slug}.json"
        logger.info(f"Using fallback URL: {endpoint_url}")

    logger.info(f"Fetching job details for offer ID {offer_id} from {endpoint_url}")
    response = make_api_request(endpoint_url)

    # Check if the request failed and it might be due to an invalid hash
    if not response and retry_on_hash_error:
        # Try to update the hash and retry
        logger.warning(f"Failed to fetch job details, attempting to update BUILD_ID_HASH and retry")
        if fetch_and_update_build_id_hash():
            # Retry the request with the new hash (disable retry_on_hash_error to avoid infinite recursion)
            return fetch_job_details_data(offer_id, slug, retry_on_hash_error=False)
        else:
            logger.error(f"Failed to update BUILD_ID_HASH, cannot retry request")
    
    if not response:
        logger.error(f"Failed to fetch job details for offer ID {offer_id} (request failed).")
        return None

    try:
        data = response.json()
        # Navigate the expected structure to find the offer details
        offer_details = data.get('pageProps', {}).get('offer')
        if offer_details and isinstance(offer_details, dict):
            logger.info(f"Successfully fetched and parsed details for offer ID {offer_id}.")
            return offer_details
        else:
            logger.warning(f"Could not find 'pageProps.offer' in the response for job details, offer ID {offer_id}. Response keys: {list(data.keys())}")
            # Check if this might be due to an invalid hash (e.g., the response structure is completely different)
            if retry_on_hash_error and ('error' in data or 'notFound' in data):
                logger.warning(f"Response indicates possible invalid hash, attempting to update BUILD_ID_HASH and retry")
                if fetch_and_update_build_id_hash():
                    # Retry the request with the new hash
                    return fetch_job_details_data(offer_id, slug, retry_on_hash_error=False)
                else:
                    logger.error(f"Failed to update BUILD_ID_HASH, cannot retry request")
            return None  # Structure mismatch
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON job details for offer ID {offer_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error processing job details response for offer ID {offer_id}: {e}", exc_info=True)
        return None

def close_http_client():
    """Closes the HTTP client to free resources. Should be called during application shutdown."""
    try:
        http_client.close()
        logger.info("HTTP client closed successfully")
    except Exception as e:
        logger.error(f"Error closing HTTP client: {e}")

# Function to help with retries for other modules
def get_retry_for_request(func):
    """
    A helper function that can be used to add retry logic to any request function.
    Usage:
    
    @get_retry_for_request
    def my_request_function(url):
        return requests.get(url)
    """
    def wrapper(*args, **kwargs):
        max_retries = CONFIG['MAX_RETRIES']
        backoff_factor = CONFIG['RETRY_BACKOFF']
        
        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt >= max_retries:
                    raise
                
                sleep_time = backoff_factor * (2 ** attempt)
                logger.warning(f"Request failed with {e}. Retrying in {sleep_time:.2f}s. "
                              f"Attempt {attempt+1}/{max_retries+1}")
                time.sleep(sleep_time)
        
        return None  # This should never be reached
    
    return wrapper

# --- END OF FILE manfred_api.py ---