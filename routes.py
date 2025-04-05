# --- START OF FILE routes.py ---
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Path, status
from fastapi.responses import JSONResponse

import services
import manfred_api
from models import (
    OffersList, StoreOffersResponse, ProcessDetailsResponse,
    JobSkillsResponse, NotificationsResponse, HealthCheckResponse
)

logger = logging.getLogger(__name__)

# Create a router instead of a Blueprint
router = APIRouter()


@router.get("/raw-offers", 
    response_model=OffersList,
    summary="Get raw job offers list from Manfred API",
    description="Directly fetches and returns the JSON response from the configured EXTERNAL_ENDPOINT_URL without processing or saving.",
    response_description="Raw list of active job offers from the external API.",
    tags=["Raw Data"])
async def get_raw_offers():
    logger.info("Route: GET /raw-offers")
    try:
        # Use the API function directly for raw data
        data = manfred_api.fetch_raw_offers_list()
        if data is not None:
            # Check if it's a list (as expected) or handle other valid JSON types if needed
            if isinstance(data, (list, dict)):
                return data
            else:
                logger.error(f"Raw offers: Unexpected data type returned: {type(data)}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unexpected data type received from external API"
                )
        else:
            # fetch_raw_offers_list already logged the error
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch data from external API"
            )
    except Exception as e:
        logger.exception("Route: Unexpected error in /raw-offers")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred"
        )


@router.get("/store-offers", 
    response_model=StoreOffersResponse,
    summary="Fetch, store/update job offers, process skills, notify",
    description="Orchestrates fetching offers, storing new/updating existing ones, attempting to fetch skills for new offers, and sending Discord notifications for new offers.",
    response_description="Summary of actions performed.",
    tags=["Data Storage & Processing"])
async def store_offers_route():
    logger.info("Route: GET /store-offers")
    try:
        result = services.fetch_and_store_offers_service()
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR if result.get("status") == "error" else status.HTTP_200_OK
        
        # Handle specific upstream errors resulting in 502
        if "Invalid response format" in result.get("message", "") or \
           "Failed to fetch data" in result.get("message", ""):
            return JSONResponse(content=result, status_code=status.HTTP_502_BAD_GATEWAY)
            
        return JSONResponse(content=result, status_code=status_code)
    except Exception as e:
        logger.exception("Route: Unexpected error in /store-offers")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred"
        )


@router.get("/process-job-details", 
    response_model=ProcessDetailsResponse,
    summary="Process job offers to fetch and store detailed skills information",
    description="Finds job offers marked as needing skills details, fetches their data from the Manfred API, stores the extracted skills, and marks the offer as processed.",
    response_description="Information about the processing batch.",
    tags=["Data Processing"])
async def process_job_details_route(limit: int = Query(10, description="Maximum number of offers to process in this batch")):
    logger.info("Route: GET /process-job-details")
    try:
        if limit <= 0:
            limit = 10  # Enforce a positive limit

        processed_count = services.process_pending_details_service(limit=limit)
        
        return {
            "status": "success",
            "processed_count": processed_count,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.exception("Route: Unexpected error in /process-job-details")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An internal server error occurred: {str(e)}"
        )


@router.get("/job-skills/{offer_id}", 
    response_model=JobSkillsResponse,
    summary="Get skills and language requirements for a specific job offer",
    description="Retrieves the stored skills information and language requirements for a given job offer ID.",
    response_description="Job skills and language requirements.",
    tags=["Data Retrieval"])
async def get_job_skills_route(offer_id: int = Path(..., description="The unique ID of the job offer")):
    logger.info(f"Route: GET /job-skills/{offer_id}")
    try:
        result = services.get_job_skills_service(offer_id)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job offer not found"
            )
        else:
            return {
                "status": "success",
                "offer_id": offer_id,
                "skills": result['skills'],
                "languages": result['languages']
            }
    except HTTPException:
        raise  # Re-raise HTTPExceptions
    except Exception as e:
        logger.exception(f"Route: Unexpected error in /job-skills/{offer_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred"
        )


