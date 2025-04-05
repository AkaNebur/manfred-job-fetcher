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
        
        # If not all skills were processed, log a warning
        if skills_processed_count < len(new_offer_dicts):
            logger.warning(f"Service: Only processed skills for {skills_processed_count}/{len(new_offer_dicts)} new offers.")
    else:
        logger.info("Service: No new offers found, skipping skills processing step.")

    # 4. Reload new_offer_dicts with the latest data including skills
    if new_offer_dicts:
        enriched_new_offers = []
        for offer in new_offer_dicts:
            offer_id = offer.get('id')
            if offer_id:
                # Get the full offer details from the database
                db_offer = database.get_offer_by_id(offer_id)
                if db_offer:
                    # Ensure we only send notifications for offers with skills
                    if db_offer.get('skills_retrieved', False):
                        # Create a new offer dict with the same structure as original but with DB data
                        enriched_offer = {
                            'id': db_offer['offer_id'],
                            'position': db_offer['position'],
                            'company': {
                                'name': db_offer['company_name'],
                                'logoDark': {'url': db_offer['company_logo_dark_url']} if db_offer['company_logo_dark_url'] else None
                            },
                            'remotePercentage': db_offer['remote_percentage'],
                            'salaryFrom': db_offer['salary_from'],
                            'salaryTo': db_offer['salary_to'],
                            'locations': db_offer['locations'].split(', ') if db_offer['locations'] else [],
                            'slug': db_offer['slug'] if db_offer['slug'] else f"job-{db_offer['offer_id']}"
                        }
                        enriched_new_offers.append(enriched_offer)
                    else:
                        logger.warning(f"Service: Skipping notification for offer ID {offer_id} because skills have not been retrieved yet.")
        # Replace the original list with the enriched one
        new_offer_dicts = enriched_new_offers

    # 5. Send notifications for NEW offers with skills
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
        logger.info("Service: No new offers with skills to notify.")


    # 6. Return Summary
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

            # 4. Extract and Store Skills and Languages
            if job_details and isinstance(job_details, dict):
                # Add additional logging to better diagnose skill section data
                logger.debug(f"Service: Job details for offer ID {offer_id}, keys: {list(job_details.keys())}")
                
                # Improved navigation to find the skills section
                skills_section = None
                skills_data = None
                languages_data = None
                
                # Primary path for skills section data
                if 'skillsSectionData' in job_details and isinstance(job_details.get('skillsSectionData'), dict):
                    skills_section = job_details.get('skillsSectionData')
                    logger.debug(f"Service: Found skills section via skillsSectionData for offer ID {offer_id}")
                
                # Alternative path in case structure has changed
                elif 'content' in job_details and isinstance(job_details.get('content'), dict):
                    content = job_details.get('content')
                    if 'skills' in content and isinstance(content.get('skills'), dict):
                        skills_section = content.get('skills')
                        logger.debug(f"Service: Found skills section via content.skills for offer ID {offer_id}")
                
                # Log skills section keys if found
                if skills_section:
                    logger.debug(f"Service: Skills section keys for offer ID {offer_id}: {list(skills_section.keys())}")
                    
                    # Get skills data
                    if 'skills' in skills_section:
                        skills_data = skills_section.get('skills')
                    elif 'must' in skills_section or 'nice' in skills_section or 'extra' in skills_section:
                        # The section itself might be the skills data
                        skills_data = skills_section
                    
                    # Get language requirements
                    if 'minLanguages' in skills_section:
                        languages_data = skills_section.get('minLanguages')
                    elif 'languages' in skills_section:
                        languages_data = skills_section.get('languages')
                
                if skills_data:
                    logger.debug(f"Service: Found skills data for offer ID {offer_id}: {list(skills_data.keys()) if isinstance(skills_data, dict) else 'not a dict'}")
                else:
                    logger.warning(f"Service: No skills data found for offer ID {offer_id} in the skills section")
                
                skills_stored = False
                languages_stored = False
                
                # Process skills if available
                if skills_data:
                    skills_stored = database.store_job_skills(offer_id, skills_data)
                    if not skills_stored:
                        logger.warning(f"Service: Failed to store skills for offer ID {offer_id} after fetching details.")
                else:
                    # No skills data but mark as retrieved
                    skills_stored = database.store_job_skills(offer_id, None)
                
                # Process languages if available
                if languages_data:
                    languages_stored = database.store_job_languages(offer_id, languages_data)
                    if not languages_stored:
                        logger.warning(f"Service: Failed to store languages for offer ID {offer_id} after fetching details.")
                
                # Mark as processed if either skills or languages were stored or if skills section exists but is empty
                if skills_stored or languages_stored or skills_section:
                    logger.info(f"Service: Successfully processed data for offer ID {offer_id}.")
                    processed_count += 1
                    # store_job_skills already marks as retrieved, even when skills are missing
                else:
                    # Both skills and languages processing failed, but job_details was fetched
                    logger.warning(f"Service: Fetched details for offer ID {offer_id}, but failed to process skills and languages.")
                    # Mark as retrieved to avoid retrying indefinitely
                    database.store_job_skills(offer_id, None) # Pass None to mark as retrieved
            elif job_details is not None:
                 # Details fetched, but skills section missing/empty or structure unexpected
                 logger.warning(f"Service: Fetched details for offer ID {offer_id}, but skills data was missing or in unexpected format. Marking as retrieved.")
                 # Mark as retrieved to avoid retrying this offer indefinitely if skills are genuinely missing
                 database.store_job_skills(offer_id, None) # Pass None to mark as retrieved
            else:
                 # fetch_job_details failed (logged internally)
                 logger.warning(f"Service: Failed to fetch job details for offer ID {offer_id}. It will be retried later.")
                 # Do not increment processed_count, do not mark as retrieved

        logger.info(f"Service: Finished processing pending details. Successfully processed data for {processed_count}/{len(pending_offers)} offers.")
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
    """Service layer function to retrieve skills and languages for a specific job offer."""
    logger.info(f"Service: Retrieving skills and languages for offer ID {offer_id}.")
    # Check if offer exists first
    offer_exists = database.get_offer_by_id(offer_id)
    if not offer_exists:
        logger.warning(f"Service: Offer ID {offer_id} not found in database.")
        return None # Indicate not found

    # Get skills data
    skills = database.get_job_skills_from_db(offer_id)
    
    # Get languages data
    languages = database.get_job_languages_from_db(offer_id)
    
    # Return combined result
    result = {
        'skills': skills,
        'languages': languages
    }
    
    return result

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

