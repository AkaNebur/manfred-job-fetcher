# --- START OF FILE manfred_api.py ---
import requests
import logging
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import CONFIG # Shared configuration
from database import log_fetch_attempt # Import DB function for logging

logger = logging.getLogger(__name__)

# --- Requests Session with Retries ---
retry_strategy = Retry(
    total=CONFIG['MAX_RETRIES'],
    backoff_factor=CONFIG['RETRY_BACKOFF'],
    status_forcelist=[429, 500, 502, 503, 504], # Retry on these statuses
    allowed_methods=["GET", "POST"] # Retry GET and POST requests
)
adapter = HTTPAdapter(max_retries=retry_strategy)
http_session = requests.Session()
http_session.mount("http://", adapter)
http_session.mount("https://", adapter)
# Standard headers can be set here if needed
# http_session.headers.update({'User-Agent': 'ManfredJobFetcher/1.0'})

def make_api_request(url, method='GET', json_payload=None, timeout=15):
    """Makes an HTTP request with retries and logs the attempt using the database logger."""
    response = None
    error = None
    status_code = None
    response_size = None
    try:
        logger.debug(f"Making {method} request to {url}")
        if method.upper() == 'POST':
            response = http_session.post(url, json=json_payload, headers={"Content-Type": "application/json"}, timeout=timeout)
        else: # Default to GET
            response = http_session.get(url, timeout=timeout)

        status_code = response.status_code
        response_size = len(response.content)
        response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
        logger.debug(f"Request successful: {method} {url} -> {status_code}")
        return response
    except requests.exceptions.Timeout as e:
        error = f"Timeout during request to {url}: {e}"
        logger.error(error)
    except requests.exceptions.HTTPError as e:
        error = f"HTTP error during request to {url}: {e}"
        if e.response is not None:
            status_code = e.response.status_code
            response_size = len(e.response.content) if e.response.content else 0
            # Log more details for HTTP errors
            logger.error(f"{error} - Status: {status_code}, Response: {e.response.text[:200]}")
        else:
             logger.error(error)
    except requests.exceptions.RequestException as e:
        error = f"Request exception for {url}: {e}"
        # Attempt to get status/size if response exists within the exception object
        if hasattr(e, 'response') and e.response is not None:
            status_code = e.response.status_code
            response_size = len(e.response.content) if e.response.content else 0
        logger.error(error, exc_info=True) # Log traceback for generic request errors
    except Exception as e:
        error = f"Unexpected error during request to {url}: {e}"
        logger.exception(f"Unexpected error during request to {url}") # Log full traceback for unexpected errors
    finally:
        # Always log the attempt to the database
        log_fetch_attempt(url, status_code, response_size, error)

    return None # Return None if any error occurred

def fetch_raw_offers_list():
    """Fetches the list of raw job offers from the configured endpoint."""
    endpoint_url = CONFIG['EXTERNAL_ENDPOINT_URL']
    logger.info(f"Fetching raw offers list from {endpoint_url}")
    response = make_api_request(endpoint_url)
    if response:
        try:
            return response.json() # Return parsed JSON
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from {endpoint_url}: {e}")
            return None # Indicate failure to parse
    return None # Indicate failure to fetch

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
            return None # Structure mismatch
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON job details for offer ID {offer_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error processing job details response for offer ID {offer_id}: {e}", exc_info=True)
        return None

# --- END OF FILE manfred_api.py ---