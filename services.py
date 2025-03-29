# --- START OF FILE services.py ---
import logging
from datetime import datetime

from config import CONFIG
import database
import manfred_api
import discord_notifier

logger = logging.getLogger(__name__)

def fetch_and_store_offers_service():
    """
    Service layer function to fetch offers, store/update them, process skills for new ones,
    and trigger notifications.
    Returns a dictionary summarizing the operation results.
    """
    start_time = datetime.now()
    logger.info("Service: Starting fetch and store offers process.")

    # 1. Fetch raw offers
    offers_list = manfred_api.fetch_raw_offers_list()

    if offers_list is None:
        logger.error("Service: Failed to fetch offers list from API.")
        return {"status": "error", "message": "Failed to fetch data from external API"}
    if not isinstance(offers_list, list):
        logger.error(f"Service: Expected a list from API, got {type(offers_list)}. Cannot process.")
        return {"status": "error", "message": "Invalid response format from external API - expected list"}

    total_fetched = len(offers_list)
    logger.info(f"Service: Fetched {total_fetched} offers from API.")

    # 2. Store/Update Offers in DB
    new_count, updated_count, new_offer_dicts = 0, 0, []
    try:
        new_count, updated_count, new_offer_dicts = database.store_or_update_offers(offers_list)
        logger.info(f"Service: DB update complete. New: {new_count}, Updated: {updated_count}.")
    except Exception as e:
        logger.error(f"Service: Error during offer storage: {e}", exc_info=True)
        # Depending on severity, might want to stop here or continue
        return {"status": "error", "message": f"Failed during offer storage: {str(e)}"}

    # 3. Process skills details for NEW offers
    skills_processed_count = 0
    if new_offer_dicts:
        logger.info(f"Service: Found {len(new_offer_dicts)} new offers. Processing skills details...")
        # We can directly pass the new offers to the processing function if needed,
        # or rely on the function querying the DB for offers with skills_retrieved = 0
        skills_processed_count = process_pending_details_service(limit=len(new_offer_dicts)) # Process up to the number of new offers
        logger.info(f"Service: Processed skills for {skills_processed_count} offers.")
    else:
        logger.info("Service: No new offers found, skipping skills processing step.")

    # 4. Send notifications for NEW offers
    webhook_sent_count = 0
    if new_offer_dicts and CONFIG['DISCORD_WEBHOOK_URL']:
        logger.info(f"Service: Sending {len(new_offer_dicts)} new offers to Discord webhook...")
        # Use the list of new offers directly
        webhook_sent_count = discord_notifier.send_batch_notifications(new_offer_dicts)

        # Update notification status in DB for successfully sent offers
        if webhook_sent_count > 0:
            sent_offer_ids = [offer['id'] for offer in new_offer_dicts[:webhook_sent_count] if 'id' in offer]
            if sent_offer_ids:
                database.update_notification_status(sent_offer_ids)
            else:
                logger.warning("Webhook reported sending messages, but could not extract offer IDs to update status.")
    elif not CONFIG['DISCORD_WEBHOOK_URL']:
         logger.info("Service: Discord webhook URL not configured, skipping notification step.")
    else:
        logger.info("Service: No new offers to notify.")


    # 5. Return Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    logger.info(f"Service: Fetch and store process finished in {duration:.2f} seconds.")
    return {
        "status": "success",
        "total_fetched": total_fetched,
        "new_offers": new_count,
        "updated_offers": updated_count,
        "skills_processed": skills_processed_count,
        "webhook_sent": webhook_sent_count,
        "timestamp": start_time.isoformat(),
        "duration_seconds": round(duration, 2)
    }


def process_pending_details_service(limit=10):
    """
    Service layer function to process job offers that don't have detailed skills information yet.
    Returns the number of offers for which skills were successfully processed and stored.
    """
    logger.info(f"Service: Starting process pending job details (limit {limit}).")
    processed_count = 0
    try:
        # 1. Get offers needing processing from DB
        pending_offers = database.get_pending_skill_offers(limit)

        if not pending_offers:
            logger.info("Service: No pending job details to process.")
            return 0

        logger.info(f"Service: Found {len(pending_offers)} offers pending skill details.")

        # 2. Iterate and process each offer
        for offer_row in pending_offers:
            offer_id = offer_row['offer_id']
            slug = offer_row['slug']

            # 3. Fetch details from API
            job_details = manfred_api.fetch_job_details_data(offer_id, slug)

            # 4. Extract and Store Skills
            skills_data = None
            if job_details and isinstance(job_details, dict):
                # Navigate the structure to find skills
                skills_data = job_details.get('skillsSectionData', {}).get('skills') if isinstance(job_details.get('skillsSectionData'), dict) else None

            if skills_data:
                 # Attempt to store skills in DB
                if database.store_job_skills(offer_id, skills_data):
                    logger.info(f"Service: Successfully processed and stored skills for offer ID {offer_id}.")
                    processed_count += 1
                else:
                    # store_job_skills logs the error internally
                    logger.warning(f"Service: Failed to store skills for offer ID {offer_id} after fetching details.")
                    # Decide whether to mark as retrieved anyway to prevent retries?
                    # Current logic in store_job_skills handles marking retrieved even on failure/no skills.
            elif job_details is not None:
                 # Details fetched, but skills section missing/empty or structure unexpected
                 logger.warning(f"Service: Fetched details for offer ID {offer_id}, but skills data was missing or in unexpected format. Marking as retrieved.")
                 # Mark as retrieved to avoid retrying this offer indefinitely if skills are genuinely missing
                 database.store_job_skills(offer_id, None) # Pass None to mark as retrieved
            else:
                 # fetch_job_details failed (logged internally)
                 logger.warning(f"Service: Failed to fetch job details for offer ID {offer_id}. It will be retried later.")
                 # Do not increment processed_count, do not mark as retrieved

        logger.info(f"Service: Finished processing pending details. Successfully processed skills for {processed_count}/{len(pending_offers)} offers.")
        return processed_count

    except Exception as e:
        logger.error(f"Service: Error during the overall processing of pending job details: {e}", exc_info=True)
        return processed_count # Return count processed so far

