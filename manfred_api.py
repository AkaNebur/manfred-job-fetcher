# --- START OF FILE manfred_api.py ---
import logging
import json
import httpx
import time

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

def fetch_job_details_data(offer_id, slug):
    """Fetches detailed information for a specific job offer."""
    if not slug:
        logger.warning(f"Skipping job details fetch for offer ID {offer_id} due to missing slug.")
        return None

    # Construct the detail endpoint URL by replacing placeholders
    try:
        # The pattern uses {offer_id} and {offer_slug} as format placeholders
        # First handle the BUILD_ID_HASH replacement which is in shell variable format
        endpoint_url = CONFIG['DETAIL_ENDPOINT_PATTERN'].replace('${BUILD_ID_HASH}', CONFIG['BUILD_ID_HASH'])
        # Then handle the Python format placeholders
        endpoint_url = endpoint_url.format(
            offer_id=offer_id,
            offer_slug=slug
        )
    except KeyError as e:
        logger.error(f"Missing placeholder in DETAIL_ENDPOINT_PATTERN: {e}. Pattern: '{CONFIG['DETAIL_ENDPOINT_PATTERN']}'")
        return None

    logger.info(f"Fetching job details for offer ID {offer_id} from {endpoint_url}")
    response = make_api_request(endpoint_url)

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