@router.get("/send-notifications", 
    response_model=NotificationsResponse,
    summary="Send Discord notifications for pending job offers",
    description="Checks the database for job offers where 'notification_sent' is false, attempts to send them to the configured Discord webhook, and updates their status in the database.",
    response_description="Information about notifications sent.",
    tags=["Notifications"])
async def send_pending_notifications_route(limit: int = Query(5, description="Maximum number of notifications to send in this batch")):
    logger.info("Route: GET /send-notifications")
    if not services.CONFIG['DISCORD_WEBHOOK_URL']:
        logger.warning("Route: /send-notifications called but DISCORD_WEBHOOK_URL is not set.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discord webhook URL not configured"
        )

    try:
        if limit <= 0:
            limit = 5  # Enforce a positive limit

        offers_sent, remaining_pending = services.send_pending_notifications_service(limit=limit)
        
        return {
            "status": "success",
            "offers_sent": offers_sent,
            "remaining_pending": remaining_pending
        }
    except Exception as e:
        logger.exception("Route: Unexpected error in /send-notifications")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred"
        )


@router.get("/update-build-hash", 
    summary="Update BUILD_ID_HASH",
    description="Attempts to fetch and update the BUILD_ID_HASH from the Manfred website.",
    response_description="Result of the hash update operation.",
    tags=["System"])
async def update_build_hash_route():
    logger.info("Route: GET /update-build-hash")
    try:
        # Import the function from manfred_api
        from manfred_api import fetch_and_update_build_id_hash
        
        # Store the original hash for comparison
        original_hash = services.CONFIG['BUILD_ID_HASH']
        
        # Attempt to update the hash
        success = fetch_and_update_build_id_hash()
        
        if success:
            if original_hash != services.CONFIG['BUILD_ID_HASH']:
                return {
                    "status": "success",
                    "message": f"Successfully updated BUILD_ID_HASH from {original_hash} to {services.CONFIG['BUILD_ID_HASH']}",
                    "current_hash": services.CONFIG['BUILD_ID_HASH']
                }
            else:
                return {
                    "status": "success",
                    "message": f"BUILD_ID_HASH is already up-to-date: {services.CONFIG['BUILD_ID_HASH']}",
                    "current_hash": services.CONFIG['BUILD_ID_HASH']
                }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update BUILD_ID_HASH"
            )
    except Exception as e:
        logger.exception("Route: Unexpected error in /update-build-hash")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An internal server error occurred: {str(e)}"
        )


@router.get("/health", 
    response_model=HealthCheckResponse,
    summary="System health check",
    description="Checks essential components like database connectivity and returns the overall health status.",
    response_description="System health status.",
    tags=["System"])
async def health_check_route():
    logger.debug("Route: GET /health")
    try:
        health_status_data, is_healthy = services.get_health_status_service()
        status_code = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(content=health_status_data, status_code=status_code)
    except Exception as e:
        # This endpoint should be robust; only fail on truly unexpected errors
        logger.exception("Route: Unexpected error during health check")
        # Return an unhealthy status if the check itself fails critically
        return JSONResponse(
            content={
                "status": "unhealthy",
                "timestamp": datetime.now().isoformat(),
                "database_status": f"Health check failed: {str(e)}",
                "webhook_configured": bool(services.CONFIG.get('DISCORD_WEBHOOK_URL')),
                "config": {}  # Avoid exposing config on critical failure
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@router.get("/cleanup-notifications", 
    summary="Clean up obsolete job notifications",
    description="Deletes Discord messages for job offers that are no longer active.",
    response_description="Information about the cleanup operation.",
    tags=["Notifications"])
async def cleanup_notifications_route():
    logger.info("Route: GET /cleanup-notifications")
    if not services.CONFIG['DISCORD_WEBHOOK_URL']:
        logger.warning("Route: /cleanup-notifications called but DISCORD_WEBHOOK_URL is not set.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discord webhook URL not configured"
        )
        
    try:
        deleted_count = services.cleanup_obsolete_job_notifications_service()
        
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.exception("Route: Unexpected error in /cleanup-notifications")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred"
        )
# --- END OF FILE routes.py ---