def send_pending_notifications_service(limit=5):
    """
    Service layer function to find pending notifications and send them.
    Returns the number of notifications successfully sent.
    """
    logger.info(f"Service: Starting send pending notifications (limit {limit}).")

    if not CONFIG['DISCORD_WEBHOOK_URL']:
        logger.warning("Service: Discord webhook URL not configured. Cannot send notifications.")
        return 0, 0 # Sent count, remaining count

    offers_sent_count = 0
    offers_to_send_dicts = []
    try:
        # 1. Get offers pending notification from DB
        pending_db_offers = database.get_pending_notification_offers(limit=limit * 2) # Fetch more to estimate remaining
        if not pending_db_offers:
             logger.info("Service: No pending notifications found in database.")
             return 0, 0

        logger.info(f"Service: Found {len(pending_db_offers)} potential offers pending notification.")

        # 2. Convert DB rows to dictionaries expected by notifier
        for offer_row in pending_db_offers:
             # Reconstruct the dictionary format needed by _build_discord_embed
             offers_to_send_dicts.append({
                 'id': offer_row['offer_id'],
                 'position': offer_row['position'],
                 'company': {
                     'name': offer_row['company_name'],
                     # Ensure logoDark structure exists if URL is present
                     'logoDark': {'url': offer_row['company_logo_dark_url']} if offer_row['company_logo_dark_url'] else None
                 },
                 'remotePercentage': offer_row['remote_percentage'],
                 'salaryFrom': offer_row['salary_from'],
                 'salaryTo': offer_row['salary_to'],
                 # Safely split locations string back into a list
                 'locations': offer_row['locations'].split(', ') if offer_row['locations'] else [],
                 'slug': offer_row['slug'] if offer_row['slug'] else f"job-{offer_row['offer_id']}"
             })

        # 3. Send notifications in a batch
        if offers_to_send_dicts:
            offers_sent_count = discord_notifier.send_batch_notifications(offers_to_send_dicts, batch_size=limit)

            # 4. Update DB status for successfully sent offers
            if offers_sent_count > 0:
                sent_offer_ids = [offer['id'] for offer in offers_to_send_dicts[:offers_sent_count] if 'id' in offer]
                if sent_offer_ids:
                     database.update_notification_status(sent_offer_ids)
                else:
                    logger.warning("Notifier reported sending messages, but could not extract offer IDs to update status.")

        remaining_pending = max(0, len(pending_db_offers) - offers_sent_count)
        logger.info(f"Service: Finished sending pending notifications. Sent: {offers_sent_count}, Approx Remaining: {remaining_pending}")
        return offers_sent_count, remaining_pending

    except Exception as e:
        logger.error(f"Service: Error during sending pending notifications: {e}", exc_info=True)
        # Return 0 sent, and potentially inaccurate remaining count on error
        return 0, len(offers_to_send_dicts)


def get_job_skills_service(offer_id):
    """Service layer function to retrieve skills for a specific job offer."""
    logger.info(f"Service: Retrieving skills for offer ID {offer_id}.")
    # Check if offer exists first
    offer_exists = database.get_offer_by_id(offer_id)
    if not offer_exists:
        logger.warning(f"Service: Offer ID {offer_id} not found in database.")
        return None # Indicate not found

    skills = database.get_job_skills_from_db(offer_id)
    # The DB function handles logging if retrieval fails, returns empty dict
    return skills

def get_health_status_service():
    """Service layer function to check system health."""
    logger.debug("Service: Performing health check.")
    db_ok, db_status_msg = database.check_db_connection()
    webhook_configured = bool(CONFIG['DISCORD_WEBHOOK_URL'])

    is_healthy = db_ok # Add other checks here if needed

    # Selectively expose configuration relevant to health/operation
    relevant_config = {
        k: CONFIG[k] for k in [
            'EXTERNAL_ENDPOINT_URL',
            'MAX_RETRIES',
            'RETRY_BACKOFF',
            'BUILD_ID_HASH' # Important for details fetching
            ] if k in CONFIG
        }

    health_status = {
        "status": "healthy" if is_healthy else "unhealthy",
        "timestamp": datetime.now().isoformat(),
        "database_path": CONFIG['DB_PATH'],
        "database_status": db_status_msg,
        "webhook_configured": webhook_configured,
        "config": relevant_config
    }
    logger.debug(f"Service: Health status: {health_status}")
    return health_status, is_healthy

# --- END OF FILE services.py ---