def cleanup_obsolete_job_notifications_service():
    """
    Service layer function to find jobs that are no longer in the latest fetch 
    and delete their Discord messages.
    Returns the number of messages deleted.
    """
    logger.info("Service: Starting cleanup of obsolete job notifications.")
    
    if not CONFIG['DISCORD_WEBHOOK_URL']:
        logger.warning("Service: Discord webhook URL not configured. Cannot delete notifications.")
        return 0
    
    deleted_count = 0
    try:
        # 1. Get latest active offer IDs
        latest_offers = manfred_api.fetch_raw_offers_list()
        if not latest_offers or not isinstance(latest_offers, list):
            logger.error("Service: Failed to fetch latest offers list for cleanup.")
            return 0
        
        active_offer_ids = [offer.get('id') for offer in latest_offers if offer.get('id')]
        logger.info(f"Service: Found {len(active_offer_ids)} active offers in latest fetch.")
        
        # 2. Find offers in our DB that have discord_message_id set but are no longer active
        obsolete_offers = database.get_obsolete_discord_notifications(active_offer_ids)
        if not obsolete_offers:
            logger.info("Service: No obsolete Discord notifications found.")
            return 0
        
        logger.info(f"Service: Found {len(obsolete_offers)} obsolete Discord notifications to clean up.")
        
        # 3. Delete each obsolete Discord message
        for offer in obsolete_offers:
            offer_id = offer.get('offer_id')
            message_id = offer.get('discord_message_id')
            
            if not message_id:
                continue
            
            # Delete the Discord message
            success = discord_notifier.delete_discord_message(message_id)
            if success:
                # Update the database to clear the message ID
                database.clear_discord_message_id(offer_id)
                deleted_count += 1
                logger.info(f"Service: Successfully deleted Discord message {message_id} for obsolete offer ID {offer_id}")
            else:
                logger.warning(f"Service: Failed to delete Discord message {message_id} for obsolete offer ID {offer_id}")
        
        logger.info(f"Service: Finished cleanup. Deleted {deleted_count}/{len(obsolete_offers)} obsolete Discord notifications.")
        return deleted_count
    
    except Exception as e:
        logger.error(f"Service: Error during cleanup of obsolete job notifications: {e}", exc_info=True)
        return deleted_count

# --- END OF FILE services.py ---