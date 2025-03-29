# --- START OF FILE routes.py ---
import logging
from flask import Blueprint, jsonify, request

# Import service functions that the routes will call
import services
import manfred_api # Need this for raw offers directly
import database # Need this for raw offers directly

logger = logging.getLogger(__name__)

# Create a Blueprint for API routes
api_bp = Blueprint('api', __name__)

# --- Route Definitions ---

@api_bp.route('/raw-offers', methods=['GET'])
def get_raw_offers():
    """
    Fetches and returns the raw JSON data from the external Manfred API.
    ---
    tags:
      - Raw Data
    summary: Get raw job offers list from Manfred API
    description: Directly fetches and returns the JSON response from the configured EXTERNAL_ENDPOINT_URL without processing or saving. Uses configured retries via the underlying API call.
    responses:
      200:
        description: Raw list of active job offers from the external API.
        content:
          application/json:
            schema:
              type: array # Assuming the API returns a list
              items:
                type: object
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
        description: Bad Gateway or invalid response from external API (e.g., not JSON).
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Received non-JSON or invalid response from external API"}
    """
    logger.info("Route: GET /raw-offers")
    try:
        # Use the API function directly for raw data
        data = manfred_api.fetch_raw_offers_list()
        if data is not None:
             # Check if it's a list (as expected) or handle other valid JSON types if needed
            if isinstance(data, (list, dict)):
                return jsonify(data), 200
            else:
                 logger.error(f"Raw offers: Unexpected data type returned: {type(data)}")
                 return jsonify({"status": "error", "message": "Unexpected data type received from external API"}), 502
        else:
            # fetch_raw_offers_list already logged the error
            return jsonify({"status": "error", "message": "Failed to fetch data from external API"}), 500
    except Exception as e:
        logger.exception("Route: Unexpected error in /raw-offers") # Log full trace for unexpected route errors
        return jsonify({"status": "error", "message": "An internal server error occurred"}), 500


@api_bp.route('/store-offers', methods=['GET'])
def store_offers_route():
    """
    Fetches job offers from the Manfred API, stores/updates them, processes skills, and notifies.
    ---
    tags:
      - Data Storage & Processing
    summary: Fetch, store/update job offers, process skills, notify
    description: Orchestrates fetching offers, storing new/updating existing ones, attempting to fetch skills for new offers, and sending Discord notifications for new offers (limited batch). Returns a summary of actions.
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
                duration_seconds: { type: number, format: float }
      500:
        description: Error during the fetch/store/process workflow.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Failed during offer storage: [Details]"}
      502:
        description: Error communicating with or parsing response from the external API.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Invalid response format from external API - expected list"}
    """
    logger.info("Route: GET /store-offers")
    try:
        result = services.fetch_and_store_offers_service()
        status_code = 500 if result.get("status") == "error" else 200
        # Handle specific upstream errors resulting in 502
        if "Invalid response format" in result.get("message", "") or \
           "Failed to fetch data" in result.get("message", ""):
            status_code = 502

        return jsonify(result), status_code
    except Exception as e:
        logger.exception("Route: Unexpected error in /store-offers")
        return jsonify({"status": "error", "message": "An internal server error occurred"}), 500

@api_bp.route('/process-job-details', methods=['GET'])
def process_job_details_route():
    """
    Processes pending job offers to fetch and store detailed skills information.
    ---
    tags:
      - Data Processing
    summary: Process job offers to fetch and store detailed skills information
    description: Finds job offers marked as needing skills details, fetches their data from the Manfred API (using a configurable limit), stores the extracted skills, and marks the offer as processed.
    parameters:
      - name: limit
        in: query
        description: "Maximum number of offers to process in this batch"
        required: false
        schema:
          type: integer
          default: 10
    responses:
      200:
        description: "Successfully processed a batch of job offers for skills."
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: success}
                processed_count: {type: integer, description: "Number of offers for which skills were successfully fetched and stored in this run"}
                timestamp: {type: string, format: date-time}
      500:
        description: "Error occurred during the processing of job offers."
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Failed to process job details: [Details]"}
    """
    logger.info("Route: GET /process-job-details")
    try:
        limit = request.args.get('limit', default=10, type=int)
        if limit <= 0:
            limit = 10 # Enforce a positive limit

        processed_count = services.process_pending_details_service(limit=limit)
        # This service function currently logs errors but doesn't raise them to here unless critical.
        # It returns the count of successfully processed offers.
        return jsonify({
            "status": "success",
            "processed_count": processed_count,
            "timestamp": services.datetime.now().isoformat() # Use services datetime for consistency
        }), 200
    except Exception as e:
        logger.exception("Route: Unexpected error in /process-job-details")
        return jsonify({"status": "error", "message": f"An internal server error occurred: {str(e)}"}), 500


@api_bp.route('/job-skills/<int:offer_id>', methods=['GET'])
def get_job_skills_route(offer_id):
    """
    Gets the stored skills for a specific job offer.
    ---
    tags:
      - Data Retrieval
    summary: Get skills for a specific job offer
    description: Retrieves the stored skills information (must, nice, extra categories) for a given job offer ID from the application's database.
    parameters:
      - name: offer_id
        in: path
        description: "The unique ID of the job offer"
        required: true
        schema:
          type: integer
          example: 12345
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
                  description: "Object containing arrays of skills per category."
                  properties:
                    must:
                      type: array
                      items: { $ref: '#/definitions/SkillDetail' }
                    nice:
                      type: array
                      items: { $ref: '#/definitions/SkillDetail' }
                    extra:
                      type: array
                      items: { $ref: '#/definitions/SkillDetail' }
      404:
        description: "Job offer with the specified ID was not found in the database."
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Job offer not found"}
      500:
        description: "An internal error occurred while retrieving job skills."
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Failed to retrieve job skills"}
    definitions:
      SkillDetail:
        type: object
        properties:
          skill: { type: string, example: "Python" }
          icon: { type: string, nullable: true, example: "python-icon.png" }
          level: { type: integer, nullable: true, example: 4 }
          desc: { type: string, nullable: true, example: "Experience with Django/Flask" }

    """
    logger.info(f"Route: GET /job-skills/{offer_id}")
    try:
        skills_data = services.get_job_skills_service(offer_id)
        if skills_data is None:
            return jsonify({"status": "error", "message": "Job offer not found"}), 404
        else:
            # Service returns the skills dict directly (or empty dict if skills retrieval failed but offer exists)
            return jsonify({"status": "success", "offer_id": offer_id, "skills": skills_data}), 200
    except Exception as e:
        logger.exception(f"Route: Unexpected error in /job-skills/{offer_id}")
        return jsonify({"status": "error", "message": "An internal server error occurred"}), 500


@api_bp.route('/send-notifications', methods=['GET'])
def send_pending_notifications_route():
    """
    Sends Discord notifications for job offers marked as not sent yet.
    ---
    tags:
      - Notifications
    summary: Send Discord notifications for pending job offers
    description: Checks the database for job offers where 'notification_sent' is false, attempts to send them to the configured Discord webhook (using a configurable limit), and updates their status in the database upon successful sending.
    parameters:
      - name: limit
        in: query
        description: "Maximum number of notifications to send in this batch"
        required: false
        schema:
          type: integer
          default: 5
    responses:
      200:
        description: Successfully processed the request to send pending notifications. Check counts for details.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: success}
                offers_sent: {type: integer, description: "Number of notifications successfully sent in this run"}
                remaining_pending: {type: integer, description: "Estimated number of offers still pending notification"}
      400:
        description: Bad Request, e.g., Discord webhook not configured.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "Discord webhook URL not configured"}
      500:
        description: Error processing or sending notifications.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: error}
                message: {type: string, example: "An internal server error occurred"}
    """
    logger.info("Route: GET /send-notifications")
    if not services.CONFIG['DISCORD_WEBHOOK_URL']:
         logger.warning("Route: /send-notifications called but DISCORD_WEBHOOK_URL is not set.")
         return jsonify({"status": "error", "message": "Discord webhook URL not configured"}), 400

    try:
        limit = request.args.get('limit', default=5, type=int)
        if limit <= 0:
            limit = 5 # Enforce a positive limit

        offers_sent, remaining_pending = services.send_pending_notifications_service(limit=limit)
        # Service function handles internal errors and logging, returns counts
        return jsonify({
            "status": "success",
            "offers_sent": offers_sent,
            "remaining_pending": remaining_pending
        }), 200
    except Exception as e:
        logger.exception("Route: Unexpected error in /send-notifications")
        return jsonify({"status": "error", "message": "An internal server error occurred"}), 500


@api_bp.route('/health', methods=['GET'])
def health_check_route():
    """
    Performs a health check on the service, including DB connectivity.
    ---
    tags:
      - System
    summary: System health check
    description: Checks essential components like database connectivity and returns the overall health status along with some basic configuration information.
    responses:
      200:
        description: System is healthy and operational.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: healthy}
                timestamp: {type: string, format: date-time}
                database_path: {type: string}
                database_status: {type: string, example: "connected"}
                webhook_configured: {type: boolean}
                config:
                    type: object
                    description: "Subset of operational configuration."
                    properties:
                        EXTERNAL_ENDPOINT_URL: { type: string }
                        MAX_RETRIES: { type: integer }
                        RETRY_BACKOFF: { type: number }
                        BUILD_ID_HASH: { type: string }

      503:
        description: Service Unavailable. A critical component (like the database) is not operational.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: unhealthy}
                timestamp: {type: string, format: date-time}
                database_path: {type: string}
                database_status: {type: string, example: "error: unable to open database file"}
                webhook_configured: {type: boolean}
                config: { type: object } # Config is still included
    """
    logger.debug("Route: GET /health")
    try:
        health_status_data, is_healthy = services.get_health_status_service()
        status_code = 200 if is_healthy else 503
        return jsonify(health_status_data), status_code
    except Exception as e:
        # This endpoint should be robust; only fail on truly unexpected errors
        logger.exception("Route: Unexpected error during health check")
        # Return an unhealthy status if the check itself fails critically
        return jsonify({
             "status": "unhealthy",
             "timestamp": services.datetime.now().isoformat(),
             "database_status": f"Health check failed: {str(e)}",
             "webhook_configured": bool(services.CONFIG.get('DISCORD_WEBHOOK_URL')),
             "config": {} # Avoid exposing config on critical failure
        }), 503

# --- END OF FILE routes.py ---